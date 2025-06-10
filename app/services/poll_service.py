import secrets
from datetime import datetime
from typing import List, Optional, Dict
from bson import ObjectId
from ..database import db
from ..models.poll import (
    Poll, PollCreate, PollUpdate, PollOption, 
    PollSettings, PollVoter, PollOptionCreate, PollOptionUpdate
)

class PollService:
    @property
    def collection(self):
        return db.database.polls

    async def create_poll(self, poll_data: PollCreate, auth_data: Optional[Dict] = None) -> Poll:
        # Convert options to PollOption objects
        poll_options = []
        for idx, option_data in enumerate(poll_data.options):
            if isinstance(option_data, str):
                # Backward compatibility: string options
                poll_options.append(PollOption(
                    id=str(ObjectId()),
                    name=option_data,
                    description=None,
                    image_url=None
                ))
            elif isinstance(option_data, PollOptionCreate):
                # New format with optional description and image
                poll_options.append(PollOption(
                    id=str(ObjectId()),
                    name=option_data.name,
                    description=option_data.description,
                    image_url=option_data.image_url
                ))
        
        # Create voters list for private polls
        voters = []
        if poll_data.is_private and poll_data.voter_emails:
            for email in poll_data.voter_emails:
                voters.append(PollVoter(
                    email=email,
                    token=secrets.token_urlsafe(16)
                ).model_dump())
        
        # Extract authentication data if provided
        admin_password_hash = None
        creator_email = None
        admin_token = None
        creator_id = None
        
        if auth_data:
            admin_password_hash = auth_data.get("admin_password_hash")
            creator_email = auth_data.get("creator_email")
            admin_token = auth_data.get("admin_token")
            # If you have user authentication, you could set creator_id from session/JWT
            # creator_id = auth_data.get("user_id")
        
        # Prepare document for MongoDB
        poll_doc = {
            "title": poll_data.title,
            "description": poll_data.description,
            "options": [opt.model_dump() for opt in poll_options],
            "is_private": poll_data.is_private,
            "voters": voters,
            "settings": (poll_data.settings or PollSettings()).model_dump(),
            "closing_datetime": poll_data.closing_datetime,
            "is_completed": False,
            "creator_id": creator_id,
            "admin_password_hash": admin_password_hash,
            "creator_email": creator_email,
            "admin_token": admin_token,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "tags": poll_data.tags,
            "vote_count": 0,
            "last_vote_at": None
        }
        
        # Insert into database
        result = await self.collection.insert_one(poll_doc)
        
        # Retrieve and return the created poll
        created_poll = await self.collection.find_one({"_id": result.inserted_id})
        return self._doc_to_poll(created_poll)

    async def get_poll(self, poll_id: str) -> Optional[Poll]:
        if not ObjectId.is_valid(poll_id):
            return None
            
        poll_doc = await self.collection.find_one({"_id": ObjectId(poll_id)})
        if not poll_doc:
            return None
            
        return self._doc_to_poll(poll_doc)

    async def list_polls(self, skip: int = 0, limit: int = 20) -> List[Poll]:
        cursor = self.collection.find().skip(skip).limit(limit).sort("created_at", -1)
        polls = await cursor.to_list(length=limit)
        
        return [self._doc_to_poll(poll) for poll in polls]

    async def update_poll(self, poll_id: str, poll_update: PollUpdate) -> Optional[Poll]:
        if not ObjectId.is_valid(poll_id):
            return None
        
        # Get the current poll to check if it exists
        current_poll = await self.get_poll(poll_id)
        if not current_poll:
            return None
            
        update_data = poll_update.model_dump(exclude_unset=True, exclude_none=True)
        
        # Handle poll type change (public <-> private)
        if 'is_private' in update_data:
            poll_doc = await self.collection.find_one({"_id": ObjectId(poll_id)})
            current_is_private = poll_doc.get('is_private', False)
            new_is_private = update_data['is_private']
            
            if current_is_private != new_is_private:
                if new_is_private:
                    # Changing from public to private
                    # Initialize voters list if provided
                    if 'voter_emails' in update_data:
                        voters = []
                        for email in update_data['voter_emails']:
                            voters.append({
                                "email": email.strip().lower(),
                                "token": secrets.token_urlsafe(16),
                                "has_voted": False,
                                "invited_at": datetime.utcnow(),
                                "voted_at": None
                            })
                        update_data['voters'] = voters
                        del update_data['voter_emails']  # Remove from update_data as it's not a direct field
                    else:
                        update_data['voters'] = []
                else:
                    # Changing from private to public
                    # Clear voters list
                    update_data['voters'] = []
                    
                    # Reset certain settings for public polls
                    if 'settings' not in update_data:
                        update_data['settings'] = {}
                    update_data['settings']['results_visibility'] = 'public'
        
        # Handle voter_emails update for existing private polls
        elif 'voter_emails' in update_data and current_poll.is_private:
            # This is just updating voters for an already private poll
            poll_doc = await self.collection.find_one({"_id": ObjectId(poll_id)})
            existing_voters = poll_doc.get('voters', [])
            existing_emails = {v['email'] for v in existing_voters}
            
            # Build new voters list
            new_voters = []
            for email in update_data['voter_emails']:
                email = email.strip().lower()
                # Keep existing voter if they already exist
                existing_voter = next((v for v in existing_voters if v['email'] == email), None)
                if existing_voter:
                    new_voters.append(existing_voter)
                else:
                    # Create new voter
                    new_voters.append({
                        "email": email,
                        "token": secrets.token_urlsafe(16),
                        "has_voted": False,
                        "invited_at": datetime.utcnow(),
                        "voted_at": None
                    })
            
            update_data['voters'] = new_voters
            del update_data['voter_emails']  # Remove from update_data as it's not a direct field
        
        # Handle options update specially
        if 'options' in update_data and update_data['options'] is not None:
            # Convert PollOptionUpdate objects to proper format
            updated_options = []
            for opt_update in update_data['options']:
                if opt_update.get('id'):
                    # Update existing option
                    updated_options.append({
                        'id': opt_update['id'],
                        'name': opt_update['name'],
                        'description': opt_update.get('description'),
                        'image_url': opt_update.get('image_url'),
                        'is_write_in': opt_update.get('is_write_in', False)
                    })
                else:
                    # Create new option with generated ID
                    updated_options.append({
                        'id': str(ObjectId()),
                        'name': opt_update['name'],
                        'description': opt_update.get('description'),
                        'image_url': opt_update.get('image_url'),
                        'is_write_in': False
                    })
            update_data['options'] = updated_options
        
        # Handle settings update
        if 'settings' in update_data and update_data['settings'] is not None:
            # Ensure all settings fields are included
            update_data['settings'] = update_data['settings']
        
        if not update_data:
            return await self.get_poll(poll_id)
            
        update_data["updated_at"] = datetime.utcnow()
        
        result = await self.collection.update_one(
            {"_id": ObjectId(poll_id)},
            {"$set": update_data}
        )
        
        if result.modified_count:
            return await self.get_poll(poll_id)
        return None

    async def delete_poll(self, poll_id: str) -> bool:
        if not ObjectId.is_valid(poll_id):
            return False
            
        result = await self.collection.delete_one({"_id": ObjectId(poll_id)})
        return result.deleted_count > 0

    def _doc_to_poll(self, doc: dict) -> Poll:
        from datetime import timezone
        
        # Calculate derived fields
        is_completed = doc.get("is_completed", False)
        closing_datetime = doc.get("closing_datetime")
        
        # Convert closing_datetime to datetime object if it's a string
        if closing_datetime and isinstance(closing_datetime, str):
            try:
                # Parse ISO format string to datetime
                closing_datetime = datetime.fromisoformat(closing_datetime.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                # If parsing fails, set to None
                closing_datetime = None
        
        # Make current time timezone-aware (UTC)
        current_time = datetime.utcnow().replace(tzinfo=timezone.utc)
        
        has_closed = is_completed
        time_remaining = None
        
        if closing_datetime and not is_completed:
            # Ensure closing_datetime is timezone-aware
            if closing_datetime.tzinfo is None:
                closing_datetime = closing_datetime.replace(tzinfo=timezone.utc)
                
            has_closed = current_time > closing_datetime
            
            if not has_closed:
                remaining = closing_datetime - current_time
                if remaining.total_seconds() > 0:
                    days = remaining.days
                    hours, remainder = divmod(remaining.seconds, 3600)
                    minutes, _ = divmod(remainder, 60)
                    
                    if days > 0:
                        time_remaining = f"{days}d {hours}h"
                    elif hours > 0:
                        time_remaining = f"{hours}h {minutes}m"
                    else:
                        time_remaining = f"{minutes}m"
        
        # Convert document to Poll model
        return Poll(
            id=str(doc["_id"]),
            title=doc["title"],
            description=doc.get("description"),
            options=[PollOption(**opt) for opt in doc["options"]],
            is_private=doc["is_private"],
            settings=PollSettings(**doc["settings"]),
            closing_datetime=closing_datetime,
            is_completed=is_completed,
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            tags=doc.get("tags", []),
            vote_count=doc.get("vote_count", 0),
            creator_id=doc.get("creator_id"),
            admin_password_hash=doc.get("admin_password_hash"),
            creator_email=doc.get("creator_email"),
            admin_token=doc.get("admin_token"),
            is_active=not has_closed,
            has_closed=has_closed,
            time_remaining=time_remaining
        )