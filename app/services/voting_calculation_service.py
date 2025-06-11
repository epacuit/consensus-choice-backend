from typing import List, Dict, Optional, Tuple
from ..database import db
from ..models.ballot import RankingEntry
from pref_voting.profiles_with_ties import ProfileWithTies

class VotingCalculationService:
    """Service for creating voting profiles with count-aware ballot processing"""
    
    @property
    def ballots_collection(self):
        return db.database.ballots
    
    async def create_profile_with_ties(
        self, 
        poll_id: str, 
        candidates: List[str],
        option_id_to_candidate: Dict[str, str],
        include_test: bool = False
    ) -> ProfileWithTies:
        """Create ProfileWithTies from ballots
        
        Args:
            poll_id: The poll ID
            candidates: List of candidate names (e.g., ["A", "B", "C"] or ["C0", "C1", "C2"])
            option_id_to_candidate: Mapping from database option IDs to candidate names
            include_test: Whether to include test ballots
        """
        
        # Get all ballots
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        ballots = await self.ballots_collection.find(query).to_list(length=None)
        
        if not ballots:
            return ProfileWithTies([], rcounts=[], candidates=candidates)
        
        print(f"\n=== PROCESSING {len(ballots)} BALLOTS ===")
        
        # Group identical rankings and their counts
        ranking_patterns = {}  # ranking_dict -> total_count
        
        for ballot_doc in ballots:
            count = ballot_doc.get("count", 1)
            rankings = ballot_doc["rankings"]
            
            # Convert rankings to use candidate names
            ranking_dict = {}
            for ranking in rankings:
                option_id = ranking["option_id"]
                rank = ranking["rank"]
                
                # Map option ID to candidate name
                if option_id in option_id_to_candidate:
                    candidate_name = option_id_to_candidate[option_id]
                    ranking_dict[candidate_name] = rank
            
            if not ranking_dict:
                continue
            
            # Group identical rankings
            ranking_tuple = tuple(sorted(ranking_dict.items()))
            ranking_patterns[ranking_tuple] = ranking_patterns.get(ranking_tuple, 0) + count
        
        # Build lists for ProfileWithTies
        rankings_list = []
        rcounts_list = []
        
        print(f"\n=== RANKING PATTERNS ===")
        for ranking_tuple, total_count in ranking_patterns.items():
            ranking_dict = dict(ranking_tuple)
            rankings_list.append(ranking_dict)
            rcounts_list.append(total_count)
            print(f"  {ranking_dict} : {total_count} votes")
        
        # Create ProfileWithTies
        profile = ProfileWithTies(rankings_list, rcounts=rcounts_list, candidates=candidates)
        
        print(f"\n=== PROFILE SUMMARY ===")
        print(f"Total voters: {profile.num_voters}")
        print(f"Candidates: {profile.candidates}")
        
        return profile
    
    async def get_pairwise_matrix(
        self,
        poll_id: str,
        candidates: List[str],
        option_id_to_candidate: Dict[str, str],
        include_test: bool = False
    ) -> Dict[str, Dict[str, int]]:
        """Calculate pairwise comparison matrix"""
        
        # Initialize matrix
        matrix = {
            c1: {c2: 0 for c2 in candidates if c2 != c1}
            for c1 in candidates
        }
        
        # Get all ballots
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        ballots = await self.ballots_collection.find(query).to_list(length=None)
        
        for ballot_doc in ballots:
            count = ballot_doc.get("count", 1)
            rankings = ballot_doc["rankings"]
            
            # Create preference mapping with candidate names
            prefs = {}
            for r in rankings:
                if r["option_id"] in option_id_to_candidate:
                    candidate = option_id_to_candidate[r["option_id"]]
                    prefs[candidate] = r["rank"]
            
            # Update pairwise comparisons
            for cand1 in prefs:
                for cand2 in prefs:
                    if cand1 != cand2 and prefs[cand1] < prefs[cand2]:
                        if cand1 in matrix and cand2 in matrix[cand1]:
                            matrix[cand1][cand2] += count
        
        return matrix
    
    async def get_ballot_summary(self, poll_id: str, include_test: bool = False) -> Dict:
        """Get summary statistics about ballots"""
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "total_votes": {"$sum": "$count"},
                "total_ballot_records": {"$sum": 1},
                "avg_votes_per_record": {"$avg": "$count"},
                "max_count": {"$max": "$count"},
                "individual_ballots": {
                    "$sum": {"$cond": [{"$eq": ["$count", 1]}, 1, 0]}
                },
                "aggregated_ballots": {
                    "$sum": {"$cond": [{"$gt": ["$count", 1]}, 1, 0]}
                }
            }}
        ]
        
        result = await self.ballots_collection.aggregate(pipeline).to_list(length=1)
        
        if result:
            return result[0]
        return {
            "total_votes": 0,
            "total_ballot_records": 0,
            "avg_votes_per_record": 0,
            "max_count": 0,
            "individual_ballots": 0,
            "aggregated_ballots": 0
        }