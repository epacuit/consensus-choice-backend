from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import polls, ballots, results
from .config import settings
from .database import connect_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Connecting to MongoDB...")
    await connect_db()
    yield
    # Shutdown
    print("Disconnecting from MongoDB...")
    await close_db()


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan  # Use lifespan instead of on_event
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(polls.router, prefix="/api/v1/polls", tags=["polls"])
app.include_router(ballots.router, prefix="/api/v1/ballots", tags=["ballots"])
app.include_router(results.router, prefix="/api/v1/results", tags=["results"])
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
