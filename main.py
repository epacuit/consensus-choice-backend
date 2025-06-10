# Create main.py in the root directory (not in app/)
from app.main import app

@app.get("/")
async def root():
    return {
        "name": "Consensus Choice API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health")
async def health_check():
    from app.database import db
    try:
        await db.client.admin.command('ping')
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return {
        "status": "healthy",
        "database": db_status
    }