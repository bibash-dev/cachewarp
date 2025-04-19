import json
import re
import asyncio
import time
from fastapi import Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from typing import Optional, Callable, Any

from .cache import Cache
from .origin import fetch_origin
from src.proxy.ttl_calculator import calculate_ttl
from src.logging import logger
from src.config import settings

# --- Circuit Breaker Implementation ---
class CircuitBreaker:
    """
    A simple circuit breaker to prevent repeated calls to a failing service.

    It has three states:
    - CLOSED: Requests are allowed. If failures exceed a threshold, the state becomes OPEN.
    - OPEN: Requests are blocked for a recovery timeout period. After the timeout, it becomes HALF_OPEN.
    - HALF_OPEN: One trial request is allowed. If it succeeds, the state becomes CLOSED. If it fails, the state becomes OPEN again.
    """
    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 30):
        """
        Initializes the CircuitBreaker.

        Args:
            failure_threshold (int): The number of failures before opening the circuit.
            recovery_timeout (int): The time in seconds to wait in the OPEN state before attempting recovery.
        """
        self.state = "CLOSED"
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0

    def record_failure(self):
        """
        Records a failure and transitions the state to OPEN if the failure threshold is reached.
        """
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold and self.state == "CLOSED":
            self.state = "OPEN"
            logger.warning(f"Circuit breaker tripped: OPEN state, failures={self.failure_count}")

    def record_success(self):
        """
        Records a success and resets the failure count if in CLOSED or transitions to CLOSED from HALF_OPEN.
        """
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            logger.info("Circuit breaker reset: CLOSED state after successful recovery")
        elif self.state == "CLOSED":
            self.failure_count = 0

    def can_attempt(self) -> bool:
        """
        Checks if a request to the origin should be attempted based on the current state.

        Returns:
            bool: True if an attempt should be made, False otherwise.
        """
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info("Circuit breaker entering HALF_OPEN state for recovery attempt")
                return True
            return False
        return True  # HALF_OPEN allows one attempt

# Global circuit breaker instance, configured using settings
circuit_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    recovery_timeout=settings.circuit_breaker_recovery_timeout
)

async def caching_middleware(request: Request, call_next: Callable[[Request], Any], cache: Cache, background_tasks: BackgroundTasks) -> Response:
    """
    Middleware to handle caching of HTTP responses.

    It checks the cache for GET requests and serves cached responses if available.
    If a cache miss occurs, it fetches from the origin and caches the response.
    It also implements stale-while-revalidate and integrates the circuit breaker.
    """
    # --- Step 1: Bypass Cache for Excluded Paths ---
    if request.url.path in settings.cache_skip_paths:
        logger.debug(f"Bypassing cache for excluded path: {request.url.path}")
        return await call_next(request)

    # --- Step 2: Only Process GET Requests ---
    if request.method != "GET":
        logger.debug(f"Bypassing cache for non-GET request: {request.method}")
        return await call_next(request)

    # --- Step 3: Handle Client-Side Cache Directives ---
    cache_control = request.headers.get("Cache-Control", "").lower()
    if "no-cache" in cache_control or "no-store" in cache_control:
        logger.debug(f"Bypassing cache due to Cache-Control: {cache_control}")
        return await fetch_and_return(request, cache, None)

    # --- Step 4: Get Client's Max-Age if Provided ---
    max_age_match = re.search(r"max-age=(\d+)", cache_control)
    client_ttl: Optional[int] = int(max_age_match.group(1)) if max_age_match else None
    if client_ttl is not None:
        logger.debug(f"Client requested max-age: {client_ttl} seconds")

    # --- Step 5: Construct Cache Keys ---
    cache_key = f"cache:{request.url.path}"
    lock_key = f"lock:{cache_key}"
    logger.info(f"Processing request: {request.url.path}")

    # --- Step 6: Attempt to Retrieve from Cache ---
    try:
        cached, is_stale = await cache.get(cache_key)
        logger.debug(f"Cache get result for {cache_key}: cached={cached is not None}, is_stale={is_stale}")
        if cached is not None:
            logger.info(f"{'Stale ' if is_stale else ''}Cache hit for: {cache_key}")
            if is_stale:
                # Serve stale data immediately and schedule background refresh
                logger.debug(f"Scheduling background refresh task for: {cache_key}")
                background_tasks.add_task(refresh_cache, cache, cache_key, lock_key, request.url.path)
                logger.debug(f"Serving stale data after scheduling background refresh for: {cache_key}")
            return JSONResponse(content=cached)
        logger.info(f"Cache miss for: {cache_key}")
    except RuntimeError as e:
        logger.error(f"Error during cache retrieval: {str(e)}")
        return await call_next(request)
    except Exception as e:
        logger.error(f"Unexpected error during cache retrieval: {str(e)}", exc_info=True)
        return await call_next(request)

    # --- Step 7: Handle Cache Miss - Acquire Lock for Deduplication ---
    lock_value = await cache.acquire_lock(lock_key, timeout=10)
    logger.debug(f"Lock acquisition attempt for {lock_key}: acquired={lock_value is not None}")
    if lock_value:
        try:
            # Double-check cache after acquiring the lock to avoid race conditions
            cached, is_stale = await cache.get(cache_key)
            if cached is not None:
                logger.info(f"Cache hit after lock acquisition for: {cache_key}")
                return JSONResponse(content=cached)

            # Fetch data from the origin and cache the response
            response = await fetch_and_return(request, cache, cache_key, client_ttl)
            return response
        finally:
            # Ensure the lock is released, even if errors occur
            await cache.release_lock(lock_key, lock_value)
    else:
        # If lock couldn't be acquired, wait briefly and retry cache
        logger.debug(f"Lock held for {lock_key}, waiting 50ms to retry cache")
        await asyncio.sleep(0.05)
        cached, is_stale = await cache.get(cache_key)
        if cached is not None:
            logger.info(f"Cache hit after waiting for lock for: {cache_key}")
            return JSONResponse(content=cached)
        logger.warning(f"No cache after waiting for lock, fetching from origin")
        return await fetch_and_return(request, cache, None)

async def fetch_and_return(request: Request, cache: Cache, cache_key: Optional[str], client_ttl: Optional[int] = None) -> Response:
    """
    Fetches data from the origin, handles circuit breaker logic, caches the response, and returns it.
    """
    # --- Step 1: Check Circuit Breaker State ---
    if not circuit_breaker.can_attempt():
        logger.warning(f"Circuit breaker in OPEN state, attempting to serve stale data for {request.url.path}")
        if cache_key:
            cached, is_stale = await cache.get(cache_key)
            if cached is not None:
                logger.info(f"Serving stale data due to circuit breaker OPEN state: {cache_key}")
                return JSONResponse(content=cached, status_code=200)
        logger.error(f"Circuit breaker in OPEN state and no stale data available for {request.url.path}")
        return JSONResponse(content={"error": "Service Unavailable"}, status_code=503)

    try:
        # --- Step 2: Fetch Data from Origin ---
        origin_data = await fetch_origin(request.url.path)
        if "error" not in origin_data:
            try:
                content_type = origin_data.get("content_type", "application/json")
                status_code = origin_data.get("status_code", 200)
                # --- Step 3: Calculate TTL ---
                ttl = client_ttl if client_ttl is not None else calculate_ttl(request.url.path, content_type, status_code)
                logger.info(f"Calculated TTL for {cache_key or request.url.path}: {ttl} seconds")
                # --- Step 4: Cache the Response ---
                if cache_key and ttl > 0:
                    await cache.set(cache_key, origin_data["data"], ttl=ttl)
                    logger.info(f"Cache set for: {cache_key}")
                # --- Step 5: Record Success in Circuit Breaker ---
                circuit_breaker.record_success()
                # --- Step 6: Return Origin Response ---
                return JSONResponse(content=origin_data["data"], status_code=status_code)
            except Exception as e:
                logger.error(f"Error processing origin response or setting cache: {str(e)}", exc_info=True)
                circuit_breaker.record_failure()
                return JSONResponse(content={"error": "Invalid origin response"}, status_code=500)
        else:
            logger.warning(f"Origin error for {request.url.path}: {origin_data['error']}")
            circuit_breaker.record_failure()
            return JSONResponse(
                content=origin_data,
                status_code=404 if origin_data["error"] == "Not found" else 500
            )
    except Exception as e:
        logger.error(f"Origin fetch failed for {request.url.path}: {str(e)}", exc_info=True)
        circuit_breaker.record_failure()
        # --- Step 7: Fallback to Stale Data on Origin Failure ---
        if cache_key:
            cached, is_stale = await cache.get(cache_key)
            if cached is not None:
                logger.info(f"Serving stale data due to origin failure: {cache_key}")
                return JSONResponse(content=cached, status_code=200)
        return JSONResponse(content={"error": "Service Unavailable"}, status_code=503)

async def refresh_cache(cache: Cache, cache_key: str, lock_key: str, path: str) -> None:
    """
    Refreshes the cache in the background (for stale-while-revalidate).
    It also respects the circuit breaker state.
    """
    logger.debug(f"Background refresh task started for path: {path}")
    try:
        lock_value = await cache.acquire_lock(lock_key, timeout=10)
        if not lock_value:
            logger.debug(f"Lock held for background refresh: {lock_key}, skipping refresh")
            return
        try:
            # --- Step 1: Check Circuit Breaker State Before Refresh ---
            if not circuit_breaker.can_attempt():
                logger.warning(f"Circuit breaker in OPEN state, skipping background refresh for {path}")
                return
            # --- Step 2: Fetch Fresh Data from Origin ---
            logger.debug(f"Attempting background refresh for path: {path}")
            origin_data = await fetch_origin(path)
            if "error" not in origin_data:
                content_type = origin_data.get("content_type", "application/json")
                status_code = origin_data.get("status_code", 200)
                ttl = calculate_ttl(path, content_type, status_code)
                # --- Step 3: Update Cache with Fresh Data ---
                await cache.set(cache_key, origin_data["data"], ttl=ttl)
                logger.info(f"Background cache refresh completed for: {cache_key}")
                # --- Step 4: Record Success in Circuit Breaker ---
                circuit_breaker.record_success()
            else:
                logger.warning(f"Background refresh failed for {path}: {origin_data['error']}")
                circuit_breaker.record_failure()
        except Exception as e:
            logger.error(f"Error during background cache refresh for {cache_key}: {str(e)}", exc_info=True)
            circuit_breaker.record_failure()
        finally:
            await cache.release_lock(lock_key, lock_value)
            logger.debug(f"Background refresh completed for {cache_key}, lock released")
    except Exception as e:
        logger.error(f"Failed to execute background refresh task for {cache_key}: {str(e)}", exc_info=True)