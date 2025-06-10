import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.ballot import (
    VoterType, RankingEntry, BallotSubmit, Ballot, VoteResults
)


class TestRankingEntry:
    """Test RankingEntry model validation"""
    
    def test_valid_ranking_entry(self):
        """Test creating a valid ranking entry"""
        ranking = RankingEntry(option_id="opt_1", rank=1)
        assert ranking.option_id == "opt_1"
        assert ranking.rank == 1
    
    def test_invalid_rank_zero(self):
        """Test that rank cannot be zero"""
        with pytest.raises(ValidationError) as exc_info:
            RankingEntry(option_id="opt_1", rank=0)
        assert "Rank must be positive" in str(exc_info.value)
    
    def test_invalid_rank_negative(self):
        """Test that rank cannot be negative"""
        with pytest.raises(ValidationError) as exc_info:
            RankingEntry(option_id="opt_1", rank=-1)
        assert "Rank must be positive" in str(exc_info.value)


class TestBallotSubmit:
    """Test BallotSubmit model validation"""
    
    def test_valid_ballot_submit(self):
        """Test creating a valid ballot submission"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[
                RankingEntry(option_id="opt_1", rank=1),
                RankingEntry(option_id="opt_2", rank=2)
            ]
        )
        assert ballot.poll_id == "poll_123"
        assert len(ballot.rankings) == 2
    
    def test_ballot_with_ties(self):
        """Test ballot with tied rankings (same rank for multiple options)"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[
                RankingEntry(option_id="opt_1", rank=1),
                RankingEntry(option_id="opt_2", rank=2),
                RankingEntry(option_id="opt_3", rank=2),  # Tie for 2nd
                RankingEntry(option_id="opt_4", rank=3)
            ]
        )
        assert len(ballot.rankings) == 4
        # Count how many have rank 2
        rank_2_count = sum(1 for r in ballot.rankings if r.rank == 2)
        assert rank_2_count == 2
    
    def test_ballot_with_gaps(self):
        """Test ballot with gaps in rankings (e.g., 1, 2, 4 - skipping 3)"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[
                RankingEntry(option_id="opt_1", rank=1),
                RankingEntry(option_id="opt_2", rank=2),
                RankingEntry(option_id="opt_3", rank=4),  # Gap - no rank 3
                RankingEntry(option_id="opt_4", rank=7)   # Bigger gap
            ]
        )
        assert len(ballot.rankings) == 4
        ranks = [r.rank for r in ballot.rankings]
        assert ranks == [1, 2, 4, 7]
    
    def test_empty_rankings_invalid(self):
        """Test that empty rankings list is invalid"""
        with pytest.raises(ValidationError) as exc_info:
            BallotSubmit(poll_id="poll_123", rankings=[])
        assert "At least one ranking required" in str(exc_info.value)
    
    def test_duplicate_option_invalid(self):
        """Test that ranking the same option twice is invalid"""
        with pytest.raises(ValidationError) as exc_info:
            BallotSubmit(
                poll_id="poll_123",
                rankings=[
                    RankingEntry(option_id="opt_1", rank=1),
                    RankingEntry(option_id="opt_1", rank=2),  # Same option again
                ]
            )
        assert "Cannot rank the same option multiple times" in str(exc_info.value)
    
    def test_ballot_with_test_mode(self):
        """Test ballot submission with test mode key"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            test_mode_key="secret-key-123"
        )
        assert ballot.test_mode_key == "secret-key-123"
    
    def test_ballot_with_browser_fingerprint(self):
        """Test ballot submission with browser fingerprint"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            browser_fingerprint="hash_abc123"
        )
        assert ballot.browser_fingerprint == "hash_abc123"
    
    def test_ballot_with_voter_token(self):
        """Test ballot submission with voter token for private polls"""
        ballot = BallotSubmit(
            poll_id="poll_123",
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            voter_token="token_xyz789"
        )
        assert ballot.voter_token == "token_xyz789"


class TestBallot:
    """Test Ballot model (stored ballot)"""
    
    def test_valid_ballot(self):
        """Test creating a valid ballot record"""
        ballot = Ballot(
            id="ballot_456",
            poll_id="poll_123",
            voter_type=VoterType.ANONYMOUS,
            rankings=[
                RankingEntry(option_id="opt_1", rank=1),
                RankingEntry(option_id="opt_2", rank=2)
            ],
            submitted_at=datetime.utcnow(),
            is_test=False
        )
        assert ballot.id == "ballot_456"
        assert ballot.voter_type == VoterType.ANONYMOUS
        assert not ballot.is_test
    
    def test_authenticated_ballot(self):
        """Test ballot from authenticated voter"""
        ballot = Ballot(
            id="ballot_789",
            poll_id="poll_123",
            voter_type=VoterType.AUTHENTICATED,
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            voter_email="voter@example.com",
            voter_token="token_abc",
            submitted_at=datetime.utcnow(),
            is_test=False
        )
        assert ballot.voter_type == VoterType.AUTHENTICATED
        assert ballot.voter_email == "voter@example.com"
        assert ballot.voter_token == "token_abc"
    
    def test_test_ballot(self):
        """Test ballot marked as test"""
        ballot = Ballot(
            id="ballot_test",
            poll_id="poll_123",
            voter_type=VoterType.TEST,
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            submitted_at=datetime.utcnow(),
            is_test=True
        )
        assert ballot.voter_type == VoterType.TEST
        assert ballot.is_test
    
    def test_ballot_datetime_serialization(self):
        """Test that datetime is properly serialized"""
        now = datetime.utcnow()
        ballot = Ballot(
            id="ballot_123",
            poll_id="poll_123",
            voter_type=VoterType.ANONYMOUS,
            rankings=[RankingEntry(option_id="opt_1", rank=1)],
            submitted_at=now,
            is_test=False
        )
        # Convert to dict to see serialization
        ballot_dict = ballot.model_dump()
        assert isinstance(ballot_dict["submitted_at"], str)
        assert ballot_dict["submitted_at"] == now.isoformat()


class TestVoteResults:
    """Test VoteResults model"""
    
    def test_valid_vote_results(self):
        """Test creating valid vote results"""
        results = VoteResults(
            poll_id="poll_123",
            total_ballots=100,
            total_test_ballots=5,
            first_place_counts={
                "opt_1": 45,
                "opt_2": 30,
                "opt_3": 25
            },
            ranking_matrix={
                "opt_1": {1: 45, 2: 30, 3: 25},
                "opt_2": {1: 30, 2: 40, 3: 30},
                "opt_3": {1: 25, 2: 30, 3: 45}
            },
            pairwise_matrix={
                "opt_1": {"opt_2": 60, "opt_3": 70},
                "opt_2": {"opt_1": 40, "opt_3": 55},
                "opt_3": {"opt_1": 30, "opt_2": 45}
            },
            last_updated=datetime.utcnow()
        )
        assert results.total_ballots == 100
        assert results.total_test_ballots == 5
        assert results.first_place_counts["opt_1"] == 45
        assert results.ranking_matrix["opt_1"][1] == 45
        assert results.pairwise_matrix["opt_1"]["opt_2"] == 60
