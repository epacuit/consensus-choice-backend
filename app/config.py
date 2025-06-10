
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "BetterChoices API"
    MONGODB_URL: str
    MONGODB_DB: str
    SECRET_KEY: str  # No default value - must come from .env
    
    # API Settings
    API_V1_STR: str = "/api/v1"
    
    # CORS Settings (for frontend)
    BACKEND_CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173"]
    
    model_config = ConfigDict(env_file=".env")

settings = Settings()
