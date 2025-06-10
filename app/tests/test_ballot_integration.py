"""
Integration tests for ballot functionality with real database

To run these tests:
MONGODB_DB=betterchoices_test pytest app/tests/test_ballot_integration.py -v

Or set the test database in your .env.test file.
"""

import pytest
import pytest_asyncio
import asyncio
from bson import ObjectId
from datetime import datetime
import os

# IMPORTANT: Set test database BEFORE any imports that use it
if "MONGODB_DB" not in os.environ:
    os.environ["MONGODB_DB"] = "betterchoices_test"

# Now import after env is set
from app.database import db, connect_db, close_db
from app.services.poll_service import PollService
from app.services.ballot_service import BallotService
from app.models.poll import PollCreate
from app.models.ballot import BallotSubmit, RankingEntry, VoterType
from app.config import settings


@pytest_asyncio.fixture(scope="function")
async def setup_database():
    """Setup and teardown test database."""
    # Connect to the test database
    await connect_db()
    
    yield
    
    # Clean up test data after each test
    try:
        await db.database.polls.delete_many({})
        await db.database.ballots.delete_many({})
    except Exception as e:
        print(f"Cleanup error: {e}")
    
    # Close connection after test
    await close_db()


@pytest_asyncio.fixture
async def poll_service(setup_database):
    """Get real poll service."""
    return PollService()


@pytest_asyncio.fixture
async def ballot_service(setup_database):
    """Get real ballot service."""
    return BallotService()


@pytest_asyncio.fixture
async def test_poll(poll_service):
    """Create a test poll for ballot tests."""
    poll_data = PollCreate(
        title="Best Programming Language",
        description="Vote for your favorite",
        options=["Python", "JavaScript", "Go", "Rust", "Java"],
        is_private=False
    )
    poll = await poll_service.create_poll(poll_data)
    yield poll
    # Cleanup
    await poll_service.delete_poll(poll.id)


@pytest_asyncio.fixture
async def private_test_poll(poll_service):
    """Create a private test poll with voters."""
    poll_data = PollCreate(
        title="Team Lunch Location",
        description="Where should we go?",
        options=["Italian", "Japanese", "Mexican", "Thai"],
        is_private=True,
        voter_emails=["alice@example.com", "bob@example.com", "charlie@example.com"]
    )
    poll = await poll_service.create_poll(poll_data)
    
    # Get the poll document to access voter tokens
    poll_doc = await db.database.polls.find_one({"_id": ObjectId(poll.id)})
    
    # Return both the poll and voters separately
    yield poll, poll_doc["voters"]
    # Cleanup
    await poll_service.delete_poll(poll.id)


class TestBallotIntegration:
    """Test ballot operations with real database."""
    
    @pytest.mark.asyncio
    async def test_submit_ballot_public_poll(self, ballot_service, test_poll):
        """Test submitting a ballot to a public poll."""
        ballot_data = BallotSubmit(
            poll_id=test_poll.id,
            rankings=[
                RankingEntry(option_id=test_poll.options[0].id, rank=1),  # Python
                RankingEntry(option_id=test_poll.options[1].id, rank=2),  # JavaScript
                RankingEntry(option_id=test_poll.options[3].id, rank=3),  # Rust
            ],
            browser_fingerprint="test_fingerprint_123"
        )
        
        # Submit ballot
        ballot = await ballot_service.submit_ballot(ballot_data)
        
        # Verify ballot was created
        assert ballot.id is not None
        assert ballot.poll_id == test_poll.id
        assert ballot.voter_type == VoterType.ANONYMOUS
        assert len(ballot.rankings) == 3
        assert not ballot.is_test
        
        # Verify in database
        ballot_doc = await db.database.ballots.find_one({"_id": ObjectId(ballot.id)})
        assert ballot_doc is not None
        assert ballot_doc["poll_id"] == test_poll.id
    
    @pytest.mark.asyncio
    async def test_submit_ballot_with_ties_and_gaps(self, ballot_service, test_poll):
        """Test submitting a ballot with tied rankings and gaps."""
        ballot_data = BallotSubmit(
            poll_id=test_poll.id,
            rankings=[
                RankingEntry(option_id=test_poll.options[0].id, rank=1),   # Python - 1st
                RankingEntry(option_id=test_poll.options[1].id, rank=2),   # JavaScript - 2nd (tie)
                RankingEntry(option_id=test_poll.options[2].id, rank=2),   # Go - 2nd (tie)
                RankingEntry(option_id=test_poll.options[3].id, rank=5),   # Rust - 5th (gap)
            ],
            browser_fingerprint="test_fingerprint_456"
        )
        
        ballot = await ballot_service.submit_ballot(ballot_data)
        
        # Verify ties (two options with rank 2)
        rank_2_count = sum(1 for r in ballot.rankings if r.rank == 2)
        assert rank_2_count == 2
        
        # Verify gap (no rank 3 or 4)
        ranks = [r.rank for r in ballot.rankings]
        assert 3 not in ranks
        assert 4 not in ranks
        assert 5 in ranks
    
    @pytest.mark.asyncio
    async def test_duplicate_vote_prevention(self, ballot_service, test_poll):
        """Test that duplicate votes from same browser are prevented."""
        ballot_data = BallotSubmit(
            poll_id=test_poll.id,
            rankings=[
                RankingEntry(option_id=test_poll.options[0].id, rank=1)
            ],
            browser_fingerprint="duplicate_test_fingerprint"
        )
        
        # First submission should succeed
        ballot1 = await ballot_service.submit_ballot(ballot_data)
        assert ballot1 is not None
        
        # Second submission with same fingerprint should fail
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(ballot_data)
        assert "already been submitted" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_submit_ballot_private_poll(self, ballot_service, private_test_poll):
        """Test submitting a ballot to a private poll with token."""
        poll, voters = private_test_poll
        
        # Get Alice's token
        alice_voter = next(v for v in voters if v["email"] == "alice@example.com")
        
        ballot_data = BallotSubmit(
            poll_id=poll.id,
            rankings=[
                RankingEntry(option_id=poll.options[0].id, rank=1),  # Italian
                RankingEntry(option_id=poll.options[2].id, rank=2),  # Mexican
            ],
            voter_token=alice_voter["token"]
        )
        
        ballot = await ballot_service.submit_ballot(ballot_data)
        
        assert ballot.voter_type == VoterType.AUTHENTICATED
        assert ballot.voter_email == "alice@example.com"
        
        # Try to vote again with same token - should fail
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(ballot_data)
        assert "already submitted" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_submit_ballot_test_mode(self, ballot_service, test_poll):
        """Test submitting multiple ballots in test mode."""
        # Submit multiple test ballots with same fingerprint
        ballots = []
        for i in range(3):
            ballot_data = BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[i].id, rank=1)
                ],
                browser_fingerprint="test_mode_fingerprint",
                test_mode_key=settings.SECRET_KEY
            )
            
            ballot = await ballot_service.submit_ballot(ballot_data)
            assert ballot.voter_type == VoterType.TEST
            assert ballot.is_test is True
            ballots.append(ballot)
        
        # Verify all 3 were created
        assert len(ballots) == 3
    
    @pytest.mark.asyncio
    async def test_get_live_results(self, ballot_service, test_poll):
        """Test getting live voting results."""
        # Submit several ballots
        ballots_data = [
            # Ballot 1: Python > JavaScript > Go
            BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[0].id, rank=1),
                    RankingEntry(option_id=test_poll.options[1].id, rank=2),
                    RankingEntry(option_id=test_poll.options[2].id, rank=3)
                ],
                browser_fingerprint="voter1"
            ),
            # Ballot 2: JavaScript > Python
            BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[1].id, rank=1),
                    RankingEntry(option_id=test_poll.options[0].id, rank=2)
                ],
                browser_fingerprint="voter2"
            ),
            # Ballot 3: Python > Rust (tie) > Go (tie)
            BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[0].id, rank=1),
                    RankingEntry(option_id=test_poll.options[3].id, rank=2),
                    RankingEntry(option_id=test_poll.options[2].id, rank=2)
                ],
                browser_fingerprint="voter3"
            )
        ]
        
        # Submit all ballots
        for ballot_data in ballots_data:
            await ballot_service.submit_ballot(ballot_data)
        
        # Get results
        results = await ballot_service.get_live_results(test_poll.id)
        
        # Verify results
        assert results.poll_id == test_poll.id
        assert results.total_ballots == 3
        assert results.total_test_ballots == 0
        
        # Check first place counts
        python_id = test_poll.options[0].id
        javascript_id = test_poll.options[1].id
        
        assert results.first_place_counts[python_id] == 2
        assert results.first_place_counts[javascript_id] == 1
        
        # Check pairwise matrix
        # Python beats JavaScript in ballot 1 (both ranked)
        # JavaScript beats Python in ballot 2 (both ranked)
        # In ballot 3, JavaScript is not ranked, so no comparison
        # Final result: 1-1 tie
        assert results.pairwise_matrix[python_id][javascript_id] == 1
        assert results.pairwise_matrix[javascript_id][python_id] == 1
    
    @pytest.mark.asyncio
    async def test_concurrent_ballot_submission(self, ballot_service, test_poll):
        """Test submitting multiple ballots concurrently."""
        # Create 10 different ballots
        tasks = []
        for i in range(10):
            ballot_data = BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[i % 5].id, rank=1)
                ],
                browser_fingerprint=f"concurrent_voter_{i}"
            )
            tasks.append(ballot_service.submit_ballot(ballot_data))
        
        # Submit concurrently
        results = await asyncio.gather(*tasks)
        
        # Verify all were created
        assert len(results) == 10
        assert all(ballot.id is not None for ballot in results)
        
        # Verify results
        live_results = await ballot_service.get_live_results(test_poll.id)
        assert live_results.total_ballots == 10
    
    @pytest.mark.asyncio
    async def test_invalid_ballot_submissions(self, ballot_service, test_poll):
        """Test various invalid ballot submission scenarios."""
        # Test with invalid option ID
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(BallotSubmit(
                poll_id=test_poll.id,
                rankings=[RankingEntry(option_id="invalid_id", rank=1)],
                browser_fingerprint="test"
            ))
        assert "Invalid option ID" in str(exc_info.value)
        
        # Test with non-existent poll
        with pytest.raises(ValueError) as exc_info:
            await ballot_service.submit_ballot(BallotSubmit(
                poll_id="507f1f77bcf86cd799439999",
                rankings=[RankingEntry(option_id="any", rank=1)],
                browser_fingerprint="test"
            ))
        assert "not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_large_scale_voting(self, ballot_service, test_poll):
        """Test performance with many ballots."""
        # Submit 100 ballots
        start_time = datetime.utcnow()
        
        for i in range(100):
            ballot_data = BallotSubmit(
                poll_id=test_poll.id,
                rankings=[
                    RankingEntry(option_id=test_poll.options[i % 5].id, rank=1),
                    RankingEntry(option_id=test_poll.options[(i + 1) % 5].id, rank=2)
                ],
                browser_fingerprint=f"voter_{i}"
            )
            await ballot_service.submit_ballot(ballot_data)
        
        submit_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Should handle 100 ballots reasonably quickly
        assert submit_time < 10.0  # Less than 10 seconds
        
        # Test results calculation performance
        start_time = datetime.utcnow()
        results = await ballot_service.get_live_results(test_poll.id)
        results_time = (datetime.utcnow() - start_time).total_seconds()
        
        assert results_time < 2.0  # Less than 2 seconds
        assert results.total_ballots == 100