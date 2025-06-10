import secrets
from datetime import datetime
from typing import List, Optional, Dict
from bson import ObjectId
from ..database import db
from ..models.ballot import (
    Ballot, BallotSubmit, VoteResults,
    VoterType, RankingEntry
)
from .poll_service import PollService
from ..config import settings

class BallotService:
    def __init__(self):
        self.poll_service = PollService()
        # Use SECRET_KEY from settings for test mode
        self.TEST_MODE_KEY = settings.SECRET_KEY
    
    @property
    def ballots_collection(self):
        return db.database.ballots
    
    @property
    def polls_collection(self):
        return db.database.polls

    async def submit_ballot(
        self, 
        ballot_data: BallotSubmit,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Ballot:
        """Submit a ballot for a poll"""
        
        # Get the poll
        poll = await self.poll_service.get_poll(ballot_data.poll_id)
        if not poll:
            raise ValueError(f"Poll {ballot_data.poll_id} not found")
        
        if poll.has_closed:
            raise ValueError("Poll has closed")
        
        # Validate option IDs
        valid_option_ids = {opt.id for opt in poll.options}
        for ranking in ballot_data.rankings:
            if ranking.option_id not in valid_option_ids:
                raise ValueError(f"Invalid option ID: {ranking.option_id}")
        
        # Determine voter type and validate
        voter_type = VoterType.ANONYMOUS
        voter_email = None
        is_test = False
        
        # Check for test mode first
        if ballot_data.test_mode_key == self.TEST_MODE_KEY:
            voter_type = VoterType.TEST
            is_test = True
        elif ballot_data.test_mode_key == 'admin_import':
            # Special case for admin imports - treat as regular votes, not test votes
            voter_type = VoterType.ANONYMOUS
            is_test = False
        elif poll.is_private:
            # Private poll - require token
            if not ballot_data.voter_token:
                raise ValueError("Voter token required for private poll")
            
            # Validate token and check if already voted
            voter = await self._validate_private_voter(
                ballot_data.poll_id, 
                ballot_data.voter_token
            )
            if not voter:
                raise ValueError("Invalid voter token")
            
            if voter["has_voted"] and not is_test:
                raise ValueError("Voter has already submitted a ballot")
            
            voter_type = VoterType.AUTHENTICATED
            voter_email = voter["email"]
        else:
            # Public poll - check for duplicate votes
            if ballot_data.browser_fingerprint and not is_test:
                duplicate = await self._check_duplicate_public_vote(
                    ballot_data.poll_id,
                    ballot_data.browser_fingerprint
                )
                if duplicate:
                    raise ValueError("A ballot has already been submitted from this browser")
        
        # Create ballot document
        ballot_doc = {
            "poll_id": ballot_data.poll_id,
            "voter_type": voter_type.value,
            "rankings": [r.model_dump() for r in ballot_data.rankings],
            "voter_email": voter_email,
            "voter_token": ballot_data.voter_token,
            "browser_fingerprint": ballot_data.browser_fingerprint,
            "submitted_at": datetime.utcnow(),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "is_test": is_test
        }
        
        # Insert ballot
        result = await self.ballots_collection.insert_one(ballot_doc)
        
        # Update voter status for private polls (only for non-test votes)
        if poll.is_private and voter_type == VoterType.AUTHENTICATED and not is_test:
            await self._mark_voter_as_voted(
                ballot_data.poll_id,
                ballot_data.voter_token
            )
        
        # Update poll vote count
        await self._increment_vote_count(ballot_data.poll_id, is_test)
        
        # Get and return the created ballot
        created_ballot = await self.ballots_collection.find_one({"_id": result.inserted_id})
        return self._doc_to_ballot(created_ballot)

    async def bulk_import_ballots(
        self,
        poll_id: str,
        ballots: List[BallotSubmit],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, int]:
        """Bulk import multiple ballots for a poll"""
        
        # First validate the poll exists and is active
        poll = await self.poll_service.get_poll(poll_id)
        if not poll:
            raise ValueError(f"Poll {poll_id} not found")
        
        if poll.has_closed:
            raise ValueError("Poll has closed")
        
        # Track results
        imported_count = 0
        failed_count = 0
        errors = []
        
        # Process each ballot
        for i, ballot_data in enumerate(ballots):
            try:
                # Ensure poll_id is set correctly
                ballot_data.poll_id = poll_id
                
                # Submit the ballot
                await self.submit_ballot(
                    ballot_data,
                    ip_address=ip_address,
                    user_agent=f"{user_agent} (bulk import ballot {i+1})"
                )
                imported_count += 1
                
            except Exception as e:
                failed_count += 1
                errors.append(f"Ballot {i+1}: {str(e)}")
        
        # Create result message
        message = f"Successfully imported {imported_count} ballots"
        if failed_count > 0:
            message += f", {failed_count} failed"
            if len(errors) <= 3:
                message += f": {'; '.join(errors)}"
            else:
                message += f": {'; '.join(errors[:3])}... and {len(errors)-3} more"
        
        return {
            "imported_count": imported_count,
            "failed_count": failed_count,
            "message": message
        }

    async def get_live_results(self, poll_id: str, include_test: bool = False) -> VoteResults:
        """Calculate live voting results"""
        poll = await self.poll_service.get_poll(poll_id)
        if not poll:
            raise ValueError(f"Poll {poll_id} not found")
        
        # Get all ballots
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        ballots = await self.ballots_collection.find(query).to_list(length=None)
        
        # Initialize result structures
        first_place_counts = {opt.id: 0 for opt in poll.options}
        ranking_matrix = {opt.id: {} for opt in poll.options}
        pairwise_matrix = {opt.id: {other.id: 0 for other in poll.options if other.id != opt.id} 
                          for opt in poll.options}
        
        total_ballots = 0
        total_test_ballots = 0
        
        # Count test ballots separately
        test_ballot_count = await self.ballots_collection.count_documents({
            "poll_id": poll_id,
            "is_test": True
        })
        
        for ballot_doc in ballots:
            if not ballot_doc.get("is_test", False):
                total_ballots += 1
            
            rankings = ballot_doc["rankings"]
            
            # Process rankings
            for ranking in rankings:
                option_id = ranking["option_id"]
                rank = ranking["rank"]
                
                # Count first place votes
                if rank == 1:
                    first_place_counts[option_id] += 1
                
                # Update ranking matrix
                if rank not in ranking_matrix[option_id]:
                    ranking_matrix[option_id][rank] = 0
                ranking_matrix[option_id][rank] += 1
            
            # Calculate pairwise preferences
            ranked_options = {r["option_id"]: r["rank"] for r in rankings}
            for opt1 in ranked_options:
                for opt2 in ranked_options:
                    if opt1 != opt2:
                        if ranked_options[opt1] < ranked_options[opt2]:
                            # opt1 is ranked better than opt2
                            pairwise_matrix[opt1][opt2] += 1
        
        # Convert ranking_matrix to Dict[str, Dict[int, int]] format
        ranking_matrix_formatted = {
            option_id: {int(rank): count for rank, count in ranks.items()}
            for option_id, ranks in ranking_matrix.items()
        }
        
        return VoteResults(
            poll_id=poll_id,
            total_ballots=total_ballots,
            total_test_ballots=test_ballot_count,
            first_place_counts=first_place_counts,
            ranking_matrix=ranking_matrix_formatted,
            pairwise_matrix=pairwise_matrix,
            last_updated=datetime.utcnow()
        )

    async def _validate_private_voter(self, poll_id: str, token: str) -> Optional[dict]:
        """Validate a voter token for a private poll"""
        poll_doc = await self.polls_collection.find_one(
            {
                "_id": ObjectId(poll_id),
                "voters.token": token
            },
            {"voters.$": 1}
        )
        
        if poll_doc and "voters" in poll_doc and poll_doc["voters"]:
            return poll_doc["voters"][0]
        return None

    async def _mark_voter_as_voted(self, poll_id: str, token: str):
        """Mark a voter as having voted"""
        await self.polls_collection.update_one(
            {
                "_id": ObjectId(poll_id),
                "voters.token": token
            },
            {
                "$set": {
                    "voters.$.has_voted": True,
                    "voters.$.voted_at": datetime.utcnow()
                }
            }
        )

    async def _check_duplicate_public_vote(self, poll_id: str, fingerprint: str) -> bool:
        """Check if a browser fingerprint has already voted"""
        existing = await self.ballots_collection.find_one({
            "poll_id": poll_id,
            "browser_fingerprint": fingerprint,
            "is_test": {"$ne": True}
        })
        return existing is not None

    async def _increment_vote_count(self, poll_id: str, is_test: bool = False):
        """Increment the vote count for a poll"""
        update_doc = {
            "$inc": {"vote_count": 1},
            "$set": {"last_vote_at": datetime.utcnow()}
        }
        
        await self.polls_collection.update_one(
            {"_id": ObjectId(poll_id)},
            update_doc
        )

    def _doc_to_ballot(self, doc: dict) -> Ballot:
        """Convert document to Ballot model"""
        return Ballot(
            id=str(doc["_id"]),
            poll_id=doc["poll_id"],
            voter_type=VoterType(doc["voter_type"]),
            rankings=[RankingEntry(**r) for r in doc["rankings"]],
            voter_email=doc.get("voter_email"),
            voter_token=doc.get("voter_token"),
            browser_fingerprint=doc.get("browser_fingerprint"),
            submitted_at=doc["submitted_at"],
            ip_address=doc.get("ip_address"),
            user_agent=doc.get("user_agent"),
            is_test=doc.get("is_test", False)
        )