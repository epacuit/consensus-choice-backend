from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator
from enum import Enum

class VoterType(str, Enum):
    AUTHENTICATED = "authenticated"  # Private poll with token
    ANONYMOUS = "anonymous"         # Public poll
    TEST = "test"                  # Test votes for demo

class RankingEntry(BaseModel):
    """Represents a single ranking entry in a ballot"""
    option_id: str
    rank: int  # 1 = first choice, 2 = second, etc.
    
    @field_validator('rank')
    @classmethod
    def validate_rank(cls, v: int) -> int:
        if v < 1:
            raise ValueError('Rank must be positive')
        return v

class BallotSubmit(BaseModel):
    """Request model for submitting a ballot"""
    poll_id: str
    rankings: List[RankingEntry]
    
    # For private polls
    voter_token: Optional[str] = None
    
    # For public polls (browser fingerprinting)
    browser_fingerprint: Optional[str] = None
    
    # Hidden test mode
    test_mode_key: Optional[str] = None
    
    model_config = ConfigDict()
    
    @field_validator('rankings')
    @classmethod
    def validate_rankings(cls, v: List[RankingEntry]) -> List[RankingEntry]:
        if not v:
            raise ValueError('At least one ranking required')
        
        # Check for duplicate option_ids
        option_ids = [r.option_id for r in v]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError('Cannot rank the same option multiple times')
            
        return v

class Ballot(BaseModel):
    """Stored ballot record"""
    id: str
    poll_id: str
    voter_type: VoterType
    
    # The actual rankings
    rankings: List[RankingEntry]
    
    # Voter identification
    voter_email: Optional[str] = None  # For authenticated voters
    voter_token: Optional[str] = None  # For authenticated voters
    browser_fingerprint: Optional[str] = None  # For anonymous voters
    
    # Metadata
    submitted_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # For test votes
    is_test: bool = False
    
    model_config = ConfigDict()
    
    @field_serializer('submitted_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None

class VoteResults(BaseModel):
    """Live voting results"""
    poll_id: str
    total_ballots: int
    total_test_ballots: int
    
    # Rankings by option_id
    first_place_counts: Dict[str, int]
    
    # Full ranking matrix: option_id -> rank -> count
    ranking_matrix: Dict[str, Dict[int, int]]
    
    # Pairwise preferences for Condorcet methods
    pairwise_matrix: Dict[str, Dict[str, int]]
    
    last_updated: datetime
    
    model_config = ConfigDict()
    
    @field_serializer('last_updated')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None