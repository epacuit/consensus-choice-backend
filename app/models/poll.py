from datetime import datetime
from typing import Optional, List, Dict, Union
from pydantic import BaseModel, Field, ConfigDict, field_serializer, field_validator

from enum import Enum

class PollVisibility(str, Enum):
    PUBLIC = "public"
    VOTERS_ONLY = "voters"
    CREATOR_ONLY = "creator"
    CUSTOM = "custom"

class PollOption(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_write_in: bool = False
    
class PollOptionCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    image_url: Optional[str] = None

class PollOptionUpdate(BaseModel):
    id: Optional[str] = None  # If provided, update existing; if not, create new
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    image_url: Optional[str] = None

class PollSettings(BaseModel):
    # Voting configuration
    allow_ties: bool = True
    require_complete_ranking: bool = False
    randomize_options: bool = False  # Changed from True to False
    allow_write_in: bool = False
    
    # Results configuration
    show_detailed_results: bool = True
    show_rankings: bool = True
    anonymize_voters: bool = True
    
    # Visibility settings
    results_visibility: PollVisibility = PollVisibility.PUBLIC
    can_view_before_close: bool = False

class PollVoter(BaseModel):
    email: str
    token: str
    has_voted: bool = False
    invited_at: datetime = Field(default_factory=datetime.utcnow)
    voted_at: Optional[datetime] = None
    
    model_config = ConfigDict()
    
    @field_serializer('invited_at', 'voted_at')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None

# Request/Response models
class PollCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    options: List[Union[str, PollOptionCreate, dict]] = Field(..., min_length=2)  # Accept strings, objects, or dicts
    is_private: bool = False
    voter_emails: List[str] = Field(default_factory=list)
    settings: Optional[PollSettings] = None
    closing_datetime: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list)
    
    # New authentication fields
    admin_password: Optional[str] = None  # Plain password from user
    creator_email: Optional[str] = None   # Optional email for management
    
    model_config = ConfigDict()
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Title cannot be empty')
        return v
    
    @field_validator('options')
    @classmethod
    def validate_options(cls, v: List[Union[str, PollOptionCreate, dict]]) -> List[PollOptionCreate]:
        # Normalize all options to PollOptionCreate objects
        normalized = []
        for opt in v:
            if isinstance(opt, str):
                # Backward compatibility: string -> PollOptionCreate
                opt_str = opt.strip()
                if opt_str:
                    normalized.append(PollOptionCreate(name=opt_str))
            elif isinstance(opt, dict):
                # Dict -> PollOptionCreate
                name = opt.get('name', '').strip()
                if name:
                    normalized.append(PollOptionCreate(
                        name=name,
                        description=opt.get('description'),
                        image_url=opt.get('image_url')
                    ))
            elif isinstance(opt, PollOptionCreate):
                # Already PollOptionCreate
                if opt.name.strip():
                    normalized.append(opt)
        
        if len(normalized) < 2:
            raise ValueError('At least 2 non-empty options required')
        return normalized
    
    @field_validator('creator_email')
    @classmethod
    def validate_creator_email(cls, v: Optional[str]) -> Optional[str]:
        if v:
            v = v.strip().lower()
            # Basic email validation
            if '@' not in v or '.' not in v:
                raise ValueError('Invalid email format')
        return v
    
    @field_serializer('closing_datetime')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None

class PollUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    closing_datetime: Optional[datetime] = None
    is_completed: Optional[bool] = None
    is_private: Optional[bool] = None  # Add this to support poll type changes
    voter_emails: Optional[List[str]] = None  # Add this for voter updates
    tags: Optional[List[str]] = None
    options: Optional[List[PollOptionUpdate]] = None
    settings: Optional[PollSettings] = None
    
    model_config = ConfigDict()
    
    @field_validator('options')
    @classmethod
    def validate_options(cls, v: Optional[List[PollOptionUpdate]]) -> Optional[List[PollOptionUpdate]]:
        if v is None:
            return None
        
        # Ensure at least 2 options if updating
        non_empty = [opt for opt in v if opt.name.strip()]
        if len(non_empty) < 2:
            raise ValueError('At least 2 non-empty options required')
        return non_empty
    
    @field_validator('voter_emails')
    @classmethod
    def validate_voter_emails(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        
        # Validate and normalize emails
        validated = []
        for email in v:
            email = email.strip().lower()
            if email:
                # Basic email validation
                if '@' not in email or '.' not in email:
                    raise ValueError(f'Invalid email format: {email}')
                validated.append(email)
        
        return validated
    
    @field_serializer('closing_datetime')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None
    
class Poll(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    options: List[PollOption]
    is_private: bool
    settings: PollSettings
    closing_datetime: Optional[datetime] = None
    is_completed: bool = False
    created_at: datetime
    updated_at: datetime
    tags: List[str] = Field(default_factory=list)
    vote_count: int = 0
    creator_id: Optional[str] = None
    
    # New authentication fields
    admin_password_hash: Optional[str] = None  # Hashed password for admin access
    creator_email: Optional[str] = None        # Email of poll creator
    admin_token: Optional[str] = None           # Unique token for direct admin access
    
    # Computed fields
    is_active: bool = True
    has_closed: bool = False
    time_remaining: Optional[str] = None
    
    model_config = ConfigDict()
    
    @field_serializer('created_at', 'updated_at', 'closing_datetime')
    def serialize_datetime(self, dt: datetime, _info):
        return dt.isoformat() if dt else None