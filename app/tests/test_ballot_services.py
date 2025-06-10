import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from app.services.ballot_service import BallotService
from app.models.ballot import (
    BallotSubmit, VoterType, RankingEntry, VoteResults
)
from app.models.poll import Poll, PollOption, PollSettings


@pytest.fixture
def ballot_service():
    """Create a ballot service instance with mocked dependencies"""
    service = BallotService()
    # Mock the poll service
    service.poll_service = AsyncMock()
    return service


@pytest.fixture
def sample_poll():
    """Create a sample poll for testing"""
    return Poll(
        id="507f1f77bcf86cd799439011",
        title="Best Programming Language",
        description="Vote for your favorite",
        options=[
            PollOption(id="opt_1", name="Python"),
            PollOption(id="opt_2", name="JavaScript"),
            PollOption(id="opt_3", name="Go"),
            PollOption(id="opt_4", name="Rust")
        ],
        is_private=False,
        settings=PollSettings(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        is_active=True,
        has_closed=False
    )


@pytest.fixture
def sample_ballot_submit():
    """Create a sample ballot submission"""
    return BallotSubmit(
        poll_id="507f1f77bcf86cd799439011",
        rankings=[
            RankingEntry(option_id="opt_1", rank=1),
            RankingEntry(option_id="opt_2", rank=2),
            RankingEntry(option_id="opt_3", rank=2),  # Tie for 2nd
            RankingEntry(option_id="opt_4", rank=4)   # Gap - no rank 3
        ],
        browser_fingerprint="test_fingerprint_123"
    )


class TestBallotService:
    """Test the ballot service functionality"""
    
    @pytest.mark.asyncio
    @patch('app.services.ballot_service.db')
    async def test_submit_ballot_public_poll(self, mock_db, ballot_service, sample_poll, sample_ballot_submit):
        """Test submitting a ballot to a public poll"""
        # Setup mocks for the database property chain
        mock_ballots = AsyncMock()
        mock_polls = AsyncMock()
        mock_database = MagicMock()
        mock_database.ballots = mock_ballots
        mock_database.polls = mock_polls
        mock_db.database = mock_database
        
        ballot_service.poll_service.get_poll.return_value = sample_poll
        ballot_service._check_duplicate_public_vote = AsyncMock(return_value=False)
        mock_ballots.insert_one.return_value = MagicMock(
            inserted_id=ObjectId("507f1f77bcf86cd799439012")
        )
        mock_ballots.find_one.return_value = {
            "_id": ObjectId("507f1f77bcf86cd799439012"),
            "poll_id": sample_ballot_submit.poll_id,
            "voter_type": VoterType.ANONYMOUS.value,
            "rankings": [r.model_dump() for r in sample_ballot_submit.rankings],
            "browser_fingerprint": sample_ballot_submit.browser_fingerprint,
            "submitted_at": datetime.utcnow(),
            "is_test": False
        }
        ballot_service._increment_vote_count = AsyncMock()
        
        # Submit ballot
        result = await ballot_service.submit_ballot(sample_ballot_submit)
        
        # Verify
        assert result.id == "507f1f77bcf86cd799439012"
        assert result.voter_type == VoterType.ANONYMOUS
        assert len(result.rankings) == 4
        assert not result.is_test
        
        # Verify duplicate check was called
        ballot_service._check_duplicate_public_vote.assert_called_once_with(
            sample_ballot_submit.poll_id,
            sample_ballot_submit.browser_fingerprint
        )
        
        # Verify vote count was incremented
        ballot_service._increment_vote_count.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_submit_ballot_closed_poll(self, ballot_service, sample_poll, sample_ballot_submit):
        """Test that submitting to a closed poll raises an error"""
        # Setup closed poll
        sample_poll.has_closed = True
        ballot_service.poll_service.get_poll.return_value = sample_poll
        
        # Attempt to submit
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(sample_ballot_submit)
        
        assert "Poll has closed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_submit_ballot_invalid_option(self, ballot_service, sample_poll, sample_ballot_submit):
        """Test that submitting with invalid option ID raises an error"""
        # Add invalid option to rankings
        sample_ballot_submit.rankings.append(
            RankingEntry(option_id="opt_invalid", rank=5)
        )
        ballot_service.poll_service.get_poll.return_value = sample_poll
        
        # Attempt to submit
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(sample_ballot_submit)
        
        assert "Invalid option ID: opt_invalid" in str(exc_info.value)
    
    @pytest.mark.asyncio
    @patch('app.services.ballot_service.db')
    async def test_submit_ballot_duplicate_public_vote(self, mock_db, ballot_service, sample_poll, sample_ballot_submit):
        """Test that duplicate votes in public polls are prevented"""
        # Setup mocks for the database property chain
        mock_ballots = AsyncMock()
        mock_database = MagicMock()
        mock_database.ballots = mock_ballots
        mock_db.database = mock_database
        
        ballot_service.poll_service.get_poll.return_value = sample_poll
        
        # Mock duplicate check to return True
        mock_ballots.find_one.return_value = {"existing": "ballot"}  # Indicates duplicate
        
        # Attempt to submit duplicate
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(sample_ballot_submit)
        
        assert "already been submitted from this browser" in str(exc_info.value)
    
    @pytest.mark.asyncio
    @patch('app.services.ballot_service.db')
    async def test_submit_ballot_test_mode(self, mock_db, ballot_service, sample_poll, sample_ballot_submit):
        """Test submitting ballot in test mode"""
        # Setup mocks for the database property chain
        mock_ballots = AsyncMock()
        mock_polls = AsyncMock()
        mock_database = MagicMock()
        mock_database.ballots = mock_ballots
        mock_database.polls = mock_polls
        mock_db.database = mock_database
        
        # Add test mode key
        sample_ballot_submit.test_mode_key = ballot_service.TEST_MODE_KEY
        
        # Setup mocks
        ballot_service.poll_service.get_poll.return_value = sample_poll
        mock_ballots.insert_one.return_value = MagicMock(
            inserted_id=ObjectId("507f1f77bcf86cd799439013")
        )
        mock_ballots.find_one.return_value = {
            "_id": ObjectId("507f1f77bcf86cd799439013"),
            "poll_id": sample_ballot_submit.poll_id,
            "voter_type": VoterType.TEST.value,
            "rankings": [r.model_dump() for r in sample_ballot_submit.rankings],
            "submitted_at": datetime.utcnow(),
            "is_test": True
        }
        
        # Submit ballot
        result = await ballot_service.submit_ballot(sample_ballot_submit)
        
        # Verify
        assert result.voter_type == VoterType.TEST
        assert result.is_test
    
    @pytest.mark.asyncio
    @patch('app.services.ballot_service.db')
    async def test_get_live_results(self, mock_db, ballot_service, sample_poll):
        """Test calculating live results"""
        # Setup mocks for the database property chain
        mock_ballots = MagicMock()
        mock_database = MagicMock()
        mock_database.ballots = mock_ballots
        mock_db.database = mock_database
        
        # Setup poll
        ballot_service.poll_service.get_poll.return_value = sample_poll
        
        # Mock ballot data
        test_ballots = [
            {
                "poll_id": sample_poll.id,
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2}
                ],
                "is_test": False
            },
            {
                "poll_id": sample_poll.id,
                "rankings": [
                    {"option_id": "opt_2", "rank": 1},
                    {"option_id": "opt_1", "rank": 2},
                    {"option_id": "opt_3", "rank": 3}
                ],
                "is_test": False
            },
            {
                "poll_id": sample_poll.id,
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_3", "rank": 2},
                    {"option_id": "opt_2", "rank": 2}  # Tie
                ],
                "is_test": False
            }
        ]
        
        # Create a mock cursor with async to_list method
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=test_ballots)
        mock_ballots.find.return_value = mock_cursor
        mock_ballots.count_documents = AsyncMock(return_value=0)  # No test ballots
        
        # Get results
        results = await ballot_service.get_live_results(sample_poll.id)
        
        # Verify results
        assert results.poll_id == sample_poll.id
        assert results.total_ballots == 3
        assert results.total_test_ballots == 0
        
        # Check first place counts
        assert results.first_place_counts["opt_1"] == 2
        assert results.first_place_counts["opt_2"] == 1
        assert results.first_place_counts["opt_3"] == 0
        assert results.first_place_counts["opt_4"] == 0
        
        # Check ranking matrix
        assert results.ranking_matrix["opt_1"][1] == 2  # opt_1 ranked 1st twice
        assert results.ranking_matrix["opt_1"][2] == 1  # opt_1 ranked 2nd once
        assert results.ranking_matrix["opt_2"][1] == 1  # opt_2 ranked 1st once
        assert results.ranking_matrix["opt_2"][2] == 2  # opt_2 ranked 2nd twice
        
        # Check pairwise preferences
        # opt_1 beats opt_2 in 2 ballots (ballots 1 and 3)
        assert results.pairwise_matrix["opt_1"]["opt_2"] == 2
        # opt_2 beats opt_1 in 1 ballot (ballot 2)
        assert results.pairwise_matrix["opt_2"]["opt_1"] == 1
    
    @pytest.mark.asyncio
    @patch('app.services.ballot_service.db')
    async def test_get_live_results_with_test_ballots(self, mock_db, ballot_service, sample_poll):
        """Test calculating results including test ballots"""
        # Setup mocks for the database property chain
        mock_ballots = MagicMock()
        mock_database = MagicMock()
        mock_database.ballots = mock_ballots
        mock_db.database = mock_database
        
        ballot_service.poll_service.get_poll.return_value = sample_poll
        
        # Include a test ballot
        test_ballots = [
            {
                "poll_id": sample_poll.id,
                "rankings": [{"option_id": "opt_1", "rank": 1}],
                "is_test": False
            },
            {
                "poll_id": sample_poll.id,
                "rankings": [{"option_id": "opt_2", "rank": 1}],
                "is_test": True  # Test ballot
            }
        ]
        
        # Create a mock cursor with async to_list method
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=test_ballots)
        mock_ballots.find.return_value = mock_cursor
        mock_ballots.count_documents = AsyncMock(return_value=1)  # 1 test ballot
        
        # Get results including test ballots
        results = await ballot_service.get_live_results(sample_poll.id, include_test=True)
        
        assert results.total_ballots == 1  # Only real ballot
        assert results.total_test_ballots == 1
        assert results.first_place_counts["opt_1"] == 1
        assert results.first_place_counts["opt_2"] == 1  # Includes test ballot