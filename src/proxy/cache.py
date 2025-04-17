import json
from typing import Optional, Any
from redis.asyncio import Redis
from cachetools import TTLCache

from src.config import settings
from src.logging import logger

class Cache:
    def __init__(self):
        self.redis: Optional[Redis] = None
        # L1 cache: in-memory LRU cache with TTL
        self.l1_cache = TTLCache(
            maxsize=settings.l1_cache_maxsize,  # Number of items
            ttl=settings.cache_default_ttl      # TTL in seconds
        )

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
        """Retrieve the value for the given key from L1 or L2 cache."""
        # Check L1 cache first
        if key in self.l1_cache:
            logger.debug(f"L1 cache hit: {key}")
            return self.l1_cache[key]

        logger.debug(f"L1 cache miss: {key}")

        # Check L2 cache (Redis)
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            if data := await self.redis.get(key):
                value = json.loads(data)
                # Populate L1 cache on L2 hit
                self.l1_cache[key] = value
                logger.debug(f"L2 cache hit: {key}")
                return value
            logger.debug(f"L2 cache miss: {key}")
            return None
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {str(e)}", exc_info=True)
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set the value for a given key in both L1 and L2 caches with an optional TTL."""
        # Use provided TTL, or fall back to default
        effective_ttl = ttl if ttl is not None else settings.cache_default_ttl

        # Set in L1 cache (TTLCache has its own TTL; we can't override per key)
        self.l1_cache[key] = value
        logger.debug(f"L1 cache set: {key}")

        # Set in L2 cache (Redis) with the specified TTL
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            await self.redis.setex(key, effective_ttl, json.dumps(value))
            logger.debug(f"L2 cache set: {key} with TTL {effective_ttl} seconds")
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {str(e)}", exc_info=True)
            pass