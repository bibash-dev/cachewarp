import json
import uuid
import time
from typing import Optional, Any, Tuple
from redis.asyncio import Redis
from cacheout import Cache as CacheOut
from redis.exceptions import ConnectionError, TimeoutError

from src.config import settings
from src.logging import logger

# Lua script for safe lock release (runs atomically in Redis)
SAFE_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class Cache:
    def __init__(self) -> None:
        self.redis: Optional[Redis] = None
        self.l1_cache = CacheOut(
            maxsize=settings.l1_cache_maxsize,
        )
        self._release_lock_sha: Optional[str] = None
        # Dictionary to store expiration times for L1 cache entries
        self._l1_expirations: dict[str, float] = {}

    async def connect(self) -> None:
        """Establish a connection to the Redis server."""
        logger.info("Connecting to Redis")
        try:
            self.redis = await Redis.from_url(
                str(settings.redis_url), max_connections=20, decode_responses=True
            )
            # Load the safe release lock script into Redis
            if self.redis:
                self._release_lock_sha = await self.redis.script_load(
                    SAFE_RELEASE_LOCK_SCRIPT
                )
                logger.info("Redis connection established")
                logger.debug(
                    f"Safe release lock script loaded (SHA: {self._release_lock_sha})"
                )
            else:
                logger.error("Redis client is None after connection attempt.")
        except ConnectionError as e:
            logger.error(f"Error connecting to Redis: {e}")
            self.redis = None
        except Exception as e:
            logger.error(
                f"An unexpected error occurred during Redis connection: {e}",
                exc_info=True,
            )
            self.redis = None

    async def close(self) -> None:
        """Close the connection to the Redis server."""
        if self.redis:
            logger.info("Closing Redis connection")
            await self.redis.aclose()
            self.redis = None
            logger.info("Redis connection closed")

    async def get(self, key: str) -> Tuple[Optional[Any], bool]:
        """Retrieve the value for the given key from L1 or L2 cache, with staleness flag."""
        # 1. Check L1 cache (fast, in-memory)
        if value := self.l1_cache.get(key):
            # Calculate remaining TTL using stored expiration time
            expiration = self._l1_expirations.get(key, 0)
            ttl_remaining = max(0, expiration - time.time())
            logger.debug(
                f"L1 cache hit: {key}, TTL remaining: {ttl_remaining:.2f} seconds"
            )
            return value, False  # Not stale

        logger.debug(f"L1 cache miss: {key}")

        # 2. Check L2 cache (Redis)
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError(
                "Redis not connected"
            )  # Raise a specific error if Redis isn't available
        try:
            data = await self.redis.get(key)
            ttl = await self.redis.ttl(key)
            logger.debug(
                f"Redis get for {key}: data exists={data is not None}, TTL={ttl}"
            )
            if data:
                try:
                    parsed = json.loads(data)
                    value = json.loads(parsed["value"])
                    set_time = parsed["set_time"]
                    ttl = parsed["ttl"]
                    elapsed = time.time() - set_time
                    is_stale = elapsed > ttl
                    logger.debug(
                        f"Cache {key}: set_time={set_time}, ttl={ttl}, elapsed={elapsed}, is_stale={is_stale}"
                    )
                    if not is_stale:
                        # Populate L1 cache if the data from L2 is not stale
                        l1_ttl = max(ttl - elapsed, 1) if ttl > elapsed else 1
                        self.l1_cache.set(key, value, ttl=l1_ttl)
                        self._l1_expirations[key] = time.time() + l1_ttl
                        logger.debug(
                            f"L2 cache hit: {key}, populated L1 with TTL {l1_ttl}"
                        )
                    else:
                        logger.debug(f"L2 cache stale hit: {key}")
                    return value, is_stale
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in Redis for key {key}, clearing")
                    await self.redis.delete(key)
                    return None, False

            # Check for stale data in separate key (after a cache miss in the fresh key)
            stale_key = f"stale:{key}"
            stale_data = await self.redis.get(stale_key)
            if stale_data:
                value = json.loads(stale_data)
                logger.debug(f"Stale cache hit: {stale_key}")
                return value, True

            logger.debug(f"L2 cache miss: {key}")
            return None, False
        except ConnectionError as e:
            logger.error(
                f"Redis connection error for key {key}: {str(e)}", exc_info=True
            )
            return None, False
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error for key {key}: {str(e)}", exc_info=True
            )
            return None, False
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {str(e)}", exc_info=True)
            return None, False

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set the value for a given key in both L1 and L2 caches with an optional TTL."""
        effective_ttl = ttl if ttl is not None else settings.cache_default_ttl
        if effective_ttl <= 0:
            logger.debug(f"Skipping cache set for {key} due to non-positive TTL")
            return

        # 1. Set in L1 cache (fast, in-memory)
        self.l1_cache.set(key, value, ttl=effective_ttl)
        self._l1_expirations[key] = time.time() + effective_ttl
        logger.debug(f"L1 cache set: {key} with TTL {effective_ttl} seconds")

        # 2. Set in L2 cache (Redis)
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError(
                "Redis not connected"
            )  # Raise a specific error if Redis isn't available
        try:
            # Store fresh data
            data = {
                "value": json.dumps(value),
                "set_time": time.time(),
                "ttl": effective_ttl,
            }
            await self.redis.setex(key, int(effective_ttl), json.dumps(data))
            # Store stale data in a separate key with a longer TTL
            stale_key = f"stale:{key}"
            await self.redis.setex(
                stale_key,
                int(effective_ttl + settings.stale_ttl_offset),
                json.dumps(value),
            )
            redis_ttl = await self.redis.ttl(key)
            logger.debug(
                f"L2 cache set: {key} with TTL {int(effective_ttl)} seconds, actual Redis TTL={redis_ttl}"
            )
            logger.debug(
                f"Stale data set: {stale_key} with TTL {int(effective_ttl + settings.stale_ttl_offset)} seconds"
            )
        except ConnectionError as e:
            logger.error(
                f"Redis connection error during set for key {key}: {str(e)}",
                exc_info=True,
            )
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error during set for key {key}: {str(e)}", exc_info=True
            )
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {str(e)}", exc_info=True)

    async def acquire_lock(self, lock_key: str, timeout: int = 10) -> Optional[str]:
        """Attempt to acquire a Redis lock for the given key."""
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError(
                "Redis not connected"
            )  # Raise a specific error if Redis isn't available
        lock_value = str(uuid.uuid4())
        try:
            # SET the key if it doesn't exist (NX) and set an expiration time (EX)
            acquired = await self.redis.set(lock_key, lock_value, nx=True, ex=timeout)
            if acquired:
                logger.debug(f"Acquired lock: {lock_key} with value {lock_value}")
                return lock_value
            logger.debug(f"Failed to acquire lock: {lock_key} (already held)")
            return None
        except ConnectionError as e:
            logger.error(
                f"Redis connection error acquiring lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            return None
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error acquiring lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(f"Error acquiring lock {lock_key}: {str(e)}", exc_info=True)
            return None

    async def release_lock(self, lock_key: str, lock_value: str) -> bool:
        """Release a Redis lock if the value matches using a Lua script for atomicity."""
        if not self.redis or not self._release_lock_sha:
            logger.error("Redis not connected or release script not loaded")
            return False
        try:
            # Execute the Lua script to ensure atomic release
            result = await self.redis.evalsha(
                self._release_lock_sha, 1, lock_key, lock_value
            )
            if result == 1:
                logger.debug(f"Released lock: {lock_key}")
                return True
            logger.debug(
                f"Failed to release lock: {lock_key} (value mismatch or expired)"
            )
            return False
        except ConnectionError as e:
            logger.error(
                f"Redis connection error releasing lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            return False
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error releasing lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            return False
        except Exception as e:
            logger.error(f"Error releasing lock {lock_key}: {str(e)}", exc_info=True)
            return False
