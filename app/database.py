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

async def close_db():
    db.client.close()
    print("Closed MongoDB connection")

def get_database() -> AsyncIOMotorDatabase:
    return db.database
