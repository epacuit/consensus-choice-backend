from typing import Optional
from fastapi import APIRouter, HTTPException, status, Query

from ..models.results import DetailedResults
from ..services.results_service import ResultsService

router = APIRouter()
results_service = ResultsService()


@router.get("/poll/{poll_id}/detailed", response_model=DetailedResults)
async def get_detailed_results(
    poll_id: str,
    include_test: bool = Query(False, description="Include test ballots in results")
):
    """Get detailed voting results for a poll
    
    This calculates:
    - Pairwise margin matrix
    - Condorcet winner (if exists)
    - Minimax winner(s)
    - Copeland Global Minimax winner(s)
    - Ballot type analysis
    - Number of bullet votes, complete rankings, linear orders
    - Head-to-head matrices showing which ballot types rank A over B
    """
    try:
        results = await results_service.calculate_detailed_results(poll_id, include_test)
        return results
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
