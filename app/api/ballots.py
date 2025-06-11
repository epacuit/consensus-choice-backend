from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, Request, Query
from pydantic import BaseModel
from ..models.ballot import Ballot, BallotSubmit, VoteResults
from ..services.ballot_service import BallotService
from ..services.poll_service import PollService
from bson import ObjectId
from ..database import db
import bcrypt

router = APIRouter()
ballot_service = BallotService()
poll_service = PollService()

# Request/Response models for bulk import
class BulkImportRequest(BaseModel):
    poll_id: str
    ballots: List[BallotSubmit]
    # New auth fields
    admin_token: str = None
    password: str = None
    # Optimization options
    use_aggregation: bool = True
    batch_name: Optional[str] = None

class BulkImportResponse(BaseModel):
    imported_count: int
    failed_count: int = 0
    unique_patterns: Optional[int] = None
    batch_id: Optional[str] = None
    message: str

class DeleteBallotsRequest(BaseModel):
    admin_token: str = None
    password: str = None
    poll_id: str = None  # For additional validation

# Helper function to authenticate admin access
async def authenticate_admin(poll_id: str, auth_data: dict) -> bool:
    """Authenticate admin access using new auth methods"""
    # Get the poll
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll {poll_id} not found"
        )
    
    # Method 1: Admin token
    if auth_data.get("admin_token") and poll.admin_token:
        return auth_data.get("admin_token") == poll.admin_token
    
    # Method 2: Password
    if auth_data.get("password") and poll.admin_password_hash:
        return bcrypt.checkpw(
            auth_data.get("password").encode('utf-8'), 
            poll.admin_password_hash.encode('utf-8')
        )
    
    # Method 3: Could add creator email verification here if needed
    
    return False

@router.post("/submit", response_model=Ballot, status_code=status.HTTP_201_CREATED)
async def submit_ballot(ballot: BallotSubmit, request: Request):
    """Submit a ballot for a poll
    
    For private polls, include voter_token in the request.
    For public polls, include browser_fingerprint to prevent duplicates.
    For testing, include test_mode_key with the secret value.
    """
    try:
        # Get client info for logging
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        submitted_ballot = await ballot_service.submit_ballot(
            ballot,
            ip_address=ip_address,
            user_agent=user_agent
        )
        return submitted_ballot
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/bulk-import", response_model=BulkImportResponse)
async def bulk_import_ballots(bulk_request: BulkImportRequest, request: Request):
    """Bulk import ballots for a poll - requires admin authentication"""
    try:
        # Authenticate using new system
        auth_data = {
            "admin_token": bulk_request.admin_token,
            "password": bulk_request.password
        }
        
        is_authenticated = await authenticate_admin(bulk_request.poll_id, auth_data)
        
        if not is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authentication credentials"
            )
        
        # Get client info for logging
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        # Process ballots with aggregation support
        result = await ballot_service.bulk_import_ballots(
            poll_id=bulk_request.poll_id,
            ballots=bulk_request.ballots,
            ip_address=ip_address,
            user_agent=user_agent,
            use_aggregation=bulk_request.use_aggregation,
            batch_name=bulk_request.batch_name
        )
        
        return BulkImportResponse(
            imported_count=result["imported_count"],
            failed_count=result.get("failed_count", 0),
            unique_patterns=result.get("unique_patterns"),
            batch_id=result.get("batch_id"),
            message=result["message"]
        )
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"Unexpected error in bulk import: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )

@router.get("/poll/{poll_id}/results", response_model=VoteResults)
async def get_poll_results(
    poll_id: str,
    include_test: bool = Query(False, description="Include test ballots in results")
):
    """Get live voting results for a poll"""
    try:
        results = await ballot_service.get_live_results(poll_id, include_test)
        return results
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

@router.delete("/poll/{poll_id}/all")
async def delete_all_ballots(poll_id: str, request: DeleteBallotsRequest):
    """Delete all ballots for a poll - requires admin authentication"""
    try:
        # Authenticate using new system
        auth_data = {
            "admin_token": request.admin_token,
            "password": request.password
        }
        
        is_authenticated = await authenticate_admin(poll_id, auth_data)
        
        if not is_authenticated:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid authentication credentials"
            )
        
        # Delete all ballots for this poll
        delete_result = await db.database.ballots.delete_many({"poll_id": poll_id})
        
        # Reset vote count on poll
        update_result = await db.database.polls.update_one(
            {"_id": ObjectId(poll_id)},
            {"$set": {"vote_count": 0, "last_vote_at": None}}
        )
        
        return {
            "deleted_count": delete_result.deleted_count,
            "message": f"Deleted {delete_result.deleted_count} ballot records",
            "poll_updated": update_result.modified_count > 0
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error deleting ballots: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/poll/{poll_id}/import-batches")
async def get_import_batches(
    poll_id: str,
    admin_token: Optional[str] = Query(None, description="Admin authentication token")
):
    """Get list of import batches for a poll"""
    # Verify admin authentication
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll {poll_id} not found"
        )
    
    if not admin_token or poll.admin_token != admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    # Get import batches from ballot service
    batches = await ballot_service.get_import_batches(poll_id)
    
    return {"batches": batches}

@router.get("/poll/{poll_id}/ballot-stats")
async def get_ballot_statistics(
    poll_id: str,
    admin_token: Optional[str] = Query(None, description="Admin authentication token")
):
    """Get statistics about ballot storage efficiency"""
    # Verify admin authentication
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll {poll_id} not found"
        )
    
    if not admin_token or poll.admin_token != admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    # Get ballot statistics from voting calculation service
    from ..services.voting_calculation_service import VotingCalculationService
    voting_calc_service = VotingCalculationService()
    
    stats = await voting_calc_service.get_ballot_summary(poll_id, include_test=False)
    
    # Calculate compression ratio
    if stats["total_ballot_records"] > 0:
        compression_ratio = stats["total_votes"] / stats["total_ballot_records"]
    else:
        compression_ratio = 0
    
    return {
        "poll_id": poll_id,
        "total_votes": stats["total_votes"],
        "total_ballot_records": stats["total_ballot_records"],
        "compression_ratio": round(compression_ratio, 2),
        "individual_ballots": stats["individual_ballots"],
        "aggregated_ballots": stats["aggregated_ballots"],
        "average_votes_per_record": round(stats["avg_votes_per_record"], 2),
        "max_votes_in_single_record": stats["max_count"],
        "storage_efficiency": f"{round((1 - stats['total_ballot_records']/stats['total_votes']) * 100, 1)}%" if stats["total_votes"] > 0 else "0%"
    }