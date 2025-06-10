from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from pydantic import BaseModel, Field, ConfigDict, field_serializer
from enum import Enum


class VotingMethod(str, Enum):
    """Supported voting methods"""
    MINIMAX = "minimax"
    COPELAND_GLOBAL_MINIMAX = "copeland_global_minimax"
    COPELAND = "copeland"


class WinnerType(str, Enum):
    """Type of winner determination"""
    CONDORCET = "condorcet"
    WEAK_CONDORCET = "weak_condorcet"
    COPELAND = "copeland"  # Best win-loss record
    MINIMAX = "minimax"  # Smallest worst loss
    TIE_WEAK_CONDORCET = "tie_weak_condorcet"  # Multiple weak Condorcet winners
    TIE_COPELAND = "tie_copeland"  # Multiple candidates with best win-loss record
    TIE_MINIMAX = "tie_minimax"  # Multiple candidates with same minimax score
    NONE = "none"


class BallotType(BaseModel):
    """Represents a unique ballot pattern and how many voters submitted it"""
    ranking: List[List[str]]  # List of lists to represent ties, e.g. [["A"], ["B", "C"], ["D"]]
    count: int
    percentage: float
    
    @property
    def ranking_string(self) -> str:
        """Convert ranking to readable string format"""
        parts = []
        for tier in self.ranking:
            if len(tier) == 1:
                parts.append(tier[0])
            else:
                parts.append(" ~ ".join(tier))
        return " > ".join(parts) if parts else "Empty ballot"


class PairwiseComparison(BaseModel):
    """Results of pairwise comparison between two candidates"""
    candidate_a: str
    candidate_b: str
    a_beats_b: int  # Number of ballots where A is ranked above B
    b_beats_a: int  # Number of ballots where B is ranked above A
    ties: int       # Number of ballots where A and B are tied
    margin: int     # a_beats_b - b_beats_a
    
    @property
    def winner(self) -> Optional[str]:
        """Return the pairwise winner, or None if tied"""
        if self.margin > 0:
            return self.candidate_a
        elif self.margin < 0:
            return self.candidate_b
        return None


class HeadToHeadMatrix(BaseModel):
    """Matrix showing rankings where candidate A beats candidate B"""
    candidate_a: str
    candidate_b: str
    ballot_types: List[BallotType]  # All ballot types where A beats B
    total_count: int
    
    model_config = ConfigDict()


class CandidateRecord(BaseModel):
    """Win-loss-tie record for a candidate"""
    candidate: str
    wins: int
    losses: int
    ties: int
    copeland_score: float  # From pref_voting
    minimax_score: Optional[float] = None  # From pref_voting (-1 * max pairwise loss)
    opponents: List[Dict[str, Any]]  # List of {opponent, result, margin}
    worst_loss_margin: Optional[int] = None  # Absolute value of worst loss for display
    
    @property
    def net_wins(self) -> int:
        """Net wins (wins - losses) for ranking"""
        return self.wins - self.losses


class VotingMethodResult(BaseModel):
    """Result from a specific voting method"""
    method: VotingMethod
    winners: List[str]  # Can be multiple in case of ties
    is_tie: bool = False
    scores: Optional[Dict[str, float]] = None  # Method-specific scores
    
    model_config = ConfigDict()


class DetailedResults(BaseModel):
    """Comprehensive results analysis for a poll"""
    poll_id: str
    calculated_at: datetime
    
    # Basic statistics
    total_voters: int
    total_ballots: int  # Should equal total_voters unless test ballots included
    num_candidates: int
    candidates: List[str]  # Candidate names/options
    
    # Ballot analysis
    ballot_types: List[BallotType]
    num_bullet_votes: int  # Ballots with only one candidate ranked
    num_complete_rankings: int  # Ballots ranking all candidates
    num_linear_orders: int  # Ballots with no ties
    
    # Pairwise comparisons
    pairwise_matrix: Dict[str, Dict[str, int]]  # margin matrix
    pairwise_support_matrix: Dict[str, Dict[str, Dict[str, int]]]  # Full support data
    pairwise_comparisons: List[PairwiseComparison]
    
    # Winner determination
    condorcet_winner: Optional[str]
    weak_condorcet_winners: List[str] = []  # Can be multiple
    winner_type: WinnerType
    determined_winner: Optional[str]  # Single winner or None if tie
    tied_winners: List[str] = []  # Multiple winners in case of tie
    is_tie: bool = False
    
    # Win-loss records (from Copeland scores)
    candidate_records: List[CandidateRecord]
    
    # Voting method results
    voting_results: List[VotingMethodResult]
    
    # Head-to-head analysis for all pairs
    head_to_head_matrices: List[HeadToHeadMatrix]
    
    model_config = ConfigDict()
    
    @field_serializer('calculated_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None


class ResultsSummary(BaseModel):
    """Quick summary of results for display"""
    poll_id: str
    winner_type: WinnerType
    determined_winner: Optional[str]
    tied_winners: List[str] = []
    is_tie: bool = False
    condorcet_winner: Optional[str]
    weak_condorcet_winners: List[str] = []
    minimax_winners: List[str]
    copeland_winners: List[str]
    most_common_ranking: BallotType
    
    model_config = ConfigDict()