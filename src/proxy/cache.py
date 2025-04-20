import json
import uuid
import time
from typing import Optional, Any, Tuple, Dict
from redis.asyncio import Redis
from cacheout import Cache as CacheOut
from redis.exceptions import ConnectionError, TimeoutError

from src.config import settings
from src.logging import logger
from src.proxy.metrics import record_cache_hit, record_cache_miss, record_redis_error  # Import metrics

# Lua script for safely releasing a distributed lock in Redis.
# This script checks if the lock's current value matches the value provided during release.
# It only deletes the lock if the values match, preventing accidental release by other processes.
SAFE_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

class Cache:
    """
    A two-tiered caching system designed for performance and resilience.

    It utilizes an L1 (in-memory) cache for fast, local access and an L2 (Redis)
    cache for a larger, distributed storage that persists across instances.
    The system also includes distributed locks to prevent cache stampedes.
    """
    def __init__(self) -> None:
        """
        Initializes the Cache instance.

        Sets up the in-memory (L1) cache using the `cacheout` library
        and prepares for a Redis (L2) connection. The lock release script
        SHA is initialized to None, and a dictionary to track L1 expiration
        times is created for more precise TTL management.
        """
        self.redis: Optional[Redis] = None  # Asynchronous Redis client instance
        self.l1_cache = CacheOut(
            maxsize=settings.l1_cache_maxsize,  # Maximum number of items in L1 cache (from settings)
        )
        self._release_lock_sha: Optional[str] = None  # SHA of the loaded safe release lock Lua script
        self._l1_expirations: Dict[str, float] = {}  # Stores the absolute expiration timestamp for L1 entries

    async def connect(self) -> None:
        """
        Establishes an asynchronous connection to the Redis server.

        Configures the Redis client using the URL from the application settings.
        It also loads the `SAFE_RELEASE_LOCK_SCRIPT` into Redis to ensure atomic
        lock releases, storing its SHA for efficient future use. Error handling
        is included to gracefully manage connection failures.
        """
        logger.info("Connecting to Redis")
        try:
            self.redis = await Redis.from_url(
                str(settings.redis_url),
                max_connections=20,  # Maximum number of connections in the Redis pool
                decode_responses=True,  # Automatically decode responses from Redis
            )
            # Load the safe release lock script into Redis for atomic lock release
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
            record_redis_error("ConnectionError")  # Record the Redis connection error metric
            self.redis = None
        except Exception as e:
            logger.error(
                f"An unexpected error occurred during Redis connection: {e}",
                exc_info=True,  # Include traceback for detailed error information
            )
            record_redis_error("UnexpectedError")  # Record an unexpected Redis error metric
            self.redis = None

    async def close(self) -> None:
        """
        Closes the asynchronous connection to the Redis server if it's active.

        This is important for releasing resources and ensuring a clean shutdown.
        """
        if self.redis:
            logger.info("Closing Redis connection")
            await self.redis.aclose()  # Asynchronously close the Redis connection
            self.redis = None
            logger.info("Redis connection closed")

    async def get(self, key: str) -> Tuple[Optional[Any], bool]:
        """
        Retrieves the value associated with the given key, checking the L1 cache first,
        then the L2 cache (Redis) if not found in L1.

        Returns:
            Tuple[Optional[Any], bool]:
                - The cached value (can be None if not found or if there's an error).
                - A boolean indicating if the retrieved value from L2 was considered stale.
        """
        # 1. Check L1 cache (in-memory for fast access)
        if value := self.l1_cache.get(key):
            # Calculate remaining TTL based on the stored expiration time
            expiration = self._l1_expirations.get(key, 0)
            ttl_remaining = max(0, expiration - time.time())
            logger.debug(
                f"L1 cache hit: {key}, TTL remaining: {ttl_remaining:.2f} seconds"
            )
            record_cache_hit("L1")  # Increment the L1 cache hit metric
            return value, False  # Value found in L1, so it's not stale

        logger.debug(f"L1 cache miss: {key}")
        record_cache_miss("L1")  # Increment the L1 cache miss metric

        # 2. Check L2 cache (Redis) if not found in L1
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            data = await self.redis.get(key)  # Get the raw JSON data from Redis
            ttl = await self.redis.ttl(key)  # Get the TTL of the key in Redis
            logger.debug(
                f"Redis get for {key}: data exists={data is not None}, TTL={ttl}"
            )
            if data:
                try:
                    parsed = json.loads(data)  # Parse the outer JSON structure
                    value = json.loads(parsed["value"])  # Parse the actual cached value (which was JSON-encoded)
                    set_time = parsed["set_time"]  # Timestamp when the value was set in Redis
                    original_ttl = parsed["ttl"]  # Original TTL set for the value
                    elapsed = time.time() - set_time  # Time elapsed since the value was cached
                    is_stale = elapsed > original_ttl  # Check if the cached data has exceeded its original TTL
                    logger.debug(
                        f"Cache {key}: set_time={set_time}, ttl={original_ttl}, elapsed={elapsed}, is_stale={is_stale}"
                    )
                    if not is_stale:
                        # If the data from L2 is not stale, populate the L1 cache
                        l1_ttl = max(original_ttl - elapsed, 1) if original_ttl > elapsed else 1
                        self.l1_cache.set(key, value, ttl=l1_ttl)
                        self._l1_expirations[key] = time.time() + l1_ttl  # Store the absolute expiration time
                        logger.debug(
                            f"L2 cache hit: {key}, populated L1 with TTL {l1_ttl}"
                        )
                    else:
                        logger.debug(f"L2 cache stale hit: {key}")
                    record_cache_hit("L2")  # Increment the L2 cache hit metric
                    return value, is_stale
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in Redis for key {key}, clearing")
                    await self.redis.delete(key)  # Remove the invalid entry from Redis
                    return None, False

            # Check for potentially stale data in a separate key (if the fresh key was a miss)
            stale_key = f"stale:{key}"
            stale_data = await self.redis.get(stale_key)
            if stale_data:
                value = json.loads(stale_data)  # Parse the stale JSON data
                logger.debug(f"Stale cache hit: {stale_key}")
                record_cache_hit("L2")  # Increment the L2 cache hit metric (for stale data)
                return value, True  # Indicate that the data is stale

            logger.debug(f"L2 cache miss: {key}")
            record_cache_miss("L2")  # Increment the L2 cache miss metric
            return None, False  # Key not found in L2

        except ConnectionError as e:
            logger.error(
                f"Redis connection error for key {key}: {str(e)}", exc_info=True
            )
            record_redis_error("ConnectionError")  # Record Redis connection error metric
            return None, False
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error for key {key}: {str(e)}", exc_info=True
            )
            record_redis_error("TimeoutError")  # Record Redis timeout error metric
            return None, False
        except Exception as e:
            logger.error(f"Redis get error for key {key}: {str(e)}", exc_info=True)
            record_redis_error("UnexpectedError")  # Record unexpected Redis error metric
            return None, False

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """
        Sets the value for the given key in both the L1 (in-memory) and L2 (Redis) caches.

        An optional TTL (time-to-live) can be provided. If not specified, the default
        cache TTL from the application settings will be used. To support stale-while-revalidate,
        the fresh data and a potentially stale version are stored in Redis with different TTLs.

        Args:
            key (str): The key under which to store the value.
            value (Any): The value to be cached.
            ttl (Optional[int]): The time-to-live for the cache entry in seconds.
        """
        effective_ttl = ttl if ttl is not None else settings.cache_default_ttl
        if effective_ttl <= 0:
            logger.debug(f"Skipping cache set for {key} due to non-positive TTL")
            return

        # 1. Set in L1 cache (in-memory)
        self.l1_cache.set(key, value, ttl=effective_ttl)
        self._l1_expirations[key] = time.time() + effective_ttl  # Store the absolute expiration time
        logger.debug(f"L1 cache set: {key} with TTL {effective_ttl} seconds")

        # 2. Set in L2 cache (Redis)
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        try:
            # Store fresh data with metadata (set time and original TTL) for revalidation
            data = {
                "value": json.dumps(value),
                "set_time": time.time(),
                "ttl": effective_ttl,
            }
            await self.redis.setex(key, int(effective_ttl), json.dumps(data))
            # Store a potentially stale version of the data with an extended TTL
            stale_key = f"stale:{key}"
            await self.redis.setex(
                stale_key,
                int(effective_ttl + settings.stale_ttl_offset),  # Longer TTL for stale data
                json.dumps(value),
            )
            redis_ttl = await self.redis.ttl(key)  # Get the actual TTL set in Redis for debugging
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
            record_redis_error("ConnectionError")  # Record Redis connection error metric
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error during set for key {key}: {str(e)}", exc_info=True
            )
            record_redis_error("TimeoutError")  # Record Redis timeout error metric
        except Exception as e:
            logger.error(f"Redis set error for key {key}: {str(e)}", exc_info=True)
            record_redis_error("UnexpectedError")  # Record unexpected Redis error metric

    async def acquire_lock(self, lock_key: str, timeout: int = 10) -> Optional[str]:
        """
        Attempts to acquire a distributed lock in Redis.

        This is useful for preventing cache stampedes by ensuring only one request
        can regenerate the cache if it's expired or not present. The lock has an
        expiration time to prevent deadlocks in case the process holding the lock fails.

        Args:
            lock_key (str): The key to use for the lock in Redis.
            timeout (int): The expiration time of the lock in seconds.

        Returns:
            Optional[str]: A unique lock value if the lock was successfully acquired,
                           None otherwise (if the lock is already held).
        """
        if not self.redis:
            logger.error("Redis not connected")
            raise RuntimeError("Redis not connected")
        lock_value = str(uuid.uuid4())  # Generate a unique value for the lock
        try:
            # Atomically SET the key if it doesn't exist (NX) and set an expiration time (EX)
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
            record_redis_error("ConnectionError")  # Record Redis connection error metric
            return None
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error acquiring lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            record_redis_error("TimeoutError")  # Record Redis timeout error metric
            return None
        except Exception as e:
            logger.error(f"Error acquiring lock {lock_key}: {str(e)}", exc_info=True)
            record_redis_error("UnexpectedError")  # Record unexpected Redis error metric
            return None

    async def release_lock(self, lock_key: str, lock_value: str) -> bool:
        """
        Releases a distributed lock in Redis, but only if the provided lock value matches
        the value currently stored for the lock key.

        This uses a Lua script to ensure that the release operation is atomic, preventing
        one client from accidentally releasing another client's lock.

        Args:
            lock_key (str): The key of the lock to be released.
            lock_value (str): The unique value that was used to acquire the lock.

        Returns:
            bool: True if the lock was successfully released, False otherwise
                  (e.g., if the lock key doesn't exist or the value doesn't match).
        """
        if not self.redis or not self._release_lock_sha:
            logger.error("Redis not connected or release script not loaded")
            return False
        try:
            # Execute the Lua script to ensure atomic release
            result = await self.redis.evalsha(
                self._release_lock_sha,  # SHA of the loaded Lua script
                1,  # Number of keys being passed (just the lock key)
                lock_key,  # The key of the lock
                lock_value,  # The value that should match the lock's current value
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
            record_redis_error("ConnectionError")  # Record Redis connection error metric
            return False
        except TimeoutError as e:
            logger.warning(
                f"Redis timeout error releasing lock {lock_key}: {str(e)}",
                exc_info=True,
            )
            record_redis_error("TimeoutError")  # Record Redis timeout error metric
            return False
        except Exception as e:
            logger.error(f"Error releasing lock {lock_key}: {str(e)}", exc_info=True)
            record_redis_error("UnexpectedError")  # Record unexpected Redis error metric
            return False