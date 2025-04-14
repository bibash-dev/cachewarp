import json
from typing import Optional, Any
from redis.asyncio import Redis

from src.config import settings


class Cache:
    def __init__(self):
        self.redis: Optional[Redis] = None

    async def connect(self):
        """Establish a connection to the Redis server."""
        self.redis = await Redis.from_url(
            str(settings.redis_url),
            max_connections=20,
            decode_responses=True
        )

    async def close(self):
        """Close the connection to the Redis server."""
        if self.redis:
            await self.redis.aclose()

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve the value for the given key from Redis."""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        if data := await self.redis.get(key):
            return json.loads(data)
        return None

    async def set(self, key: str, value: Any):
        """Set the value for a given key in Redis with a TTL."""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        await self.redis.setex(
            key,
            settings.cache_default_ttl,
            json.dumps(value)
        )
