import pytest
from datetime import datetime
from pydantic import ValidationError

from app.models.results import (
    VotingMethod, BallotType, PairwiseComparison, HeadToHeadMatrix,
    VotingMethodResult, DetailedResults, ResultsSummary
)


class TestBallotType:
    """Test BallotType model"""
    
    def test_valid_ballot_type(self):
        """Test creating a valid ballot type"""
        ballot_type = BallotType(
            ranking=[["Python"], ["JavaScript", "Go"], ["Rust"]],
            count=25,
            percentage=33.3
        )
        assert ballot_type.count == 25
        assert ballot_type.percentage == 33.3
        assert len(ballot_type.ranking) == 3
    
    def test_ranking_string_single_candidates(self):
        """Test ranking string with no ties"""
        ballot_type = BallotType(
            ranking=[["A"], ["B"], ["C"]],
            count=10,
            percentage=20.0
        )
        assert ballot_type.ranking_string == "A > B > C"
    
    def test_ranking_string_with_ties(self):
        """Test ranking string with ties"""
        ballot_type = BallotType(
            ranking=[["A"], ["B", "C"], ["D"]],
            count=5,
            percentage=10.0
        )
        assert ballot_type.ranking_string == "A > B ~ C > D"
    
    def test_ranking_string_all_tied(self):
        """Test ranking string where all are tied"""
        ballot_type = BallotType(
            ranking=[["A", "B", "C", "D"]],
            count=3,
            percentage=6.0
        )
        assert ballot_type.ranking_string == "A ~ B ~ C ~ D"
    
    def test_empty_ballot_type(self):
        """Test empty ballot type"""
        ballot_type = BallotType(
            ranking=[],
            count=0,
            percentage=0.0
        )
        assert ballot_type.ranking_string == "Empty ballot"


class TestPairwiseComparison:
    """Test PairwiseComparison model"""
    
    def test_valid_pairwise_comparison(self):
        """Test creating a valid pairwise comparison"""
        comparison = PairwiseComparison(
            candidate_a="Python",
            candidate_b="JavaScript",
            a_beats_b=60,
            b_beats_a=40,
            ties=0,
            margin=20
        )
        assert comparison.candidate_a == "Python"
        assert comparison.candidate_b == "JavaScript"
        assert comparison.margin == 20
    
    def test_winner_a_wins(self):
        """Test winner property when A wins"""
        comparison = PairwiseComparison(
            candidate_a="A",
            candidate_b="B",
            a_beats_b=60,
            b_beats_a=40,
            ties=0,
            margin=20
        )
        assert comparison.winner == "A"
    
    def test_winner_b_wins(self):
        """Test winner property when B wins"""
        comparison = PairwiseComparison(
            candidate_a="A",
            candidate_b="B",
            a_beats_b=30,
            b_beats_a=70,
            ties=0,
            margin=-40
        )
        assert comparison.winner == "B"
    
    def test_winner_tie(self):
        """Test winner property when tied"""
        comparison = PairwiseComparison(
            candidate_a="A",
            candidate_b="B",
            a_beats_b=50,
            b_beats_a=50,
            ties=0,
            margin=0
        )
        assert comparison.winner is None
    
    def test_comparison_with_ties(self):
        """Test comparison with tied ballots"""
        comparison = PairwiseComparison(
            candidate_a="A",
            candidate_b="B",
            a_beats_b=40,
            b_beats_a=30,
            ties=30,
            margin=10
        )
        assert comparison.ties == 30
        assert comparison.a_beats_b + comparison.b_beats_a + comparison.ties == 100


class TestHeadToHeadMatrix:
    """Test HeadToHeadMatrix model"""
    
    def test_valid_head_to_head_matrix(self):
        """Test creating a valid head to head matrix"""
        ballot_types = [
            BallotType(ranking=[["A"], ["B"]], count=10, percentage=20.0),
            BallotType(ranking=[["A"], ["B", "C"]], count=5, percentage=10.0)
        ]
        
        matrix = HeadToHeadMatrix(
            candidate_a="A",
            candidate_b="B",
            ballot_types=ballot_types,
            total_count=15
        )
        assert matrix.candidate_a == "A"
        assert matrix.candidate_b == "B"
        assert len(matrix.ballot_types) == 2
        assert matrix.total_count == 15
    
    def test_empty_ballot_types(self):
        """Test head to head matrix with no ballot types"""
        matrix = HeadToHeadMatrix(
            candidate_a="A",
            candidate_b="B",
            ballot_types=[],
            total_count=0
        )
        assert len(matrix.ballot_types) == 0
        assert matrix.total_count == 0


class TestVotingMethodResult:
    """Test VotingMethodResult model"""
    
    def test_single_winner(self):
        """Test voting method result with single winner"""
        result = VotingMethodResult(
            method=VotingMethod.MINIMAX,
            winners=["Python"],
            is_tie=False
        )
        assert result.method == VotingMethod.MINIMAX
        assert result.winners == ["Python"]
        assert not result.is_tie
    
    def test_multiple_winners_tie(self):
        """Test voting method result with tie"""
        result = VotingMethodResult(
            method=VotingMethod.COPELAND_GLOBAL_MINIMAX,
            winners=["Python", "JavaScript"],
            is_tie=True
        )
        assert result.method == VotingMethod.COPELAND_GLOBAL_MINIMAX
        assert len(result.winners) == 2
        assert result.is_tie


class TestDetailedResults:
    """Test DetailedResults model"""
    
    def test_valid_detailed_results(self):
        """Test creating valid detailed results"""
        ballot_types = [
            BallotType(ranking=[["A"], ["B"]], count=10, percentage=50.0),
            BallotType(ranking=[["B"], ["A"]], count=10, percentage=50.0)
        ]
        
        comparisons = [
            PairwiseComparison(
                candidate_a="A",
                candidate_b="B",
                a_beats_b=10,
                b_beats_a=10,
                ties=0,
                margin=0
            )
        ]
        
        voting_results = [
            VotingMethodResult(
                method=VotingMethod.MINIMAX,
                winners=["A", "B"],
                is_tie=True
            )
        ]
        
        results = DetailedResults(
            poll_id="poll_123",
            calculated_at=datetime.utcnow(),
            total_voters=20,
            total_ballots=20,
            num_candidates=2,
            candidates=["A", "B"],
            ballot_types=ballot_types,
            num_bullet_votes=0,
            num_complete_rankings=20,
            num_linear_orders=20,
            pairwise_matrix={"A": {"B": 0}, "B": {"A": 0}},
            pairwise_support_matrix={
                "A": {
                    "B": {"support": 10, "opposed": 10, "margin": 0},
                    "A": {"support": 0, "opposed": 0, "margin": 0}
                },
                "B": {
                    "A": {"support": 10, "opposed": 10, "margin": 0},
                    "B": {"support": 0, "opposed": 0, "margin": 0}
                }
            },
            pairwise_comparisons=comparisons,
            condorcet_winner=None,
            weak_condorcet_winner=None,
            voting_results=voting_results,
            head_to_head_matrices=[]
        )
        
        assert results.poll_id == "poll_123"
        assert results.total_voters == 20
        assert results.condorcet_winner is None
        assert len(results.voting_results) == 1
        # Test support matrix
        assert results.pairwise_support_matrix["A"]["B"]["support"] == 10
        assert results.pairwise_support_matrix["A"]["B"]["opposed"] == 10
        assert results.pairwise_support_matrix["A"]["B"]["margin"] == 0
    
    def test_datetime_serialization(self):
        """Test that datetime is properly serialized"""
        now = datetime.utcnow()
        results = DetailedResults(
            poll_id="poll_123",
            calculated_at=now,
            total_voters=10,
            total_ballots=10,
            num_candidates=2,
            candidates=["A", "B"],
            ballot_types=[],
            num_bullet_votes=0,
            num_complete_rankings=0,
            num_linear_orders=0,
            pairwise_matrix={},
            pairwise_support_matrix={},
            pairwise_comparisons=[],
            condorcet_winner=None,
            weak_condorcet_winner="A",
            voting_results=[],
            head_to_head_matrices=[]
        )
        
        # Convert to dict to see serialization
        results_dict = results.model_dump()
        assert isinstance(results_dict["calculated_at"], str)
        assert results_dict["calculated_at"] == now.isoformat()
    
    def test_with_condorcet_winner(self):
        """Test results with Condorcet winner"""
        results = DetailedResults(
            poll_id="poll_123",
            calculated_at=datetime.utcnow(),
            total_voters=100,
            total_ballots=100,
            num_candidates=3,
            candidates=["A", "B", "C"],
            ballot_types=[],
            num_bullet_votes=5,
            num_complete_rankings=80,
            num_linear_orders=90,
            pairwise_matrix={
                "A": {"B": 20, "C": 30},
                "B": {"A": -20, "C": 10},
                "C": {"A": -30, "B": -10}
            },
            pairwise_support_matrix={
                "A": {
                    "A": {"support": 0, "opposed": 0, "margin": 0},
                    "B": {"support": 60, "opposed": 40, "margin": 20},
                    "C": {"support": 65, "opposed": 35, "margin": 30}
                },
                "B": {
                    "A": {"support": 40, "opposed": 60, "margin": -20},
                    "B": {"support": 0, "opposed": 0, "margin": 0},
                    "C": {"support": 55, "opposed": 45, "margin": 10}
                },
                "C": {
                    "A": {"support": 35, "opposed": 65, "margin": -30},
                    "B": {"support": 45, "opposed": 55, "margin": -10},
                    "C": {"support": 0, "opposed": 0, "margin": 0}
                }
            },
            pairwise_comparisons=[],
            condorcet_winner="A",
            weak_condorcet_winner="A",
            voting_results=[],
            head_to_head_matrices=[]
        )
        
        assert results.condorcet_winner == "A"
        assert results.weak_condorcet_winner == "A"
        assert results.num_bullet_votes == 5
        assert results.num_complete_rankings == 80
        assert results.num_linear_orders == 90
        # Test support matrix for Condorcet winner
        assert results.pairwise_support_matrix["A"]["B"]["support"] == 60
        assert results.pairwise_support_matrix["A"]["C"]["support"] == 65
        assert results.pairwise_support_matrix["A"]["B"]["margin"] == 20
        assert results.pairwise_support_matrix["A"]["C"]["margin"] == 30
    
    def test_support_matrix_structure(self):
        """Test the structure and content of pairwise support matrix"""
        results = DetailedResults(
            poll_id="poll_123",
            calculated_at=datetime.utcnow(),
            total_voters=50,
            total_ballots=50,
            num_candidates=3,
            candidates=["X", "Y", "Z"],
            ballot_types=[],
            num_bullet_votes=0,
            num_complete_rankings=50,
            num_linear_orders=50,
            pairwise_matrix={
                "X": {"Y": 10, "Z": -5},
                "Y": {"X": -10, "Z": 15},
                "Z": {"X": 5, "Y": -15}
            },
            pairwise_support_matrix={
                "X": {
                    "X": {"support": 0, "opposed": 0, "margin": 0},
                    "Y": {"support": 30, "opposed": 20, "margin": 10},
                    "Z": {"support": 22, "opposed": 27, "margin": -5}
                },
                "Y": {
                    "X": {"support": 20, "opposed": 30, "margin": -10},
                    "Y": {"support": 0, "opposed": 0, "margin": 0},
                    "Z": {"support": 32, "opposed": 17, "margin": 15}
                },
                "Z": {
                    "X": {"support": 27, "opposed": 22, "margin": 5},
                    "Y": {"support": 17, "opposed": 32, "margin": -15},
                    "Z": {"support": 0, "opposed": 0, "margin": 0}
                }
            },
            pairwise_comparisons=[],
            condorcet_winner=None,
            weak_condorcet_winner="Y",
            voting_results=[],
            head_to_head_matrices=[]
        )
        
        # Test that support + opposed is consistent
        assert results.pairwise_support_matrix["X"]["Y"]["support"] == 30
        assert results.pairwise_support_matrix["Y"]["X"]["support"] == 20
        assert results.pairwise_support_matrix["X"]["Y"]["opposed"] == 20
        assert results.pairwise_support_matrix["Y"]["X"]["opposed"] == 30
        
        # Test that margins match the pairwise matrix
        assert results.pairwise_support_matrix["X"]["Y"]["margin"] == results.pairwise_matrix["X"]["Y"]
        assert results.pairwise_support_matrix["Y"]["Z"]["margin"] == results.pairwise_matrix["Y"]["Z"]
        
        # Test diagonal entries (same candidate)
        for candidate in results.candidates:
            assert results.pairwise_support_matrix[candidate][candidate]["support"] == 0
            assert results.pairwise_support_matrix[candidate][candidate]["opposed"] == 0
            assert results.pairwise_support_matrix[candidate][candidate]["margin"] == 0


class TestResultsSummary:
    """Test ResultsSummary model"""
    
    def test_valid_results_summary(self):
        """Test creating valid results summary"""
        most_common = BallotType(
            ranking=[["Python"], ["JavaScript"]],
            count=50,
            percentage=50.0
        )
        
        summary = ResultsSummary(
            poll_id="poll_123",
            condorcet_winner="Python",
            weak_condorcet_winner="Python",
            minimax_winners=["Python"],
            copeland_global_minimax_winners=["Python"],
            most_common_ranking=most_common
        )
        
        assert summary.poll_id == "poll_123"
        assert summary.condorcet_winner == "Python"
        assert summary.minimax_winners == ["Python"]
    
    def test_summary_no_condorcet_winner(self):
        """Test summary with no Condorcet winner"""
        most_common = BallotType(
            ranking=[["A"], ["B"], ["C"]],
            count=33,
            percentage=33.0
        )
        
        summary = ResultsSummary(
            poll_id="poll_123",
            condorcet_winner=None,
            weak_condorcet_winner="A",
            minimax_winners=["A"],
            copeland_global_minimax_winners=["A", "B"],
            most_common_ranking=most_common
        )
        
        assert summary.condorcet_winner is None
        assert summary.weak_condorcet_winner == "A"
        assert len(summary.copeland_global_minimax_winners) == 2
    
    def test_summary_multiple_winners(self):
        """Test summary with multiple winners in methods"""
        most_common = BallotType(
            ranking=[["A", "B", "C"]],
            count=100,
            percentage=100.0
        )
        
        summary = ResultsSummary(
            poll_id="poll_123",
            condorcet_winner=None,
            weak_condorcet_winner=None,
            minimax_winners=["A", "B", "C"],
            copeland_global_minimax_winners=["A", "B", "C"],
            most_common_ranking=most_common
        )
        
        assert summary.condorcet_winner is None
        assert summary.weak_condorcet_winner is None
        assert len(summary.minimax_winners) == 3
        assert len(summary.copeland_global_minimax_winners) == 3