from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from .config import settings

class Database:
    client: AsyncIOMotorClient = None
    database: AsyncIOMotorDatabase = None

db = Database()

async def connect_db():
    db.client = AsyncIOMotorClient(settings.MONGODB_URL)
    db.database = db.client[settings.MONGODB_DB]
    print(f"Connected to MongoDB: {settings.MONGODB_DB}")
    
    # Create indexes after connection
    await create_indexes()

async def close_db():
    db.client.close()
    print("Closed MongoDB connection")

def get_database() -> AsyncIOMotorDatabase:
    return db.database

async def create_indexes():
    """Create necessary indexes for optimal performance with unified ballot model"""
    
    # Indexes for polls collection
    await db.database.polls.create_index([("created_at", -1)])
    await db.database.polls.create_index([("is_private", 1)])
    await db.database.polls.create_index([("creator_email", 1)])
    
    # Indexes for ballots collection (unified model with count field)
    await db.database.ballots.create_index([("poll_id", 1)])
    await db.database.ballots.create_index([("poll_id", 1), ("is_test", 1)])
    await db.database.ballots.create_index([("poll_id", 1), ("browser_fingerprint", 1)])
    await db.database.ballots.create_index([("poll_id", 1), ("voter_token", 1)])
    
    # Index for bulk imports
    await db.database.ballots.create_index([("poll_id", 1), ("import_batch_id", 1)])
    
    # Compound index for efficient vote counting
    await db.database.ballots.create_index([
        ("poll_id", 1), 
        ("is_test", 1), 
        ("count", 1)
    ])
    
    # Index for voter type queries
    await db.database.ballots.create_index([("poll_id", 1), ("voter_type", 1)])
    
    # Index for submitted_at for time-based queries
    await db.database.ballots.create_index([("poll_id", 1), ("submitted_at", -1)])
    
    print("Database indexes created successfully")