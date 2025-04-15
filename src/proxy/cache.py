import json
from typing import Optional, Any
from redis.asyncio import Redis

from src.config import settings
from src.logging import logger

class Cache:
    def __init__(self):
        self.redis: Optional[Redis] = None

    async def connect(self):
        """Establish a connection to the Redis server."""
        logger.info("Connecting to Redis")
        self.redis = await Redis.from_url(
            str(settings.redis_url),
            max_connections=20,
            decode_responses=True
        )
        logger.info("Redis connection established")

    async def close(self):
        """Close the connection to the Redis server."""
        if self.redis:
            logger.info("Closing Redis connection")
            await self.redis.aclose()
            logger.info("Redis connection closed")

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve the value for the given key from Redis."""
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            if data := await self.redis.get(key):
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {str(e)}", exc_info=True)
            return None

    async def set(self, key: str, value: Any):
        """Set the value for a given key in Redis with a TTL."""
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            await self.redis.setex(key, settings.cache_default_ttl, json.dumps(value))
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {str(e)}", exc_info=True)
            pass