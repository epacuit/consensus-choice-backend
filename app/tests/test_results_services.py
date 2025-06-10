import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pref_voting.profiles_with_ties import ProfileWithTies

from app.services.results_service import ResultsService
from app.models.poll import Poll, PollOption
from app.models.results import (
    DetailedResults, VotingMethod, VotingMethodResult,
    BallotType, PairwiseComparison, HeadToHeadMatrix
)


class TestResultsService:
    """Test ResultsService with corrected implementation"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database"""
        with patch('app.services.results_service.db') as mock:
            yield mock
    
    @pytest.fixture
    def mock_poll_service(self):
        """Mock PollService"""
        with patch('app.services.results_service.PollService') as mock:
            yield mock
    
    @pytest.fixture
    def sample_poll(self):
        """Create a sample poll"""
        return Poll(
            id="poll_123",
            title="Best Programming Language",
            description="Vote for your favorite",
            options=[
                PollOption(id="opt_1", name="Python", description=""),
                PollOption(id="opt_2", name="JavaScript", description=""),
                PollOption(id="opt_3", name="Rust", description="")
            ],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            user_id="user_123",
            is_public=True,
            is_private=False,
            allow_anonymous=True,
            settings={}
        )
    
    @pytest.fixture
    def sample_ballots(self):
        """Create sample ballot documents"""
        return [
            # 5 voters: Python > JavaScript > Rust
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2},
                    {"option_id": "opt_3", "rank": 3}
                ],
                "is_test": False
            }
        ] * 5 + [
            # 4 voters: JavaScript > Rust > Python
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_2", "rank": 1},
                    {"option_id": "opt_3", "rank": 2},
                    {"option_id": "opt_1", "rank": 3}
                ],
                "is_test": False
            }
        ] * 4 + [
            # 3 voters: Rust > Python > JavaScript
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_3", "rank": 1},
                    {"option_id": "opt_1", "rank": 2},
                    {"option_id": "opt_2", "rank": 3}
                ],
                "is_test": False
            }
        ] * 3
    
    @pytest.fixture
    def ballots_with_ties(self):
        """Create ballot documents with ties"""
        return [
            # Python > JavaScript ~ Rust (tied for 2nd)
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2},
                    {"option_id": "opt_3", "rank": 2}
                ],
                "is_test": False
            }
        ] * 2 + [
            # JavaScript ~ Rust (tied for 1st) > Python
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_2", "rank": 1},
                    {"option_id": "opt_3", "rank": 1},
                    {"option_id": "opt_1", "rank": 2}
                ],
                "is_test": False
            }
        ] * 3
    
    @pytest.fixture
    def bullet_vote_ballots(self):
        """Create ballots with bullet votes (only one candidate ranked)"""
        return [
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_1", "rank": 1}
                ],
                "is_test": False
            }
        ] * 3
    
    def create_mock_ranking(self, rmap):
        """Create a mock Ranking object"""
        mock_ranking = MagicMock()
        mock_ranking.rmap = rmap
        
        # Mock the cands property (candidates in this ranking)
        mock_ranking.cands = list(rmap.keys())
        
        # Mock to_indiff_list() to return proper format for tied rankings
        # Group candidates by rank value
        rank_groups = {}
        for cand, rank in rmap.items():
            if rank not in rank_groups:
                rank_groups[rank] = []
            rank_groups[rank].append(cand)
        
        # Convert to list of lists format
        indiff_list = [rank_groups[rank] for rank in sorted(rank_groups.keys())]
        mock_ranking.to_indiff_list = MagicMock(return_value=indiff_list)
        
        # Mock is_bullet_vote() - true if only one candidate is ranked
        mock_ranking.is_bullet_vote = MagicMock(return_value=len(rmap) == 1)
        
        # Mock is_linear() - true if complete ranking with no ties
        def is_linear_mock(num_cands):
            # Linear if all candidates ranked and all ranks are different
            if len(rmap) != num_cands:
                return False
            return len(set(rmap.values())) == len(rmap)
        mock_ranking.is_linear = MagicMock(side_effect=is_linear_mock)
        
        # Mock is_truncated_linear() - true if partial ranking with no ties
        def is_truncated_linear_mock(num_cands):
            # Truncated linear if not all candidates ranked but no ties
            if len(rmap) >= num_cands:
                return False
            return len(set(rmap.values())) == len(rmap)
        mock_ranking.is_truncated_linear = MagicMock(side_effect=is_truncated_linear_mock)
        
        # Mock extended_strict_pref() for head-to-head comparisons
        def extended_strict_pref_mock(c1, c2):
            # c1 beats c2 if c1 is ranked and c2 is not, or if both ranked and c1 has lower rank
            if c1 in rmap and c2 not in rmap:
                return True
            if c1 in rmap and c2 in rmap:
                return rmap[c1] < rmap[c2]
            return False
        mock_ranking.extended_strict_pref = MagicMock(side_effect=extended_strict_pref_mock)
        
        return mock_ranking
    
    def create_mock_profile(self, rankings_data, counts, candidates):
        """Create a mock ProfileWithTies object"""
        mock_profile = MagicMock(spec=ProfileWithTies)
        
        # Create mock ranking objects
        mock_rankings = []
        for ranking_dict in rankings_data:
            mock_rankings.append(self.create_mock_ranking(ranking_dict))
        
        mock_profile.rankings = mock_rankings
        mock_profile.rcounts = counts
        mock_profile.candidates = candidates
        mock_profile.num_voters = sum(counts)
        
        # Mock the rankings_counts property to return tuple of (rankings, counts)
        mock_profile.rankings_counts = (mock_rankings, counts)
        
        # Mock methods
        mock_profile.condorcet_winner = MagicMock(return_value=None)
        mock_profile.weak_condorcet_winner = MagicMock(return_value=[])
        mock_profile.margin = MagicMock(return_value=0)
        
        # Create a proper support function that calculates based on rankings
        def support_side_effect(c1, c2):
            total_support = 0
            for ranking, count in zip(mock_rankings, counts):
                if ranking.extended_strict_pref(c1, c2):
                    total_support += count
            return total_support
        
        mock_profile.support = MagicMock(side_effect=support_side_effect)
        mock_profile.use_extended_strict_preference = MagicMock()
        
        return mock_profile
    
    @pytest.mark.asyncio
    async def test_calculate_detailed_results_basic(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test basic calculation of detailed results"""
        # Setup mocks
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        # Mock database query
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        # Create a mock profile with proper structure
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2, 'C2': 3}, {'C1': 1, 'C2': 2, 'C0': 3}, {'C2': 1, 'C0': 2, 'C1': 3}],
            [5, 4, 3],
            ['C0', 'C1', 'C2']
        )
        mock_profile.condorcet_winner.return_value = 'C0'
        mock_profile.weak_condorcet_winner.return_value = ['C0']
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            mock_minimax.return_value = ["C0"]  # Python
            mock_copeland_global_minimax.return_value = ["C0"]  # Python
            
            # Calculate results
            results = await service.calculate_detailed_results("poll_123")
        
        # Verify basic properties
        assert results.poll_id == "poll_123"
        assert results.total_voters == 12
        assert results.total_ballots == 12
        assert results.num_candidates == 3
        assert set(results.candidates) == {"Python", "JavaScript", "Rust"}
        
        # Verify condorcet winners
        assert results.condorcet_winner == "Python"
        assert results.weak_condorcet_winner == "Python"
    
    @pytest.mark.asyncio
    async def test_calculate_detailed_results_with_ties(
        self, mock_db, mock_poll_service, sample_poll, ballots_with_ties
    ):
        """Test calculation with tied rankings"""
        # Setup mocks
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=ballots_with_ties)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        # Create a mock profile with ties
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2, 'C2': 2}, {'C1': 1, 'C2': 1, 'C0': 2}],
            [2, 3],
            ['C0', 'C1', 'C2']
        )
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            mock_minimax.return_value = ["C1", "C2"]  # Tie
            mock_copeland_global_minimax.return_value = ["C1"]
            
            results = await service.calculate_detailed_results("poll_123")
        
        # Verify no condorcet winners
        assert results.condorcet_winner is None
        assert results.weak_condorcet_winner is None
    
    @pytest.mark.asyncio
    async def test_calculate_detailed_results_poll_not_found(
        self, mock_db, mock_poll_service
    ):
        """Test error when poll is not found"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=None)
        
        with pytest.raises(ValueError, match="Poll poll_123 not found"):
            await service.calculate_detailed_results("poll_123")
    
    @pytest.mark.asyncio
    async def test_calculate_detailed_results_no_ballots(
        self, mock_db, mock_poll_service, sample_poll
    ):
        """Test error when no ballots are found"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.database.ballots.find.return_value = mock_cursor
        
        with pytest.raises(ValueError, match="No ballots found"):
            await service.calculate_detailed_results("poll_123")
    
    @pytest.mark.asyncio
    async def test_exclude_test_ballots(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test that test ballots are excluded by default"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        # Add test ballot
        all_ballots = sample_ballots + [{
            "poll_id": "poll_123",
            "rankings": [{"option_id": "opt_1", "rank": 1}],
            "is_test": True
        }]
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)  # Only non-test
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1}],
            [1],
            ['C0', 'C1', 'C2']
        )
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            await service.calculate_detailed_results("poll_123")
        
        # Verify query excluded test ballots
        mock_db.database.ballots.find.assert_called_with({
            "poll_id": "poll_123",
            "is_test": {"$ne": True}
        })
    
    @pytest.mark.asyncio
    async def test_include_test_ballots(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test including test ballots when requested"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1}],
            [1],
            ['C0', 'C1', 'C2']
        )
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            await service.calculate_detailed_results("poll_123", include_test=True)
        
        # Verify query included all ballots
        mock_db.database.ballots.find.assert_called_with({"poll_id": "poll_123"})
    
    @pytest.mark.asyncio
    async def test_voting_method_results(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test voting method results"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2}],
            [1],
            ['C0', 'C1']
        )
        mock_profile.condorcet_winner.return_value = 'C0'
        mock_profile.weak_condorcet_winner.return_value = ['C0']
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            mock_minimax.return_value = ["C0", "C1"]  # Tie
            mock_copeland_global_minimax.return_value = "C0"  # Single winner
            
            results = await service.calculate_detailed_results("poll_123")
        
        # Should have exactly 2 voting method results
        assert len(results.voting_results) == 2
        
        # Check minimax result
        minimax_result = next(r for r in results.voting_results if r.method == VotingMethod.MINIMAX)
        assert len(minimax_result.winners) == 2
        assert minimax_result.is_tie is True
        
        # Check copeland global minimax result
        copeland_gm_result = next(r for r in results.voting_results if r.method == VotingMethod.COPELAND_GLOBAL_MINIMAX)
        assert len(copeland_gm_result.winners) == 1
        assert copeland_gm_result.is_tie is False
    
    @pytest.mark.asyncio
    async def test_bullet_vote_counting(
        self, mock_db, mock_poll_service, sample_poll, bullet_vote_ballots
    ):
        """Test counting of bullet votes"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=bullet_vote_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        # Create mock profile with bullet votes
        mock_profile = self.create_mock_profile(
            [{'C0': 1}],  # Only C0 ranked
            [3],
            ['C0', 'C1', 'C2']
        )
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            results = await service.calculate_detailed_results("poll_123")
        
        assert results.num_bullet_votes == 3
        assert results.num_complete_rankings == 0
    
    def test_create_profile_from_ballots(self):
        """Test profile creation from ballots"""
        service = ResultsService()
        
        poll = Poll(
            id="poll_123",
            title="Test Poll",
            description="",
            options=[
                PollOption(id="opt_1", name="A", description=""),
                PollOption(id="opt_2", name="B", description="")
            ],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            user_id="user_123",
            is_public=True,
            is_private=False,
            allow_anonymous=True,
            settings={}
        )
        
        ballots = [
            {
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2}
                ]
            },
            {
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2}
                ]
            },
            {
                "rankings": [
                    {"option_id": "opt_2", "rank": 1},
                    {"option_id": "opt_1", "rank": 2}
                ]
            }
        ]
        
        with patch('app.services.results_service.ProfileWithTies') as mock_profile_class:
            mock_profile = MagicMock()
            mock_profile_class.return_value = mock_profile
            
            profile = service._create_profile_from_ballots(poll, ballots)
            
            # Verify ProfileWithTies was called with correct arguments
            mock_profile_class.assert_called_once()
            call_args = mock_profile_class.call_args
            
            # Check rankings format (dictionaries)
            rankings = call_args[0][0]
            assert len(rankings) == 2  # Two unique ballot types
            assert rankings[0] == {'C0': 1, 'C1': 2}
            assert rankings[1] == {'C1': 1, 'C0': 2}
            
            # Check counts
            assert 'rcounts' in call_args[1]
            assert call_args[1]['rcounts'] == [2, 1]  # First ballot type appears twice
            
            # Check candidates
            assert call_args[1]['candidates'] == ['C0', 'C1']
    
    @pytest.mark.asyncio
    async def test_weak_condorcet_winner_field(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test that weak_condorcet_winner field is properly set"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2}],
            [1],
            ['C0', 'C1', 'C2']
        )
        mock_profile.condorcet_winner.return_value = None
        mock_profile.weak_condorcet_winner.return_value = ["C1"]
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C1"]
            mock_copeland_global_minimax.return_value = ["C1"]
            
            results = await service.calculate_detailed_results("poll_123")
            
            # Now this should pass with the corrected service
            assert results.weak_condorcet_winner == "JavaScript"
    
    @pytest.mark.asyncio
    async def test_weak_condorcet_multiple_winners(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test weak_condorcet_winner when multiple weak winners exist"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1}],
            [1],
            ['C0', 'C1', 'C2']
        )
        mock_profile.condorcet_winner.return_value = None
        mock_profile.weak_condorcet_winner.return_value = ["C0", "C1", "C2"]
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            results = await service.calculate_detailed_results("poll_123")
            
            # Service takes the first one
            assert results.weak_condorcet_winner == "Python"
    
    @pytest.mark.asyncio
    async def test_pairwise_comparisons(
        self, mock_db, mock_poll_service, sample_poll, sample_ballots
    ):
        """Test pairwise comparison calculations"""
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=sample_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=sample_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2, 'C2': 3}],
            [1],
            ['C0', 'C1', 'C2']
        )
        
        # Mock margin and support methods - support calculation is now automatic via create_mock_profile
        mock_profile.margin.side_effect = lambda a, b: 1 if a == 'C0' and b == 'C1' else -1
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            results = await service.calculate_detailed_results("poll_123")
        
        # Should have 3 pairwise comparisons for 3 candidates
        assert len(results.pairwise_comparisons) == 3
        
        # Check that all pairs are covered
        pairs = {(pc.candidate_a, pc.candidate_b) for pc in results.pairwise_comparisons}
        expected_pairs = {
            ("Python", "JavaScript"),
            ("Python", "Rust"),
            ("JavaScript", "Rust")
        }
        for pair in expected_pairs:
            assert pair in pairs or (pair[1], pair[0]) in pairs
    
    @pytest.mark.asyncio
    async def test_pairwise_matrix_structure(
        self, mock_db, mock_poll_service
    ):
        """Test pairwise matrix has correct structure"""
        # Simple 2-candidate scenario for clarity
        simple_poll = Poll(
            id="poll_123",
            title="Simple Poll",
            description="",
            options=[
                PollOption(id="opt_1", name="A", description=""),
                PollOption(id="opt_2", name="B", description="")
            ],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            user_id="user_123",
            is_public=True,
            is_private=False,
            allow_anonymous=True,
            settings={}
        )
        
        simple_ballots = [
            # 3 voters: A > B
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_1", "rank": 1},
                    {"option_id": "opt_2", "rank": 2}
                ],
                "is_test": False
            }
        ] * 3 + [
            # 2 voters: B > A
            {
                "poll_id": "poll_123",
                "rankings": [
                    {"option_id": "opt_2", "rank": 1},
                    {"option_id": "opt_1", "rank": 2}
                ],
                "is_test": False
            }
        ] * 2
        
        service = ResultsService()
        service.poll_service = mock_poll_service.return_value
        service.poll_service.get_poll = AsyncMock(return_value=simple_poll)
        
        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=simple_ballots)
        mock_db.database.ballots.find.return_value = mock_cursor
        
        mock_profile = self.create_mock_profile(
            [{'C0': 1, 'C1': 2}, {'C1': 1, 'C0': 2}],
            [3, 2],
            ['C0', 'C1']
        )
        
        # Mock margin calculations
        def margin_side_effect(a, b):
            if a == 'C0' and b == 'C1':
                return 1  # A beats B by 1 (3-2)
            elif a == 'C1' and b == 'C0':
                return -1  # B loses to A by 1
            else:
                return 0
        
        mock_profile.margin.side_effect = margin_side_effect
        
        with patch('app.services.results_service.ProfileWithTies', return_value=mock_profile), \
             patch('app.services.results_service.minimax') as mock_minimax, \
             patch('app.services.results_service.copeland_global_minimax') as mock_copeland_global_minimax:
            
            # Set proper return values for voting methods
            mock_minimax.return_value = ["C0"]
            mock_copeland_global_minimax.return_value = ["C0"]
            
            results = await service.calculate_detailed_results("poll_123")
        
        # Check matrix structure
        assert "A" in results.pairwise_matrix
        assert "B" in results.pairwise_matrix
        assert "A" in results.pairwise_matrix["A"]
        assert "B" in results.pairwise_matrix["A"]
        assert "A" in results.pairwise_matrix["B"]
        assert "B" in results.pairwise_matrix["B"]
        
        # Check margins
        assert results.pairwise_matrix["A"]["B"] == 1  # A beats B by 1 (3-2)
        assert results.pairwise_matrix["B"]["A"] == -1  # B loses to A by 1
        assert results.pairwise_matrix["A"]["A"] == 0  # Self-comparison is 0
        assert results.pairwise_matrix["B"]["B"] == 0  # Self-comparison is 0