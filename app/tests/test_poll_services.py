"""
Refactored tests for PollService - easier to extend.
"""

import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timedelta
from contextlib import contextmanager


class TestPollService:
    """Test PollService with reusable fixtures."""
    
    @contextmanager
    def mock_poll_service(self):
        """Context manager for mocking PollService with database."""
        # Clear any cached imports
        if 'app.services.poll_service' in sys.modules:
            del sys.modules['app.services.poll_service']
        
        with patch('app.database.db') as mock_db:
            # Setup the mock database
            mock_collection = MagicMock()
            mock_db.database = MagicMock()
            mock_db.database.polls = mock_collection
            
            # Import after mocking
            from app.services.poll_service import PollService
            
            # Yield the service and collection for test use
            yield PollService(), mock_collection
    
    def create_poll_doc(self, **overrides):
        """Helper to create a poll document with defaults."""
        poll_id = overrides.get('_id', ObjectId())
        base_doc = {
            "_id": poll_id,
            "title": "Test Poll",
            "description": "Test Description",
            "options": [
                {"id": "1", "name": "Option A", "description": None, "image_url": None},
                {"id": "2", "name": "Option B", "description": None, "image_url": None}
            ],
            "is_private": False,
            "voters": [],
            "settings": {
                "allow_multiple_votes": False,
                "show_results_before_closing": True
            },
            "is_completed": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "vote_count": 0,
            "tags": []
        }
        base_doc.update(overrides)
        return base_doc
    
    @pytest.mark.asyncio
    async def test_create_poll(self):
        """Test creating a poll."""
        with self.mock_poll_service() as (service, mock_collection):
            from app.models.poll import PollCreate
            
            # Setup mocks
            mock_id = ObjectId()
            mock_collection.insert_one = AsyncMock(
                return_value=MagicMock(inserted_id=mock_id)
            )
            mock_collection.find_one = AsyncMock(
                return_value=self.create_poll_doc(_id=mock_id, tags=["test", "poll"])
            )
            
            # Execute
            poll_data = PollCreate(
                title="Test Poll",
                description="Test Description",
                options=["Option A", "Option B"],
                is_private=False,
                tags=["test", "poll"]
            )
            result = await service.create_poll(poll_data)
            
            # Assert
            assert result.title == "Test Poll"
            assert result.description == "Test Description"
            assert len(result.options) == 2
            mock_collection.insert_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_poll(self):
        """Test getting a poll by ID."""
        with self.mock_poll_service() as (service, mock_collection):
            # Setup
            poll_obj_id = ObjectId()
            poll_id = str(poll_obj_id)
            
            mock_collection.find_one = AsyncMock(
                return_value=self.create_poll_doc(
                    _id=poll_obj_id,
                    title="Retrieved Poll",
                    description="Test",
                    options=[],
                    vote_count=5
                )
            )
            
            # Execute
            result = await service.get_poll(poll_id)
            
            # Assert
            assert result is not None
            assert result.id == poll_id
            assert result.title == "Retrieved Poll"
            assert result.vote_count == 5
    
    @pytest.mark.asyncio
    async def test_get_poll_not_found(self):
        """Test getting a non-existent poll."""
        with self.mock_poll_service() as (service, mock_collection):
            mock_collection.find_one = AsyncMock(return_value=None)
            
            result = await service.get_poll(str(ObjectId()))
            assert result is None
    
    @pytest.mark.asyncio
    async def test_delete_poll(self):
        """Test deleting a poll."""
        with self.mock_poll_service() as (service, mock_collection):
            poll_id = str(ObjectId())
            mock_collection.delete_one = AsyncMock(
                return_value=MagicMock(deleted_count=1)
            )
            
            result = await service.delete_poll(poll_id)
            
            assert result is True
            mock_collection.delete_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_poll(self):
        """Test updating a poll."""
        with self.mock_poll_service() as (service, mock_collection):
            from app.models.poll import PollUpdate
            
            poll_obj_id = ObjectId()
            poll_id = str(poll_obj_id)
            
            # Mock the update
            mock_collection.update_one = AsyncMock(
                return_value=MagicMock(modified_count=1)
            )
            
            # Mock the retrieval after update
            mock_collection.find_one = AsyncMock(
                return_value=self.create_poll_doc(
                    _id=poll_obj_id,
                    title="Updated Title",
                    description="Updated Description",
                    is_completed=True
                )
            )
            
            # Execute
            update_data = PollUpdate(
                title="Updated Title",
                description="Updated Description",
                is_completed=True
            )
            result = await service.update_poll(poll_id, update_data)
            
            # Assert
            assert result.title == "Updated Title"
            assert result.description == "Updated Description"
            assert result.is_completed is True
    
    @pytest.mark.asyncio
    async def test_list_polls(self):
        """Test listing polls."""
        with self.mock_poll_service() as (service, mock_collection):
            # Mock cursor chain
            mock_cursor = MagicMock()
            mock_cursor.skip = MagicMock(return_value=mock_cursor)
            mock_cursor.limit = MagicMock(return_value=mock_cursor)
            mock_cursor.sort = MagicMock(return_value=mock_cursor)
            mock_cursor.to_list = AsyncMock(return_value=[
                self.create_poll_doc(title="Poll 1", vote_count=10),
                self.create_poll_doc(title="Poll 2", vote_count=5, is_private=True)
            ])
            
            mock_collection.find = MagicMock(return_value=mock_cursor)
            
            # Execute
            results = await service.list_polls(skip=0, limit=10)
            
            # Assert
            assert len(results) == 2
            assert results[0].title == "Poll 1"
            assert results[1].is_private is True
    
    @pytest.mark.asyncio
    async def test_create_private_poll_with_voters(self):
        """Test creating a private poll with voter emails."""
        with self.mock_poll_service() as (service, mock_collection):
            from app.models.poll import PollCreate
            
            # Capture what gets inserted
            inserted_doc = None
            async def capture_insert(doc):
                nonlocal inserted_doc
                inserted_doc = doc
                return MagicMock(inserted_id=ObjectId())
            
            mock_collection.insert_one = AsyncMock(side_effect=capture_insert)
            mock_collection.find_one = AsyncMock(
                return_value=self.create_poll_doc(is_private=True)
            )
            
            # Execute
            poll_data = PollCreate(
                title="Private Poll",
                options=["Yes", "No"],
                is_private=True,
                voter_emails=["alice@example.com", "bob@example.com"]
            )
            await service.create_poll(poll_data)
            
            # Assert
            assert inserted_doc["is_private"] is True
            assert len(inserted_doc["voters"]) == 2
            emails = {v["email"] for v in inserted_doc["voters"]}
            assert emails == {"alice@example.com", "bob@example.com"}
            # Check unique tokens
            tokens = [v["token"] for v in inserted_doc["voters"]]
            assert len(tokens) == len(set(tokens))
