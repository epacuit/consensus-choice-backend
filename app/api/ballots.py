from typing import List
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

class BulkImportResponse(BaseModel):
    imported_count: int
    failed_count: int
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
        
        # Process ballots
        result = await ballot_service.bulk_import_ballots(
            poll_id=bulk_request.poll_id,
            ballots=bulk_request.ballots,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return BulkImportResponse(
            imported_count=result["imported_count"],
            failed_count=result["failed_count"],
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
            "message": f"Deleted {delete_result.deleted_count} ballots",
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