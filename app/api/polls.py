from typing import List, Optional
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os
import uuid
from pathlib import Path
from bson import ObjectId
from ..models.poll import Poll, PollCreate, PollUpdate, PollOption
from ..services.poll_service import PollService
from datetime import datetime
from ..database import db
import bcrypt
import secrets

router = APIRouter()
poll_service = PollService()

# Create uploads directory if it doesn't exist
UPLOAD_DIR = Path("uploads/poll_images")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Authentication request model
class AuthenticateAdminRequest(BaseModel):
    poll_id: str
    password: str = None
    admin_token: str = None

class AuthenticateAdminResponse(BaseModel):
    authenticated: bool
    auth_method: str
    poll_id: str
    poll_title: str


class VoterInfo(BaseModel):
    email: str
    token: str
    has_voted: bool
    invited_at: str
    voted_at: Optional[str] = None

class GetVotersResponse(BaseModel):
    voters: List[VoterInfo]
    total_count: int

class AddVotersRequest(BaseModel):
    poll_id: str
    admin_token: Optional[str] = None
    emails: List[str]

class RemoveVoterRequest(BaseModel):
    poll_id: str
    admin_token: Optional[str] = None

class RegenerateTokenRequest(BaseModel):
    poll_id: str
    admin_token: Optional[str] = None
    email: str

class RegenerateTokenResponse(BaseModel):
    email: str
    token: str

# Authentication endpoints
@router.post("/authenticate-admin", response_model=AuthenticateAdminResponse)
async def authenticate_admin(auth_request: AuthenticateAdminRequest):
    """Authenticate admin access to a poll"""
    poll_id = auth_request.poll_id
    password = auth_request.password
    admin_token = auth_request.admin_token
    
    if not poll_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Poll ID is required"
        )
    
    # Get poll
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    # Check authentication methods
    authenticated = False
    auth_method = None
    
    # Method 1: Admin token (direct link)
    if admin_token and hasattr(poll, 'admin_token') and poll.admin_token == admin_token:
        authenticated = True
        auth_method = "token"
    
    # Method 2: Password
    elif password and hasattr(poll, 'admin_password_hash') and poll.admin_password_hash:
        try:
            if bcrypt.checkpw(password.encode('utf-8'), poll.admin_password_hash.encode('utf-8')):
                authenticated = True
                auth_method = "password"
        except Exception as e:
            print(f"Password check error: {e}")
            # Password check failed
            pass
    
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    return AuthenticateAdminResponse(
        authenticated=True,
        auth_method=auth_method,
        poll_id=poll_id,
        poll_title=poll.title
    )

@router.post("/upload-image")
async def upload_poll_image(request: Request, file: UploadFile = File(...)):
    """Upload an image for a poll option"""
    # Validate file type
    if not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image"
        )
    
    # Validate file size (5MB limit)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size must be less than 5MB"
        )
    
    # Generate unique filename
    file_extension = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as f:
        f.write(contents)
    
    # Return the FULL URL
    base_url = str(request.base_url).rstrip('/')
    image_url = f"{base_url}/uploads/poll_images/{unique_filename}"
    
    return JSONResponse(content={"image_url": image_url})

@router.post("/", response_model=Poll, status_code=status.HTTP_201_CREATED)
async def create_poll(poll: PollCreate):
    """Create a new poll with optional authentication"""
    # Generate admin token
    admin_token = secrets.token_urlsafe(32)
    
    # Hash password if provided
    admin_password_hash = None
    if poll.admin_password:
        admin_password_hash = bcrypt.hashpw(
            poll.admin_password.encode('utf-8'), 
            bcrypt.gensalt()
        ).decode('utf-8')
    
    # Pass authentication data to service
    auth_data = {
        "admin_password_hash": admin_password_hash,
        "creator_email": poll.creator_email,
        "admin_token": admin_token
    }
    
    return await poll_service.create_poll(poll, auth_data)

@router.get("/{poll_id}", response_model=Poll)
async def get_poll(poll_id: str):
    """Get a specific poll by ID"""
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    return poll

@router.get("/", response_model=List[Poll])
async def list_polls(skip: int = 0, limit: int = 20):
    """List polls with pagination"""
    return await poll_service.list_polls(skip=skip, limit=limit)

@router.put("/{poll_id}", response_model=Poll)
async def update_poll(poll_id: str, poll_update: PollUpdate):
    """Update a poll"""
    updated_poll = await poll_service.update_poll(poll_id, poll_update)
    if not updated_poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    return updated_poll

@router.delete("/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_poll(poll_id: str):
    """Delete a poll"""
    success = await poll_service.delete_poll(poll_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )

# Write-in endpoints
@router.post("/{poll_id}/write-ins", response_model=PollOption)
async def add_write_in_candidate(poll_id: str, write_in: dict):
    """Add a write-in candidate to a poll"""
    # Validate poll exists and allows write-ins
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    if not poll.settings.allow_write_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This poll does not allow write-in candidates"
        )
    
    # Validate write-in data
    name = write_in.get("name", "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Write-in candidate name is required"
        )
    
    # Check if candidate already exists
    existing_names = [opt.name.lower() for opt in poll.options]
    if name.lower() in existing_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A candidate with this name already exists"
        )
    
    # Create new option
    new_option = PollOption(
        id=str(ObjectId()),
        name=name,
        description=write_in.get("description"),
        image_url=write_in.get("image_url"),
        is_write_in=True  # Mark as write-in
    )
    
    # Add to poll
    result = await db.database.polls.update_one(
        {"_id": ObjectId(poll_id)},
        {"$push": {"options": new_option.model_dump()}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add write-in candidate"
        )
    
    return new_option

@router.get("/{poll_id}/write-ins", response_model=List[PollOption])
async def get_write_in_candidates(poll_id: str):
    """Get all write-in candidates for a poll"""
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    # Filter and return only write-in candidates
    write_ins = [opt for opt in poll.options if getattr(opt, 'is_write_in', False)]
    return write_ins

# Get polls by creator email
@router.get("/creator/{email}", response_model=List[Poll])
async def get_polls_by_creator(email: str, skip: int = 0, limit: int = 20):
    """Get all polls created by a specific email"""
    email = email.strip().lower()
    
    polls = await db.database.polls.find(
        {"creator_email": email}
    ).skip(skip).limit(limit).to_list(length=limit)
    
    return [poll_service._doc_to_poll(doc) for doc in polls]


# Voter Management Endpoints
@router.get("/{poll_id}/voters", response_model=GetVotersResponse)
async def get_poll_voters(poll_id: str, admin_token: Optional[str] = None):
    """Get all voters for a private poll (requires admin authentication)"""
    
    # Verify poll exists and is private
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    if not poll.is_private:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for private polls"
        )
    
    # Verify admin authentication
    if not admin_token or poll.admin_token != admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    # Get voters from database
    poll_doc = await db.database.polls.find_one({"_id": ObjectId(poll_id)})
    voters_data = poll_doc.get("voters", [])
    
    # Convert to response format
    voters = []
    for voter in voters_data:
        # Handle invited_at field - it might be a datetime object or already a string
        invited_at = voter.get("invited_at")
        if invited_at:
            if hasattr(invited_at, 'isoformat'):
                invited_at_str = invited_at.isoformat()
            else:
                invited_at_str = str(invited_at)
        else:
            invited_at_str = datetime.utcnow().isoformat()
        
        # Handle voted_at field similarly
        voted_at = voter.get("voted_at")
        voted_at_str = None
        if voted_at:
            if hasattr(voted_at, 'isoformat'):
                voted_at_str = voted_at.isoformat()
            else:
                voted_at_str = str(voted_at)
        
        voters.append(VoterInfo(
            email=voter["email"],
            token=voter["token"],
            has_voted=voter.get("has_voted", False),
            invited_at=invited_at_str,
            voted_at=voted_at_str
        ))
    
    return GetVotersResponse(
        voters=voters,
        total_count=len(voters)
    )

@router.post("/{poll_id}/voters")
async def add_voters(poll_id: str, request: AddVotersRequest):
    """Add new voters to a private poll"""
    
    # Verify poll exists and is private
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    if not poll.is_private:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for private polls"
        )
    
    # Verify admin authentication
    if not request.admin_token or poll.admin_token != request.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    # Get existing voters
    poll_doc = await db.database.polls.find_one({"_id": ObjectId(poll_id)})
    existing_voters = poll_doc.get("voters", [])
    existing_emails = {v["email"] for v in existing_voters}
    
    # Create new voter entries
    new_voters = []
    for email in request.emails:
        email = email.strip().lower()
        if email and email not in existing_emails:
            new_voters.append({
                "email": email,
                "token": secrets.token_urlsafe(16),
                "has_voted": False,
                "invited_at": datetime.utcnow(),
                "voted_at": None
            })
    
    if new_voters:
        # Add new voters to the poll
        result = await db.database.polls.update_one(
            {"_id": ObjectId(poll_id)},
            {"$push": {"voters": {"$each": new_voters}}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add voters"
            )
    
    return {"message": f"Added {len(new_voters)} voters", "count": len(new_voters)}

@router.delete("/{poll_id}/voters/{email}")
async def remove_voter(poll_id: str, email: str, request: RemoveVoterRequest):
    """Remove a voter from a private poll"""
    
    # Verify poll exists and is private
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    if not poll.is_private:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for private polls"
        )
    
    # Verify admin authentication
    if not request.admin_token or poll.admin_token != request.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    email = email.strip().lower()
    
    # Remove the voter
    result = await db.database.polls.update_one(
        {"_id": ObjectId(poll_id)},
        {"$pull": {"voters": {"email": email}}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voter {email} not found"
        )
    
    # Also remove any ballots from this voter
    await db.database.ballots.delete_many({
        "poll_id": poll_id,
        "voter_token": {"$exists": True}  # You might need to adjust based on how you store voter info in ballots
    })
    
    return {"message": f"Removed voter {email}"}

@router.post("/{poll_id}/regenerate-token", response_model=RegenerateTokenResponse)
async def regenerate_voter_token(poll_id: str, request: RegenerateTokenRequest):
    """Regenerate a voting token for a specific voter"""
    
    # Verify poll exists and is private
    poll = await poll_service.get_poll(poll_id)
    if not poll:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Poll with ID {poll_id} not found"
        )
    
    if not poll.is_private:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint is only for private polls"
        )
    
    # Verify admin authentication
    if not request.admin_token or poll.admin_token != request.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    
    email = request.email.strip().lower()
    
    # Get current voters
    poll_doc = await db.database.polls.find_one({"_id": ObjectId(poll_id)})
    voters = poll_doc.get("voters", [])
    
    # Find the voter
    voter_index = None
    for i, voter in enumerate(voters):
        if voter["email"] == email:
            voter_index = i
            break
    
    if voter_index is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Voter {email} not found"
        )
    
    # Check if voter has already voted
    if voters[voter_index].get("has_voted", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot regenerate token for a voter who has already voted"
        )
    
    # Generate new token
    new_token = secrets.token_urlsafe(16)
    
    # Update the voter's token
    result = await db.database.polls.update_one(
        {
            "_id": ObjectId(poll_id),
            "voters.email": email
        },
        {
            "$set": {
                "voters.$.token": new_token,
                "voters.$.invited_at": datetime.utcnow()
            }
        }
    )
    
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate token"
        )
    
    return RegenerateTokenResponse(
        email=email,
        token=new_token
    )
