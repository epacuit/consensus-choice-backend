from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set, Any
from collections import defaultdict, Counter
from pref_voting.profiles_with_ties import ProfileWithTies
from pref_voting.voting_methods import minimax, copeland_global_minimax, copeland
from pref_voting.margin_based_methods import minimax_scores

from ..database import db
from ..models.results import (
    DetailedResults, VotingMethod, VotingMethodResult,
    BallotType, PairwiseComparison, HeadToHeadMatrix,
    CandidateRecord, WinnerType
)
from .poll_service import PollService


class ResultsService:
    def __init__(self):
        self.poll_service = PollService()
    
    async def calculate_detailed_results(
        self, 
        poll_id: str, 
        include_test: bool = False
    ) -> DetailedResults:
        """Calculate comprehensive voting results for a poll"""
        
        # Get poll and ballots
        poll = await self.poll_service.get_poll(poll_id)
        if not poll:
            raise ValueError(f"Poll {poll_id} not found")
        
        # Get all ballots
        query = {"poll_id": poll_id}
        if not include_test:
            query["is_test"] = {"$ne": True}
        
        ballot_docs = await db.database.ballots.find(query).to_list(length=None)
        
        if not ballot_docs:
            # Return empty results
            candidate_names = {opt.id: opt.name for opt in poll.options}
            candidate_names_list = [opt.name for opt in poll.options]
            
            # Create empty candidate records
            empty_records = []
            for opt in poll.options:
                empty_records.append(CandidateRecord(
                    candidate=opt.name,
                    wins=0,
                    losses=0,
                    ties=0,
                    copeland_score=0.0,
                    minimax_score=0.0,
                    opponents=[],
                    worst_loss_margin=0
                ))
            
            return DetailedResults(
                poll_id=poll_id,
                calculated_at=datetime.utcnow(),
                total_voters=0,
                total_ballots=0,
                num_candidates=len(poll.options),
                candidates=candidate_names_list,
                ballot_types=[],
                num_bullet_votes=0,
                num_complete_rankings=0,
                num_linear_orders=0,
                pairwise_matrix={name: {other: 0 for other in candidate_names_list} for name in candidate_names_list},
                pairwise_support_matrix={name: {other: {"support": 0, "opposed": 0, "margin": 0} for other in candidate_names_list} for name in candidate_names_list},
                pairwise_comparisons=[],
                condorcet_winner=None,
                weak_condorcet_winners=[],
                winner_type=WinnerType.NONE,
                determined_winner=None,
                tied_winners=[],
                is_tie=False,
                candidate_records=empty_records,
                voting_results=[
                    VotingMethodResult(method=VotingMethod.MINIMAX, winners=[], is_tie=False),
                    VotingMethodResult(method=VotingMethod.COPELAND, winners=[], is_tie=False),
                    VotingMethodResult(method=VotingMethod.COPELAND_GLOBAL_MINIMAX, winners=[], is_tie=False)
                ],
                head_to_head_matrices=[]
            )
        
        # Convert to ProfileWithTies
        profile = self._create_profile_from_ballots(poll, ballot_docs)
        profile.use_extended_strict_preference()
        
        # Get candidate names
        candidates = list(profile.candidates)
        candidate_names = {opt.id: opt.name for opt in poll.options}
        
        # Calculate Condorcet winners
        condorcet_winner = self._get_condorcet_winner(profile, candidate_names)
        weak_condorcet_winners = self._get_weak_condorcet_winners(profile, candidate_names) if not condorcet_winner else []
        
        # Calculate Copeland scores and records
        candidate_records = self._calculate_candidate_records(profile, candidate_names)
        
        # Determine winner type and actual winner(s)
        winner_type, determined_winner, tied_winners, is_tie = self._determine_winner(
            condorcet_winner, 
            weak_condorcet_winners, 
            candidate_records,
            profile,
            candidate_names
        )
        
        # Calculate all results
        results = DetailedResults(
            poll_id=poll_id,
            calculated_at=datetime.utcnow(),
            total_voters=profile.num_voters,
            total_ballots=len(ballot_docs),
            num_candidates=len(candidates),
            candidates=[candidate_names.get(self._candidate_to_option_id.get(c, c), c) for c in candidates],
            ballot_types=self._get_ballot_types(profile, candidate_names),
            num_bullet_votes=self._count_bullet_votes(profile),
            num_complete_rankings=self._count_complete_rankings(profile),
            num_linear_orders=self._count_linear_orders(profile),
            pairwise_matrix=self._get_pairwise_matrix(profile, candidate_names),
            pairwise_support_matrix=self._get_pairwise_support_matrix(profile, candidate_names),
            pairwise_comparisons=self._get_pairwise_comparisons(profile, candidate_names),
            condorcet_winner=condorcet_winner,
            weak_condorcet_winners=weak_condorcet_winners,
            winner_type=winner_type,
            determined_winner=determined_winner,
            tied_winners=tied_winners,
            is_tie=is_tie,
            candidate_records=candidate_records,
            voting_results=self._calculate_voting_results(profile, candidate_names),
            head_to_head_matrices=self._calculate_head_to_head_matrices(profile, candidate_names)
        )
        
        return results
    
    def _create_profile_from_ballots(
        self, 
        poll, 
        ballot_docs: List[dict]
    ) -> ProfileWithTies:
        """Convert poll and ballots to ProfileWithTies format"""
        
        # Map option IDs to simple identifiers for pref_voting
        option_id_to_candidate = {opt.id: f"C{i}" for i, opt in enumerate(poll.options)}
        
        # Group identical ballots
        ballot_counter = Counter()
        
        for ballot_doc in ballot_docs:
            # Convert rankings to preference format with ties
            rankings_by_rank = defaultdict(list)
            
            for ranking in ballot_doc["rankings"]:
                option_id = ranking["option_id"]
                rank = ranking["rank"]
                candidate = option_id_to_candidate[option_id]
                rankings_by_rank[rank].append(candidate)
            
            # Create ranking tuple of tuples (for ties)
            sorted_ranks = sorted(rankings_by_rank.keys())
            ranking_tuple = tuple(
                tuple(sorted(rankings_by_rank[rank])) 
                for rank in sorted_ranks
            )
            
            ballot_counter[ranking_tuple] += 1
        
        # Create ProfileWithTies with unique rankings and their counts
        rankings = []
        counts = []
        
        for ranking_tuple, count in ballot_counter.items():
            # Convert tuple format to dictionary format for ProfileWithTies
            ranking_dict = {}
            for rank_idx, candidates_at_rank in enumerate(ranking_tuple):
                for candidate in candidates_at_rank:
                    ranking_dict[candidate] = rank_idx + 1
            rankings.append(ranking_dict)
            counts.append(count)
        
        candidates = list(option_id_to_candidate.values())
        
        # Store mapping for later use
        self._candidate_to_option_id = {v: k for k, v in option_id_to_candidate.items()}
        
        return ProfileWithTies(rankings, rcounts=counts, candidates=candidates)
    
    def _calculate_candidate_records(
        self,
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[CandidateRecord]:
        """Calculate win-loss-tie records using Copeland scores"""
        
        # Get Copeland scores from pref_voting
        copeland_scores_dict = profile.copeland_scores()
        
        # Get minimax scores from pref_voting
        minimax_scores_dict = minimax_scores(profile)
        
        records = []
        
        for candidate in profile.candidates:
            wins = 0
            losses = 0
            ties = 0
            opponents = []
            worst_loss_margin = None
            
            # Compare with all other candidates
            for other in profile.candidates:
                if candidate == other:
                    continue
                
                margin = profile.margin(candidate, other)
                
                if margin > 0:
                    wins += 1
                    opponents.append({
                        "opponent": candidate_names.get(self._candidate_to_option_id.get(other, other), other),
                        "result": "win",
                        "margin": margin
                    })
                elif margin < 0:
                    losses += 1
                    opponents.append({
                        "opponent": candidate_names.get(self._candidate_to_option_id.get(other, other), other),
                        "result": "loss",
                        "margin": margin
                    })
                    # Track worst loss for display purposes
                    if worst_loss_margin is None or abs(margin) > worst_loss_margin:
                        worst_loss_margin = abs(margin)
                else:
                    ties += 1
                    opponents.append({
                        "opponent": candidate_names.get(self._candidate_to_option_id.get(other, other), other),
                        "result": "tie",
                        "margin": 0
                    })
            
            option_id = self._candidate_to_option_id.get(candidate, candidate)
            records.append(CandidateRecord(
                candidate=candidate_names.get(option_id, candidate),
                wins=wins,
                losses=losses,
                ties=ties,
                copeland_score=copeland_scores_dict[candidate],
                minimax_score=minimax_scores_dict[candidate],
                opponents=opponents,
                worst_loss_margin=worst_loss_margin if worst_loss_margin is not None else 0
            ))
        
        # Sort by Copeland score (which is essentially wins - losses with tie handling)
        records.sort(key=lambda r: r.copeland_score, reverse=True)
        
        return records
    
    def _determine_winner(
        self,
        condorcet_winner: Optional[str],
        weak_condorcet_winners: List[str],
        candidate_records: List[CandidateRecord],
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> Tuple[WinnerType, Optional[str], List[str], bool]:
        """Determine the type of winner and who it is
        
        Returns: (winner_type, single_winner, tied_winners, is_tie)
        """
        
        # 1. Check for Condorcet winner
        if condorcet_winner:
            return WinnerType.CONDORCET, condorcet_winner, [], False
        
        # 2. Check for unique weak Condorcet winner
        if len(weak_condorcet_winners) == 1:
            return WinnerType.WEAK_CONDORCET, weak_condorcet_winners[0], [], False
        
        # If we have multiple weak Condorcet winners or none, continue to Copeland
        
        # 3. Check Copeland scores (best win-loss record)
        if candidate_records:
            best_score = candidate_records[0].copeland_score
            candidates_with_best_score = [r for r in candidate_records if r.copeland_score == best_score]
            
            # If unique Copeland winner
            if len(candidates_with_best_score) == 1:
                return WinnerType.COPELAND, candidates_with_best_score[0].candidate, [], False
            
            # 4. Multiple candidates with same Copeland score - check minimax
            # Higher minimax score is better (less negative = smaller worst loss)
            candidates_with_scores = [r for r in candidates_with_best_score if r.minimax_score is not None]
            
            if candidates_with_scores:
                best_minimax_score = max(r.minimax_score for r in candidates_with_scores)
                minimax_winners = [r for r in candidates_with_scores if r.minimax_score == best_minimax_score]
                
                # If unique Minimax winner
                if len(minimax_winners) == 1:
                    return WinnerType.MINIMAX, minimax_winners[0].candidate, [], False
                else:
                    # 5. Multiple candidates with same minimax score - it's a tie
                    tied_candidates = [r.candidate for r in minimax_winners]
                    return WinnerType.TIE_MINIMAX, None, tied_candidates, True
            else:
                # No minimax scores available, all candidates with best Copeland score are tied
                tied_candidates = [r.candidate for r in candidates_with_best_score]
                if len(tied_candidates) > 1:
                    return WinnerType.TIE_COPELAND, None, tied_candidates, True
                else:
                    return WinnerType.COPELAND, tied_candidates[0], [], False
        
        return WinnerType.NONE, None, [], False
    
    def _get_ballot_types(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[BallotType]:
        """Extract and count unique ballot types"""
        
        ballot_types = []
        total_voters = profile.num_voters
        
        # Use rankings_counts property
        rankings, counts = profile.rankings_counts
        
        # Access rankings and counts together
        for ranking, count in zip(rankings, counts):
            ranking_list = ranking.to_indiff_list()
            
            # Convert candidate IDs in ranking to names
            named_ranking_list = []
            for tier in ranking_list:
                named_tier = []
                for candidate in tier:
                    option_id = self._candidate_to_option_id.get(candidate, candidate)
                    name = candidate_names.get(option_id, candidate)
                    named_tier.append(name)
                named_ranking_list.append(named_tier)
            
            ballot_types.append(BallotType(
                ranking=named_ranking_list,
                count=count,
                percentage=(count / total_voters) * 100
            ))
        
        # Sort by count descending
        ballot_types.sort(key=lambda x: x.count, reverse=True)
        return ballot_types
    
    def _count_bullet_votes(self, profile: ProfileWithTies) -> int:
        """Count ballots that rank only one candidate"""
        bullet_count = 0
        rankings, counts = profile.rankings_counts
        for ranking, count in zip(rankings, counts):
            if ranking.is_bullet_vote():
                bullet_count += count
        return bullet_count
    
    def _count_complete_rankings(self, profile: ProfileWithTies) -> int:
        """Count ballots that rank all candidates"""
        complete_count = 0
        rankings, counts = profile.rankings_counts
        for ranking, count in zip(rankings, counts):
            if len(ranking.cands) == len(profile.candidates):
                complete_count += count
        return complete_count
    
    def _count_linear_orders(self, profile: ProfileWithTies) -> int:
        """Count ballots with no ties (strict preferences)"""
        linear_count = 0
        rankings, counts = profile.rankings_counts
        for ranking, count in zip(rankings, counts):
            if ranking.is_linear(len(profile.candidates)) or ranking.is_truncated_linear(len(profile.candidates)):
                linear_count += count
        return linear_count
    
    def _get_pairwise_matrix(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> Dict[str, Dict[str, int]]:
        """Get the margin matrix"""
        margin_matrix = {}
        
        for c1 in profile.candidates:
            option_id1 = self._candidate_to_option_id.get(c1, c1)
            name1 = candidate_names.get(option_id1, c1)
            margin_matrix[name1] = {}
            
            for c2 in profile.candidates:
                option_id2 = self._candidate_to_option_id.get(c2, c2)
                name2 = candidate_names.get(option_id2, c2)
                
                if c1 != c2:
                    margin_matrix[name1][name2] = profile.margin(c1, c2)
                else:
                    margin_matrix[name1][name2] = 0
        
        return margin_matrix
    
    def _get_pairwise_support_matrix(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> Dict[str, Dict[str, Dict[str, int]]]:
        """Get the full support matrix with support, opposed, and margin"""
        support_matrix = {}
        
        for c1 in profile.candidates:
            option_id1 = self._candidate_to_option_id.get(c1, c1)
            name1 = candidate_names.get(option_id1, c1)
            support_matrix[name1] = {}
            
            for c2 in profile.candidates:
                option_id2 = self._candidate_to_option_id.get(c2, c2)
                name2 = candidate_names.get(option_id2, c2)
                
                if c1 != c2:
                    support = profile.support(c1, c2)
                    opposed = profile.support(c2, c1)
                    margin = profile.margin(c1, c2)
                    
                    support_matrix[name1][name2] = {
                        "support": support,
                        "opposed": opposed,
                        "margin": margin
                    }
                else:
                    support_matrix[name1][name2] = {
                        "support": 0,
                        "opposed": 0,
                        "margin": 0
                    }
        
        return support_matrix
    
    def _get_pairwise_comparisons(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[PairwiseComparison]:
        """Get all pairwise comparisons"""
        comparisons = []
        
        candidates = list(profile.candidates)
        for i, c1 in enumerate(candidates):
            for c2 in candidates[i+1:]:
                a_beats_b = profile.support(c1, c2)
                b_beats_a = profile.support(c2, c1)
                margin = profile.margin(c1, c2)
                
                option_id1 = self._candidate_to_option_id.get(c1, c1)
                option_id2 = self._candidate_to_option_id.get(c2, c2)
                
                comparisons.append(PairwiseComparison(
                    candidate_a=candidate_names.get(option_id1, c1),
                    candidate_b=candidate_names.get(option_id2, c2),
                    a_beats_b=a_beats_b,
                    b_beats_a=b_beats_a,
                    ties=profile.num_voters - a_beats_b - b_beats_a,
                    margin=margin
                ))
        
        return comparisons
    
    def _get_condorcet_winner(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> Optional[str]:
        """Find the Condorcet winner if one exists"""
        winner = profile.condorcet_winner()
        if winner is not None:
            option_id = self._candidate_to_option_id.get(winner, winner)
            return candidate_names.get(option_id, winner)
        return None
    
    def _get_weak_condorcet_winners(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[str]:
        """Find all weak Condorcet winners if they exist"""
        winners = profile.weak_condorcet_winner()  # Returns a list
        if winners:  # If list is not empty
            named_winners = []
            for winner in winners:
                option_id = self._candidate_to_option_id.get(winner, winner)
                named_winners.append(candidate_names.get(option_id, winner))
            return named_winners
        return []
    
    def _calculate_voting_results(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[VotingMethodResult]:
        """Calculate results for various voting methods"""
        results = []
        
        # Minimax
        minimax_winners = minimax(profile)
        minimax_scores_dict = minimax_scores(profile)
        
        if isinstance(minimax_winners, list):
            winners = [candidate_names.get(self._candidate_to_option_id.get(w, w), w) 
                      for w in minimax_winners]
            is_tie = len(winners) > 1
        else:
            option_id = self._candidate_to_option_id.get(minimax_winners, minimax_winners)
            winners = [candidate_names.get(option_id, minimax_winners)]
            is_tie = False
        
        # Convert minimax scores to use candidate names
        scores_dict = {}
        for candidate, score in minimax_scores_dict.items():
            option_id = self._candidate_to_option_id.get(candidate, candidate)
            name = candidate_names.get(option_id, candidate)
            scores_dict[name] = score
        
        results.append(VotingMethodResult(
            method=VotingMethod.MINIMAX,
            winners=winners,
            is_tie=is_tie,
            scores=scores_dict
        ))
        
        # Copeland
        copeland_winners = copeland(profile)
        if isinstance(copeland_winners, list):
            winners = [candidate_names.get(self._candidate_to_option_id.get(w, w), w) 
                      for w in copeland_winners]
            is_tie = len(winners) > 1
        else:
            option_id = self._candidate_to_option_id.get(copeland_winners, copeland_winners)
            winners = [candidate_names.get(option_id, copeland_winners)]
            is_tie = False
        
        # Get Copeland scores
        copeland_scores = profile.copeland_scores()
        scores_dict = {}
        for candidate, score in copeland_scores.items():
            option_id = self._candidate_to_option_id.get(candidate, candidate)
            name = candidate_names.get(option_id, candidate)
            scores_dict[name] = score
        
        results.append(VotingMethodResult(
            method=VotingMethod.COPELAND,
            winners=winners,
            is_tie=is_tie,
            scores=scores_dict
        ))
        
        # Copeland Global Minimax
        copeland_global_minimax_winners = copeland_global_minimax(profile)
        if isinstance(copeland_global_minimax_winners, list):
            winners = [candidate_names.get(self._candidate_to_option_id.get(w, w), w) 
                      for w in copeland_global_minimax_winners]
            is_tie = len(winners) > 1
        else:
            option_id = self._candidate_to_option_id.get(copeland_global_minimax_winners, copeland_global_minimax_winners)
            winners = [candidate_names.get(option_id, copeland_global_minimax_winners)]
            is_tie = False
        
        results.append(VotingMethodResult(
            method=VotingMethod.COPELAND_GLOBAL_MINIMAX,
            winners=winners,
            is_tie=is_tie
        ))
        
        return results
    
    def _calculate_head_to_head_matrices(
        self, 
        profile: ProfileWithTies,
        candidate_names: Dict[str, str]
    ) -> List[HeadToHeadMatrix]:
        """Calculate which ballot types have A ranked above B for all pairs"""
        matrices = []
        
        candidates = list(profile.candidates)
        rankings, counts = profile.rankings_counts
        
        for c1 in candidates:
            for c2 in candidates:
                if c1 == c2:
                    continue
                
                # Find all ballot types where c1 beats c2
                ballot_types = []
                total_count = 0
                
                for ranking, count in zip(rankings, counts):
                    # Use pref_voting's extended_strict_pref to check if c1 beats c2
                    if ranking.extended_strict_pref(c1, c2):
                        # Convert ranking to readable format
                        ranking_list = ranking.to_indiff_list()
                        
                        # Convert candidate IDs to names
                        named_ranking_list = []
                        for tier in ranking_list:
                            tier_names = []
                            for candidate in tier:
                                option_id = self._candidate_to_option_id.get(candidate, candidate)
                                name = candidate_names.get(option_id, candidate)
                                tier_names.append(name)
                            named_ranking_list.append(tier_names)
                        
                        ballot_types.append(BallotType(
                            ranking=named_ranking_list,
                            count=count,
                            percentage=(count / profile.num_voters) * 100
                        ))
                        total_count += count
                
                # Verify total_count matches profile.support
                assert total_count == profile.support(c1, c2), f"Mismatch in support calculation"
                
                if ballot_types:  # Only add if there are ballot types where c1 beats c2
                    option_id1 = self._candidate_to_option_id.get(c1, c1)
                    option_id2 = self._candidate_to_option_id.get(c2, c2)
                    
                    matrices.append(HeadToHeadMatrix(
                        candidate_a=candidate_names.get(option_id1, c1),
                        candidate_b=candidate_names.get(option_id2, c2),
                        ballot_types=ballot_types,
                        total_count=total_count
                    ))
        
        return matrices