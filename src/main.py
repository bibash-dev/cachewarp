from fastapi import FastAPI
import uvicorn
from config import settings  # NEW: Centralized config

app = FastAPI(title="CacheWarp", version="0.1.0")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "redis": settings.redis_url  # Verify config works
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Enable dev reload
    )