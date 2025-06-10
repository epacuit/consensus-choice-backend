"""
Integration tests for results calculation with real database

Make sure you have pytest-asyncio installed:
pip install pytest-asyncio

To run these tests:
MONGODB_DB=betterchoices_test pytest app/tests/test_results_integration.py -v

Or set the test database in your .env.test file.
"""

import pytest
import pytest_asyncio
import asyncio
from datetime import datetime
import os
from typing import List, Dict

# IMPORTANT: Set test database BEFORE any imports that use it
if "MONGODB_DB" not in os.environ:
    os.environ["MONGODB_DB"] = "betterchoices_test"

# Now import after env is set
from app.database import db, connect_db, close_db
from app.services.poll_service import PollService
from app.services.results_service import ResultsService
from app.models.poll import PollCreate
from app.models.results import VotingMethod


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
async def results_service(setup_database):
    """Get real results service."""
    return ResultsService()


async def create_test_poll(poll_service) -> str:
    """Helper to create a test poll."""
    poll_data = PollCreate(
        title="Test Election",
        description="Integration test for results",
        options=["Alice", "Bob", "Charlie", "David"],
        tags=["test", "results"]
    )
    poll = await poll_service.create_poll(poll_data)
    return poll.id


async def add_ballot(poll_id: str, rankings: List[Dict[str, any]], is_test: bool = False):
    """Helper to add a ballot to the database."""
    ballot = {
        "poll_id": poll_id,
        "rankings": rankings,
        "is_test": is_test,
        "created_at": datetime.utcnow()
    }
    result = await db.database.ballots.insert_one(ballot)
    return str(result.inserted_id)


class TestResultsIntegration:
    """Test real results calculation with database."""
    
    @pytest.mark.asyncio
    async def test_simple_condorcet_winner(self, poll_service, results_service):
        """Test calculation with a clear Condorcet winner."""
        # Create poll
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        
        # Map names to option IDs
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add ballots where Alice beats everyone
        # 60% prefer Alice > Bob > Charlie > David
        for _ in range(6):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1},
                {"option_id": option_map["Bob"], "rank": 2},
                {"option_id": option_map["Charlie"], "rank": 3},
                {"option_id": option_map["David"], "rank": 4}
            ])
        
        # 40% have different preferences but Alice still wins overall
        for _ in range(4):
            await add_ballot(poll_id, [
                {"option_id": option_map["Bob"], "rank": 1},
                {"option_id": option_map["Alice"], "rank": 2},
                {"option_id": option_map["Charlie"], "rank": 3},
                {"option_id": option_map["David"], "rank": 4}
            ])
        
        # Calculate results
        results = await results_service.calculate_detailed_results(poll_id)
        
        # Verify basic stats
        assert results.total_voters == 10
        assert results.total_ballots == 10
        assert results.num_candidates == 4
        assert results.condorcet_winner == "Alice"
        
        # Verify pairwise matrix
        assert results.pairwise_matrix["Alice"]["Bob"] > 0
        assert results.pairwise_matrix["Alice"]["Charlie"] > 0
        assert results.pairwise_matrix["Alice"]["David"] > 0
        
        # Verify voting method results
        minimax_result = next(r for r in results.voting_results if r.method == VotingMethod.MINIMAX)
        assert "Alice" in minimax_result.winners
        assert not minimax_result.is_tie
    
    @pytest.mark.asyncio
    async def test_tied_winners(self, poll_service, results_service):
        """Test calculation with tied winners."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Create a symmetric situation
        # 25% each for different preferences
        preferences = [
            ["Alice", "Bob", "Charlie", "David"],
            ["Bob", "Charlie", "David", "Alice"],
            ["Charlie", "David", "Alice", "Bob"],
            ["David", "Alice", "Bob", "Charlie"]
        ]
        
        for pref in preferences:
            for _ in range(2):  # 2 voters per preference = 8 total
                rankings = []
                for rank, name in enumerate(pref, 1):
                    rankings.append({
                        "option_id": option_map[name],
                        "rank": rank
                    })
                await add_ballot(poll_id, rankings)
        
        results = await results_service.calculate_detailed_results(poll_id)
        
        assert results.total_voters == 8
        assert results.condorcet_winner is None  # No Condorcet winner
        
        # Check for ties in voting methods
        for voting_result in results.voting_results:
            if voting_result.is_tie:
                assert len(voting_result.winners) > 1
    
    @pytest.mark.asyncio
    async def test_ballot_types_analysis(self, poll_service, results_service):
        """Test ballot type counting and analysis."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add bullet votes (only rank one candidate)
        for _ in range(3):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1}
            ])
        
        # Add complete rankings
        for _ in range(2):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1},
                {"option_id": option_map["Bob"], "rank": 2},
                {"option_id": option_map["Charlie"], "rank": 3},
                {"option_id": option_map["David"], "rank": 4}
            ])
        
        # Add rankings with ties
        for _ in range(2):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1},
                {"option_id": option_map["Bob"], "rank": 1},  # Tie at rank 1
                {"option_id": option_map["Charlie"], "rank": 2},
                {"option_id": option_map["David"], "rank": 3}
            ])
        
        results = await results_service.calculate_detailed_results(poll_id)
        
        assert results.num_bullet_votes == 3
        assert results.num_complete_rankings == 4  # 2 strict complete + 2 complete with ties
        assert results.num_linear_orders == 5  # bullet votes + complete rankings (no ties)
        
        # Check ballot types
        assert len(results.ballot_types) >= 3  # At least 3 different types
        assert sum(bt.count for bt in results.ballot_types) == 7
    
    @pytest.mark.asyncio
    async def test_head_to_head_matrices(self, poll_service, results_service):
        """Test head-to-head matrix calculation."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add specific ballots to test head-to-head
        # 5 ballots: Alice > Bob > Charlie > David
        for _ in range(5):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1},
                {"option_id": option_map["Bob"], "rank": 2},
                {"option_id": option_map["Charlie"], "rank": 3},
                {"option_id": option_map["David"], "rank": 4}
            ])
        
        # 3 ballots: Bob > Alice > David > Charlie
        for _ in range(3):
            await add_ballot(poll_id, [
                {"option_id": option_map["Bob"], "rank": 1},
                {"option_id": option_map["Alice"], "rank": 2},
                {"option_id": option_map["David"], "rank": 3},
                {"option_id": option_map["Charlie"], "rank": 4}
            ])
        
        results = await results_service.calculate_detailed_results(poll_id)
        
        # Find Alice vs Bob head-to-head
        alice_vs_bob = next(
            h for h in results.head_to_head_matrices 
            if h.candidate_a == "Alice" and h.candidate_b == "Bob"
        )
        
        assert alice_vs_bob.total_count == 5  # 5 ballots have Alice > Bob
        assert len(alice_vs_bob.ballot_types) == 1  # Only one ballot type ranks Alice > Bob
        
        # Verify pairwise comparison
        alice_bob_comparison = next(
            c for c in results.pairwise_comparisons
            if (c.candidate_a == "Alice" and c.candidate_b == "Bob") or
               (c.candidate_a == "Bob" and c.candidate_b == "Alice")
        )
        
        if alice_bob_comparison.candidate_a == "Alice":
            assert alice_bob_comparison.a_beats_b == 5
            assert alice_bob_comparison.b_beats_a == 3
        else:
            assert alice_bob_comparison.a_beats_b == 3
            assert alice_bob_comparison.b_beats_a == 5
    
    @pytest.mark.asyncio
    async def test_test_ballots_filtering(self, poll_service, results_service):
        """Test filtering of test ballots."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add regular ballots
        for _ in range(5):
            await add_ballot(poll_id, [
                {"option_id": option_map["Alice"], "rank": 1},
                {"option_id": option_map["Bob"], "rank": 2}
            ])
        
        # Add test ballots
        for _ in range(3):
            await add_ballot(poll_id, [
                {"option_id": option_map["Charlie"], "rank": 1},
                {"option_id": option_map["David"], "rank": 2}
            ], is_test=True)
        
        # Results without test ballots
        results_no_test = await results_service.calculate_detailed_results(poll_id, include_test=False)
        assert results_no_test.total_voters == 5
        
        # Results with test ballots
        results_with_test = await results_service.calculate_detailed_results(poll_id, include_test=True)
        assert results_with_test.total_voters == 8
    
    @pytest.mark.asyncio
    async def test_concurrent_results_calculation(self, poll_service, results_service):
        """Test concurrent calculation of results."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add many ballots
        for i in range(50):
            rankings = []
            # Create different ranking patterns
            if i % 3 == 0:
                order = ["Alice", "Bob", "Charlie", "David"]
            elif i % 3 == 1:
                order = ["Bob", "Charlie", "Alice", "David"]
            else:
                order = ["Charlie", "David", "Bob", "Alice"]
            
            for rank, name in enumerate(order, 1):
                rankings.append({
                    "option_id": option_map[name],
                    "rank": rank
                })
            await add_ballot(poll_id, rankings)
        
        # Calculate results multiple times concurrently
        tasks = []
        for _ in range(10):
            tasks.append(results_service.calculate_detailed_results(poll_id))
        
        results_list = await asyncio.gather(*tasks)
        
        # All results should be identical
        first_result = results_list[0]
        for result in results_list[1:]:
            assert result.total_voters == first_result.total_voters
            assert result.condorcet_winner == first_result.condorcet_winner
            assert result.num_bullet_votes == first_result.num_bullet_votes
    
    @pytest.mark.asyncio
    async def test_empty_poll_results(self, poll_service, results_service):
        """Test handling poll with no ballots."""
        poll_id = await create_test_poll(poll_service)
        
        # Try to calculate results for empty poll
        with pytest.raises(ValueError, match="No ballots found"):
            await results_service.calculate_detailed_results(poll_id)
    
    @pytest.mark.asyncio
    async def test_invalid_poll_id(self, results_service):
        """Test handling invalid poll ID."""
        fake_poll_id = "000000000000000000000000"
        
        with pytest.raises(ValueError, match="Poll .* not found"):
            await results_service.calculate_detailed_results(fake_poll_id)
    
    @pytest.mark.asyncio
    async def test_large_scale_results(self, poll_service, results_service):
        """Test performance with many ballots."""
        poll_id = await create_test_poll(poll_service)
        poll = await poll_service.get_poll(poll_id)
        option_map = {opt.name: opt.id for opt in poll.options}
        
        # Add 1000 ballots
        start_time = datetime.utcnow()
        
        for i in range(1000):
            # Create varied preferences
            if i % 4 == 0:
                rankings = [
                    {"option_id": option_map["Alice"], "rank": 1},
                    {"option_id": option_map["Bob"], "rank": 2},
                    {"option_id": option_map["Charlie"], "rank": 3},
                    {"option_id": option_map["David"], "rank": 4}
                ]
            elif i % 4 == 1:
                rankings = [
                    {"option_id": option_map["Bob"], "rank": 1},
                    {"option_id": option_map["Charlie"], "rank": 2},
                    {"option_id": option_map["Alice"], "rank": 3}
                ]
            elif i % 4 == 2:
                rankings = [
                    {"option_id": option_map["Charlie"], "rank": 1}
                ]  # Bullet vote
            else:
                rankings = [
                    {"option_id": option_map["David"], "rank": 1},
                    {"option_id": option_map["Alice"], "rank": 1},  # Tie
                    {"option_id": option_map["Bob"], "rank": 2}
                ]
            
            await add_ballot(poll_id, rankings)
        
        ballot_creation_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Calculate results
        start_time = datetime.utcnow()
        results = await results_service.calculate_detailed_results(poll_id)
        calculation_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Performance assertions
        assert ballot_creation_time < 10.0  # Should create 1000 ballots in < 10 seconds
        assert calculation_time < 5.0  # Should calculate results in < 5 seconds
        
        # Verify results
        assert results.total_voters == 1000
        assert results.num_bullet_votes == 250  # 25% are bullet votes
        assert len(results.ballot_types) == 4  # 4 different ballot types
        
        # Verify all calculations completed
        assert results.pairwise_matrix is not None
        assert len(results.pairwise_comparisons) == 6  # C(4,2) = 6 pairs
        assert len(results.voting_results) == 2  # Minimax and Copeland Global Minimax
        assert len(results.head_to_head_matrices) > 0