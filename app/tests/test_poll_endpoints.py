"""
Tests for Poll API endpoints using TestClient.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from bson import ObjectId
from datetime import datetime


class TestPollEndpoints:
    """Test Poll API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from app.main import app
        return TestClient(app)
    
    @pytest.fixture
    def mock_poll_response(self):
        """Sample poll response."""
        return {
            "id": str(ObjectId()),
            "title": "Test Poll",
            "description": "Test Description",
            "options": [
                {"id": "1", "name": "Option A", "description": None, "image_url": None},
                {"id": "2", "name": "Option B", "description": None, "image_url": None}
            ],
            "is_private": False,
            "settings": {
                "allow_ties": True,
                "require_complete_ranking": False,
                "randomize_options": True,
                "allow_write_in": False,
                "show_detailed_results": True,
                "show_rankings": True,
                "anonymize_voters": True,
                "results_visibility": "public",
                "can_view_before_close": False
            },
            "closing_datetime": None,
            "is_completed": False,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "tags": ["test"],
            "vote_count": 0,
            "creator_id": None,
            "is_active": True,
            "has_closed": False,
            "time_remaining": None
        }
    
    def test_create_poll_endpoint(self, client, mock_poll_response):
        """Test POST /api/v1/polls endpoint."""
        with patch('app.services.poll_service.PollService.create_poll', new_callable=AsyncMock) as mock_create:
            # Mock the service to return a Poll object
            from app.models.poll import Poll
            mock_poll = Poll(**mock_poll_response)
            mock_create.return_value = mock_poll
            
            # Make request
            response = client.post(
                "/api/v1/polls",
                json={
                    "title": "Test Poll",
                    "description": "Test Description",
                    "options": ["Option A", "Option B"],
                    "is_private": False,
                    "tags": ["test"]
                }
            )
            
            # Assert
            assert response.status_code == 201
            data = response.json()
            assert data["title"] == "Test Poll"
            assert len(data["options"]) == 2
    
    def test_get_poll_endpoint(self, client, mock_poll_response):
        """Test GET /api/v1/polls/{poll_id} endpoint."""
        poll_id = mock_poll_response["id"]
        
        with patch('app.services.poll_service.PollService.get_poll', new_callable=AsyncMock) as mock_get:
            from app.models.poll import Poll
            mock_poll = Poll(**mock_poll_response)
            mock_get.return_value = mock_poll
            
            response = client.get(f"/api/v1/polls/{poll_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == poll_id
            assert data["title"] == "Test Poll"
    
    def test_get_poll_not_found(self, client):
        """Test GET /api/v1/polls/{poll_id} when poll doesn't exist."""
        with patch('app.services.poll_service.PollService.get_poll', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            
            poll_id = str(ObjectId())
            response = client.get(f"/api/v1/polls/{poll_id}")
            
            assert response.status_code == 404
            assert f"Poll with ID {poll_id} not found" in response.json()["detail"]
    
    def test_list_polls_endpoint(self, client, mock_poll_response):
        """Test GET /api/v1/polls endpoint."""
        with patch('app.services.poll_service.PollService.list_polls', new_callable=AsyncMock) as mock_list:
            from app.models.poll import Poll
            mock_polls = [
                Poll(**mock_poll_response),
                Poll(**{**mock_poll_response, "title": "Poll 2", "vote_count": 10})
            ]
            mock_list.return_value = mock_polls
            
            response = client.get("/api/v1/polls?skip=0&limit=10")
            
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["title"] == "Test Poll"
            assert data[1]["title"] == "Poll 2"
    
    # Comment out until PATCH is implemented
    # def test_update_poll_endpoint(self, client, mock_poll_response):
    #     """Test PATCH /api/v1/polls/{poll_id} endpoint."""
    #     poll_id = mock_poll_response["id"]
        
    #     with patch('app.services.poll_service.PollService.update_poll') as mock_update:
    #         from app.models.poll import Poll
    #         updated_response = {**mock_poll_response, "title": "Updated Title"}
    #         mock_poll = Poll(**updated_response)
    #         mock_update.return_value = mock_poll
            
    #         response = client.patch(
    #             f"/api/v1/polls/{poll_id}",
    #             json={"title": "Updated Title"}
    #         )
            
    #         assert response.status_code == 200
    #         data = response.json()
    #         assert data["title"] == "Updated Title"
    
    def test_delete_poll_endpoint(self, client):
        """Test DELETE /api/v1/polls/{poll_id} endpoint."""
        poll_id = str(ObjectId())
        
        with patch('app.services.poll_service.PollService.delete_poll', new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = True
            
            response = client.delete(f"/api/v1/polls/{poll_id}")
            
            assert response.status_code == 204
    
    def test_delete_poll_not_found(self, client):
        """Test DELETE /api/v1/polls/{poll_id} when poll doesn't exist."""
        with patch('app.services.poll_service.PollService.delete_poll', new_callable=AsyncMock) as mock_delete:
            mock_delete.return_value = False
            
            response = client.delete(f"/api/v1/polls/{str(ObjectId())}")
            
            assert response.status_code == 404
    
    def test_invalid_poll_data(self, client):
        """Test creating poll with invalid data."""
        response = client.post(
            "/api/v1/polls",
            json={
                "title": "",  # Empty title should fail validation
                "options": []  # No options should fail
            }
        )
        
        assert response.status_code == 422  # Validation error
        # Check that validation errors are present
        assert "detail" in response.json()
    
    # Comment out until auth is implemented
    # def test_create_poll_with_auth(self, client):
    #     """Test creating poll with authentication."""
    #     # This assumes you have auth middleware
    #     with patch('app.services.poll_service.PollService.create_poll') as mock_create:
    #         with patch('app.auth.get_current_user') as mock_auth:
    #             mock_auth.return_value = {"user_id": "123", "email": "user@example.com"}
                
    #             # Your auth implementation might differ
    #             headers = {"Authorization": "Bearer fake-token"}
                
    #             response = client.post(
    #                 "/api/v1/polls",
    #                 json={
    #                     "title": "Auth Poll",
    #                     "options": ["Yes", "No"],
    #                     "is_private": True
    #                 },
    #                 headers=headers
    #             )
                
    #             # Assert based on your auth implementation
    #             # assert response.status_code == 201