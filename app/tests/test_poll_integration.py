"""
Integration tests with real database - THIS IS CRITICAL!

Make sure you have pytest-asyncio installed:
pip install pytest-asyncio

To run these tests:
MONGODB_DB=betterchoices_test pytest app/tests/test_integration.py -v

Or set the test database in your .env.test file.
"""

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import patch
from bson import ObjectId
from datetime import datetime
import os

# IMPORTANT: Set test database BEFORE any imports that use it
if "MONGODB_DB" not in os.environ:
    os.environ["MONGODB_DB"] = "betterchoices_test"

# Now import after env is set
from app.database import db, connect_db, close_db
from app.services.poll_service import PollService
from app.models.poll import PollCreate, PollUpdate


@pytest_asyncio.fixture(scope="function") 
async def setup_database():
    """Setup and teardown test database."""
    # Connect to the test database
    await connect_db()
    
    yield
    
    # Clean up test data after each test
    try:
        await db.database.polls.delete_many({})
    except Exception as e:
        print(f"Cleanup error: {e}")
    
    # Close connection after test
    await close_db()


@pytest_asyncio.fixture
async def poll_service(setup_database):
    """Get real poll service."""
    return PollService()


class TestIntegration:
    """Test real database operations."""
    
    @pytest.mark.asyncio
    async def test_create_and_retrieve_poll(self, poll_service):
        """Test creating and retrieving a poll with real DB."""
        # Create poll
        poll_data = PollCreate(
            title="Integration Test Poll",
            description="Testing with real database",
            options=["Yes", "No", "Maybe"],
            tags=["test", "integration"]
        )
        
        created_poll = await poll_service.create_poll(poll_data)
        
        # Verify it was created
        assert created_poll.id is not None
        assert created_poll.title == "Integration Test Poll"
        assert len(created_poll.options) == 3
        
        # Retrieve it
        retrieved_poll = await poll_service.get_poll(created_poll.id)
        
        # Verify retrieval
        assert retrieved_poll is not None
        assert retrieved_poll.id == created_poll.id
        assert retrieved_poll.title == created_poll.title
        
        # Clean up
        await poll_service.delete_poll(created_poll.id)
    
    @pytest.mark.asyncio
    async def test_concurrent_poll_creation(self, poll_service):
        """Test creating multiple polls concurrently."""
        # Create 10 polls at the same time
        tasks = []
        for i in range(10):
            poll_data = PollCreate(
                title=f"Concurrent Poll {i}",
                options=["A", "B"]
            )
            tasks.append(poll_service.create_poll(poll_data))
        
        # Execute concurrently
        results = await asyncio.gather(*tasks)
        
        # Verify all were created
        assert len(results) == 10
        assert all(poll.id is not None for poll in results)
        
        # Clean up
        for poll in results:
            await poll_service.delete_poll(poll.id)
    
    @pytest.mark.asyncio
    async def test_update_with_concurrent_reads(self, poll_service):
        """Test updating while others are reading."""
        # Create poll
        poll_data = PollCreate(
            title="Concurrent Test",
            options=["Option 1", "Option 2"]
        )
        poll = await poll_service.create_poll(poll_data)
        
        # Simulate concurrent operations
        async def read_poll():
            return await poll_service.get_poll(poll.id)
        
        async def update_poll():
            return await poll_service.update_poll(
                poll.id,
                PollUpdate(title="Updated Title")
            )
        
        # Mix reads and updates
        tasks = [read_poll() for _ in range(5)]
        tasks.append(update_poll())
        tasks.extend([read_poll() for _ in range(5)])
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Verify no errors
        assert not any(isinstance(r, Exception) for r in results)
        
        # Clean up
        await poll_service.delete_poll(poll.id)
    
    @pytest.mark.asyncio
    async def test_database_connection_failure(self):
        """Test handling database connection issues."""
        # Create a service with broken connection
        from app.database import db
        
        # Temporarily break the database reference
        original_db = db.database
        db.database = None
        
        try:
            service = PollService()
            
            # Try to create a poll - should fail
            with pytest.raises(AttributeError):
                await service.create_poll(PollCreate(
                    title="Test",
                    options=["A", "B"]
                ))
        finally:
            # Restore the database reference
            db.database = original_db
    
    @pytest.mark.asyncio
    async def test_large_poll_with_many_options(self, poll_service):
        """Test poll with many options (performance test)."""
        # Create poll with 100 options
        options = [f"Option {i}" for i in range(100)]
        
        poll_data = PollCreate(
            title="Large Poll Test",
            description="Testing with many options",
            options=options
        )
        
        start_time = datetime.utcnow()
        poll = await poll_service.create_poll(poll_data)
        create_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Should create quickly even with many options
        assert create_time < 1.0  # Less than 1 second
        assert len(poll.options) == 100
        
        # Test retrieval performance
        start_time = datetime.utcnow()
        retrieved = await poll_service.get_poll(poll.id)
        retrieve_time = (datetime.utcnow() - start_time).total_seconds()
        
        assert retrieve_time < 0.5  # Less than 0.5 seconds
        assert len(retrieved.options) == 100
        
        # Clean up
        await poll_service.delete_poll(poll.id)
    
    @pytest.mark.asyncio
    async def test_data_integrity_with_special_characters(self, poll_service):
        """Test handling special characters and Unicode."""
        poll_data = PollCreate(
            title="Test 中文 العربية 🎉 <script>alert('xss')</script>",
            description="Testing & special < characters > \" '",
            options=["Option A™", "Option B®", "🔥 Hot", "❄️ Cold"]
        )
        
        poll = await poll_service.create_poll(poll_data)
        retrieved = await poll_service.get_poll(poll.id)
        
        # Verify data integrity
        assert retrieved.title == poll.title
        assert retrieved.description == poll.description
        assert len(retrieved.options) == 4
        
        # Clean up
        await poll_service.delete_poll(poll.id)