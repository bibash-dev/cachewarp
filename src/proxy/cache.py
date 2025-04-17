import json
from typing import Optional, Any
from redis.asyncio import Redis
from cacheout import Cache as CacheOut

from src.config import settings
from src.logging import logger

class Cache:
    def __init__(self):
        self.redis: Optional[Redis] = None
        # L1 cache: in-memory cache with LRU eviction
        self.l1_cache = CacheOut(
            maxsize=settings.l1_cache_maxsize,  # Number of items
            # No global TTL; we'll set per-key TTLs in the set method
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
        if value := self.l1_cache.get(key):
            logger.debug(f"L1 cache hit: {key}")
            return value

        logger.debug(f"L1 cache miss: {key}")

        # Check L2 cache (Redis)
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            if data := await self.redis.get(key):
                value = json.loads(data)
                # Populate L1 cache on L2 hit (use the remaining TTL from Redis)
                ttl = await self.redis.ttl(key)  # Get remaining TTL from Redis
                if ttl > 0:  # Only set if TTL is positive
                    self.l1_cache.set(key, value, ttl=ttl)
                else:
                    self.l1_cache.set(key, value, ttl=settings.cache_default_ttl)
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

        # Set in L1 cache with the specified TTL
        self.l1_cache.set(key, value, ttl=effective_ttl)
        logger.debug(f"L1 cache set: {key} with TTL {effective_ttl} seconds")

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