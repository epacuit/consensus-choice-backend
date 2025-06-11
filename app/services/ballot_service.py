import secrets
from datetime import datetime
from typing import List, Optional, Dict
from bson import ObjectId
from collections import defaultdict
import hashlib
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
        user_agent: Optional[str] = None,
        count: int = 1,  # Allow specifying count for bulk operations
        import_batch_id: Optional[str] = None
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
        elif ballot_data.test_mode_key == 'admin_import' or count > 1:
            # Bulk import or aggregated votes
            voter_type = VoterType.AGGREGATED
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
            
            if voter["has_voted"] and not is_test and count == 1:
                raise ValueError("Voter has already submitted a ballot")
            
            voter_type = VoterType.AUTHENTICATED
            voter_email = voter["email"]
        else:
            # Public poll - check for duplicate votes only for individual ballots
            if ballot_data.browser_fingerprint and not is_test and count == 1:
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
            "count": count,  # Store the count
            "voter_email": voter_email if count == 1 else None,  # Only for individual ballots
            "voter_token": ballot_data.voter_token if count == 1 else None,
            "browser_fingerprint": ballot_data.browser_fingerprint if count == 1 else None,
            "submitted_at": datetime.utcnow(),
            "ip_address": ip_address,
            "user_agent": user_agent,
            "import_batch_id": import_batch_id,
            "is_test": is_test
        }
        
        # Insert ballot
        result = await self.ballots_collection.insert_one(ballot_doc)
        
        # Update voter status for private polls (only for individual non-test votes)
        if poll.is_private and voter_type == VoterType.AUTHENTICATED and not is_test and count == 1:
            await self._mark_voter_as_voted(
                ballot_data.poll_id,
                ballot_data.voter_token
            )
        
        # Update poll vote count
        await self._increment_vote_count(ballot_data.poll_id, count, is_test)
        
        # Get and return the created ballot
        created_ballot = await self.ballots_collection.find_one({"_id": result.inserted_id})
        return self._doc_to_ballot(created_ballot)

    async def bulk_import_ballots(
        self,
        poll_id: str,
        ballots: List[BallotSubmit],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        use_aggregation: bool = True,
        batch_name: Optional[str] = None
    ) -> Dict[str, int]:
        """Bulk import multiple ballots with optional aggregation"""
        
        # First validate the poll exists and is active
        poll = await self.poll_service.get_poll(poll_id)
        if not poll:
            raise ValueError(f"Poll {poll_id} not found")
        
        if poll.has_closed:
            raise ValueError("Poll has closed")
        
        # Generate batch ID
        batch_id = f"{datetime.utcnow().isoformat()}_{batch_name or 'bulk'}"
        
        if use_aggregation:
            # Aggregate identical rankings
            ranking_counts = defaultdict(int)
            ranking_examples = {}
            
            for ballot in ballots:
                # Create a hashable representation of the ranking
                ranking_key = tuple((r.option_id, r.rank) for r in sorted(ballot.rankings, key=lambda x: x.rank))
                ranking_counts[ranking_key] += 1
                
                # Store one example of each ranking pattern
                if ranking_key not in ranking_examples:
                    ranking_examples[ranking_key] = ballot
            
            # Insert aggregated ballots
            imported_count = 0
            failed_count = 0
            
            for ranking_key, count in ranking_counts.items():
                try:
                    ballot_data = ranking_examples[ranking_key]
                    ballot_data.poll_id = poll_id
                    ballot_data.test_mode_key = 'admin_import'
                    
                    # Submit as an aggregated ballot with count > 1
                    await self.submit_ballot(
                        ballot_data,
                        ip_address=ip_address,
                        user_agent=f"{user_agent} (bulk import)",
                        count=count,
                        import_batch_id=batch_id
                    )
                    imported_count += count
                    
                except Exception as e:
                    failed_count += count
                    print(f"Failed to import {count} ballots: {str(e)}")
            
            return {
                "imported_count": imported_count,
                "unique_patterns": len(ranking_counts),
                "batch_id": batch_id,
                "failed_count": failed_count,
                "message": f"Imported {imported_count} votes with {len(ranking_counts)} unique ranking patterns"
            }
        
        else:
            # Import each ballot individually
            imported_count = 0
            failed_count = 0
            errors = []
            
            for i, ballot_data in enumerate(ballots):
                try:
                    ballot_data.poll_id = poll_id
                    ballot_data.test_mode_key = 'admin_import'
                    
                    await self.submit_ballot(
                        ballot_data,
                        ip_address=ip_address,
                        user_agent=f"{user_agent} (bulk import ballot {i+1})",
                        count=1,
                        import_batch_id=batch_id
                    )
                    imported_count += 1
                    
                except Exception as e:
                    failed_count += 1
                    errors.append(f"Ballot {i+1}: {str(e)}")
            
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
                "batch_id": batch_id,
                "message": message
            }

    async def get_live_results(self, poll_id: str, include_test: bool = False) -> VoteResults:
        """Calculate live voting results with count-aware processing"""
        poll = await self.poll_service.get_poll(poll_id)
        if not poll:
            raise ValueError(f"Poll {poll_id} not found")
        
        # Initialize result structures
        first_place_counts = {opt.id: 0 for opt in poll.options}
        ranking_matrix = {opt.id: {} for opt in poll.options}
        pairwise_matrix = {opt.id: {other.id: 0 for other in poll.options if other.id != opt.id} 
                          for opt in poll.options}
        
        total_ballots = 0
        total_ballot_records = 0
        total_test_ballots = 0
        
        # Get all ballots
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        ballots = await self.ballots_collection.find(query).to_list(length=None)
        
        for ballot_doc in ballots:
            count = ballot_doc.get("count", 1)  # Default to 1 for old ballots
            total_ballot_records += 1
            
            if not ballot_doc.get("is_test", False):
                total_ballots += count
            else:
                total_test_ballots += count
            
            rankings = ballot_doc["rankings"]
            
            # Process rankings with count multiplier
            for ranking in rankings:
                option_id = ranking["option_id"]
                rank = ranking["rank"]
                
                # Count first place votes
                if rank == 1:
                    first_place_counts[option_id] += count
                
                # Update ranking matrix
                if rank not in ranking_matrix[option_id]:
                    ranking_matrix[option_id][rank] = 0
                ranking_matrix[option_id][rank] += count
            
            # Calculate pairwise preferences
            ranked_options = {r["option_id"]: r["rank"] for r in rankings}
            for opt1 in ranked_options:
                for opt2 in ranked_options:
                    if opt1 != opt2:
                        if ranked_options[opt1] < ranked_options[opt2]:
                            pairwise_matrix[opt1][opt2] += count
        
        # If including test ballots, count them separately
        if include_test:
            test_query = {"poll_id": poll_id, "is_test": True}
            test_ballots = await self.ballots_collection.find(test_query).to_list(length=None)
            total_test_ballots = sum(b.get("count", 1) for b in test_ballots)
        
        # Convert ranking_matrix to Dict[str, Dict[int, int]] format
        ranking_matrix_formatted = {
            option_id: {int(rank): count for rank, count in ranks.items()}
            for option_id, ranks in ranking_matrix.items()
        }
        
        return VoteResults(
            poll_id=poll_id,
            total_ballots=total_ballots,
            total_ballot_records=total_ballot_records,
            total_test_ballots=total_test_ballots,
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
        """Check if a browser fingerprint has already voted (only for individual ballots)"""
        existing = await self.ballots_collection.find_one({
            "poll_id": poll_id,
            "browser_fingerprint": fingerprint,
            "count": 1,  # Only check individual ballots
            "is_test": {"$ne": True}
        })
        return existing is not None

    async def _increment_vote_count(self, poll_id: str, count: int = 1, is_test: bool = False):
        """Increment the vote count for a poll"""
        if not is_test:
            update_doc = {
                "$inc": {"vote_count": count},
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
            count=doc.get("count", 1),  # Default to 1 for old ballots
            voter_email=doc.get("voter_email"),
            voter_token=doc.get("voter_token"),
            browser_fingerprint=doc.get("browser_fingerprint"),
            submitted_at=doc["submitted_at"],
            ip_address=doc.get("ip_address"),
            user_agent=doc.get("user_agent"),
            import_batch_id=doc.get("import_batch_id"),
            is_test=doc.get("is_test", False)
        )
    
    async def get_import_batches(self, poll_id: str) -> List[Dict]:
        """Get list of import batches for a poll"""
        pipeline = [
            {"$match": {"poll_id": poll_id, "import_batch_id": {"$ne": None}}},
            {"$group": {
                "_id": "$import_batch_id",
                "total_votes": {"$sum": "$count"},
                "ballot_records": {"$sum": 1},
                "imported_at": {"$first": "$submitted_at"}
            }},
            {"$sort": {"imported_at": -1}}
        ]
        
        batches = await self.ballots_collection.aggregate(pipeline).to_list(length=None)
        
        return [
            {
                "batch_id": batch["_id"],
                "total_votes": batch["total_votes"],
                "ballot_records": batch["ballot_records"],
                "imported_at": batch["imported_at"].isoformat() if batch["imported_at"] else None
            }
            for batch in batches
        ]