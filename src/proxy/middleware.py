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
from src.proxy.metrics import (
    record_request,
    observe_request_latency,
    set_circuit_breaker_state,
    record_cache_hit,
    record_cache_miss,
    record_redis_error,
)


# --- Circuit Breaker Implementation ---
class CircuitBreaker:
    """
    A simple state machine implementing the Circuit Breaker pattern.

    This helps to prevent cascading failures by stopping requests to a potentially
    failing origin service. It transitions through three states: CLOSED (requests allowed),
    OPEN (requests blocked for a timeout), and HALF_OPEN (a trial request is allowed).
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 30):
        """
        Initializes the CircuitBreaker with configuration parameters.

        Args:
            failure_threshold (int): The number of consecutive failures before the circuit opens.
            recovery_timeout (int): The duration in seconds the circuit remains open before attempting recovery.
        """
        self.state = "CLOSED"  # Initial state: requests are allowed
        self.failure_count = 0  # Counter for consecutive failures
        self.failure_threshold = failure_threshold  # Threshold for opening the circuit
        self.recovery_timeout = recovery_timeout  # Duration of the OPEN state
        self.last_failure_time = 0  # Timestamp of the last recorded failure
        set_circuit_breaker_state(
            self.state
        )  # Initialize Prometheus metric for circuit breaker state

    def record_failure(self):
        """
        Increments the failure count and transitions the circuit to OPEN if the threshold is met.

        If the circuit is CLOSED and the failure count reaches the threshold, it transitions
        to OPEN, blocking subsequent requests for the recovery timeout period.
        """
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold and self.state == "CLOSED":
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker tripped: OPEN state, failures={self.failure_count}"
            )
            set_circuit_breaker_state(self.state)  # Update Prometheus metric
            # In OPEN state, no requests are forwarded to the origin

    def record_success(self):
        """
        Resets the failure count if the circuit is CLOSED or transitions it from HALF_OPEN to CLOSED.

        A successful request after a recovery attempt (in HALF_OPEN state) indicates
        that the origin service is likely healthy, so the circuit is closed.
        If the circuit is already CLOSED, a success simply resets the failure counter.
        """
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failure_count = 0
            logger.info("Circuit breaker reset: CLOSED state after successful recovery")
            set_circuit_breaker_state(self.state)  # Update Prometheus metric
        elif self.state == "CLOSED":
            self.failure_count = 0

    def can_attempt(self) -> bool:
        """
        Determines if a request to the origin service should be attempted based on the current state.

        - In CLOSED state, attempts are always allowed.
        - In OPEN state, attempts are blocked until the recovery timeout expires.
        - In HALF_OPEN state, one trial attempt is allowed.

        Returns:
            bool: True if an attempt can be made, False otherwise.
        """
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                logger.info(
                    "Circuit breaker entering HALF_OPEN state for recovery attempt"
                )
                set_circuit_breaker_state(self.state)  # Update Prometheus metric
                return True  # Allow one trial request
            return False  # Block requests in OPEN state
        return True  # Allow the single trial request in HALF_OPEN state


# Global instance of the CircuitBreaker, configured using application settings
circuit_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    recovery_timeout=settings.circuit_breaker_recovery_timeout,
)


async def caching_middleware(
    request: Request,
    call_next: Callable[[Request], Any],
    cache: Cache,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Middleware function to handle caching of HTTP responses for incoming requests.

    It intercepts GET requests, checks the cache for a valid response, serves it if found,
    and otherwise forwards the request to the origin, caching the response before returning.
    Implements stale-while-revalidate to improve perceived performance and integrates
    the Circuit Breaker pattern for resilience against origin failures.
    """
    start_time = (
        time.time()
    )  # Record the start time of the request for latency measurement
    record_request()  # Increment the total number of requests processed (Prometheus metric)

    # --- Step 1: Bypass Cache for Excluded Paths ---
    if request.url.path in settings.cache_skip_paths:
        logger.debug(f"Bypassing cache for excluded path: {request.url.path}")
        response = await call_next(
            request
        )  # Directly forward the request to the next handler
        duration = time.time() - start_time
        observe_request_latency(
            duration
        )  # Record the total request processing latency (Prometheus metric)
        return response

    # --- Step 2: Only Process GET Requests ---
    if request.method != "GET":
        logger.debug(f"Bypassing cache for non-GET request: {request.method}")
        response = await call_next(request)  # Directly forward non-GET requests
        duration = time.time() - start_time
        observe_request_latency(duration)  # Record latency
        return response

    # --- Step 3: Handle Client-Side Cache Directives ---
    cache_control = request.headers.get("Cache-Control", "").lower()
    if "no-cache" in cache_control or "no-store" in cache_control:
        logger.debug(f"Bypassing cache due to Cache-Control: {cache_control}")
        response = await fetch_and_return(
            request, cache, None
        )  # Force fetch from origin
        duration = time.time() - start_time
        observe_request_latency(duration)  # Record latency
        return response

    # --- Step 4: Get Client's Max-Age if Provided ---
    max_age_match = re.search(r"max-age=(\d+)", cache_control)
    client_ttl: Optional[int] = int(max_age_match.group(1)) if max_age_match else None
    if client_ttl is not None:
        logger.debug(f"Client requested max-age: {client_ttl} seconds")

    # --- Step 5: Construct Cache Keys ---
    cache_key = (
        f"cache:{request.url.path}"  # Key for storing the actual cached response
    )
    lock_key = (
        f"lock:{cache_key}"  # Key for the distributed lock to prevent cache stampedes
    )
    logger.info(f"Processing request: {request.url.path}")

    # --- Step 6: Attempt to Retrieve from Cache ---
    try:
        cached, is_stale, content_type = await cache.get(
            cache_key
        )  # Try to get the cached response, its staleness status, and content type
        logger.debug(
            f"Cache get result for {cache_key}: cached={cached is not None}, is_stale={is_stale}"
        )
        if cached is not None:
            cache_layer = (
                "L2" if cache.redis else "L1"
            )  # Determine which cache layer served the hit
            record_cache_hit(
                cache_layer
            )  # Increment the cache hit metric for the respective layer
            logger.info(
                f"{'Stale ' if is_stale else ''}Cache hit for: {cache_key}, layer={cache_layer}"
            )
            if is_stale:
                # Serve the stale data immediately to the client
                logger.debug(f"Scheduling background refresh task for: {cache_key}")
                background_tasks.add_task(
                    refresh_cache, cache, cache_key, lock_key, request.url.path
                )
                logger.debug(
                    f"Serving stale data after scheduling background refresh for: {cache_key}"
                )
            duration = time.time() - start_time
            observe_request_latency(duration)  # Record latency
            return Response(
                content=cached,
                media_type=content_type or "application/octet-stream",
                status_code=200,
            )  # Return the cached response with the correct content type
        record_cache_miss(
            "L2" if cache.redis else "L1"
        )  # Increment the cache miss metric
        logger.info(f"Cache miss for: {cache_key}")
    except RuntimeError as e:
        logger.error(f"Error during cache retrieval: {str(e)}")
        record_redis_error("RuntimeError")  # Record Redis-related runtime error
        response = await call_next(
            request
        )  # If cache retrieval fails, forward to origin
        duration = time.time() - start_time
        observe_request_latency(duration)  # Record latency
        return response
    except Exception as e:
        logger.error(
            f"Unexpected error during cache retrieval: {str(e)}", exc_info=True
        )
        record_redis_error("UnexpectedError")  # Record unexpected Redis error
        response = await call_next(
            request
        )  # If unexpected cache error, forward to origin
        duration = time.time() - start_time
        observe_request_latency(duration)  # Record latency
        return response

    # --- Step 7: Handle Cache Miss - Acquire Lock for Deduplication ---
    lock_value = await cache.acquire_lock(
        lock_key, timeout=10
    )  # Attempt to acquire a distributed lock
    logger.debug(
        f"Lock acquisition attempt for {lock_key}: acquired={lock_value is not None}"
    )
    if lock_value:
        try:
            # Double-check the cache after acquiring the lock to prevent race conditions
            cached, is_stale, content_type = await cache.get(cache_key)
            if cached is not None:
                cache_layer = "L2" if cache.redis else "L1"  # Determine cache layer
                record_cache_hit(cache_layer)  # Record cache hit
                logger.info(
                    f"Cache hit after lock acquisition for: {cache_key}, layer={cache_layer}"
                )
                duration = time.time() - start_time
                observe_request_latency(duration)  # Record latency
                return Response(
                    content=cached,
                    media_type=content_type or "application/octet-stream",
                    status_code=200,
                )
            # If still a miss after acquiring the lock, fetch data from the origin
            response = await fetch_and_return(request, cache, cache_key, client_ttl)
            duration = time.time() - start_time
            observe_request_latency(duration)  # Record latency
            return response
        finally:
            # Ensure the lock is released, regardless of success or failure
            await cache.release_lock(lock_key, lock_value)
    else:
        # If the lock couldn't be acquired (another request is likely fetching), wait and retry cache
        logger.debug(f"Lock held for {lock_key}, waiting 50ms to retry cache")
        await asyncio.sleep(0.05)
        cached, is_stale, content_type = await cache.get(cache_key)
        if cached is not None:
            cache_layer = "L2" if cache.redis else "L1"  # Determine cache layer
            record_cache_hit(cache_layer)  # Record cache hit
            logger.info(
                f"Cache hit after waiting for lock for: {cache_key}, layer={cache_layer}"
            )
            duration = time.time() - start_time
            observe_request_latency(duration)  # Record latency
            return Response(
                content=cached,
                media_type=content_type or "application/octet-stream",
                status_code=200,
            )
        logger.warning(f"No cache after waiting for lock, fetching from origin")
        response = await fetch_and_return(
            request, cache, None
        )  # Fallback to fetching from origin
        duration = time.time() - start_time
        observe_request_latency(duration)  # Record latency
        return response


async def fetch_and_return(
    request: Request,
    cache: Cache,
    cache_key: Optional[str],
    client_ttl: Optional[int] = None,
) -> Response:
    """
    Fetches data from the origin service, handles circuit breaker logic, caches the response, and returns it to the client.

    This function encapsulates the interaction with the origin, including error handling and integration
    with the circuit breaker to prevent further requests during an outage. It also determines the TTL for caching.
    """
    # --- Step 1: Check Circuit Breaker State ---
    if not circuit_breaker.can_attempt():
        logger.warning(
            f"Circuit breaker in OPEN state, attempting to serve stale data for {request.url.path}"
        )
        if cache_key:
            cached, is_stale, content_type = await cache.get(cache_key)
            if cached is not None:
                cache_layer = "L2" if cache.redis else "L1"  # Determine cache layer
                record_cache_hit(
                    cache_layer
                )  # Record cache hit (for serving stale data)
                logger.info(
                    f"Serving stale data due to circuit breaker OPEN state: {cache_key}, layer={cache_layer}"
                )
                return Response(
                    content=cached,
                    media_type=content_type or "application/octet-stream",
                    status_code=200,
                )
        logger.error(
            f"Circuit breaker in OPEN state and no stale data available for {request.url.path}"
        )
        return JSONResponse(content={"error": "Service Unavailable"}, status_code=503)

    try:
        # --- Step 2: Fetch Data from Origin ---
        origin_data = await fetch_origin(request.url.path)
        logger.debug(f"Origin response for {request.url.path}: {origin_data}")
        if "error" not in origin_data:
            try:
                content_type = origin_data.get(
                    "content_type", "application/octet-stream"
                )
                status_code = origin_data.get("status_code", 200)
                data = origin_data["data"]
                # --- Step 3: Calculate TTL for Caching ---
                ttl = (
                    client_ttl
                    if client_ttl is not None
                    else calculate_ttl(request.url.path, content_type, status_code)
                )
                logger.info(
                    f"Calculated TTL for {cache_key or request.url.path}: {ttl} seconds"
                )
                # --- Step 4: Cache the Response ---
                if cache_key and ttl > 0:
                    await cache.set(
                        cache_key, data, content_type, ttl=ttl
                    )  # Pass content_type to cache
                    logger.info(f"Cache set for: {cache_key}")
                # --- Step 5: Record Success in Circuit Breaker ---
                circuit_breaker.record_success()
                # --- Step 6: Return Origin Response ---
                return Response(
                    content=data, media_type=content_type, status_code=status_code
                )
            except Exception as e:
                logger.error(
                    f"Error processing origin response or setting cache: {str(e)}",
                    exc_info=True,
                )
                circuit_breaker.record_failure()  # Report failure to the circuit breaker
                return JSONResponse(
                    content={"error": "Invalid origin response"}, status_code=500
                )
        else:
            logger.warning(
                f"Origin error for {request.url.path}: {origin_data['error']}"
            )
            circuit_breaker.record_failure()  # Report failure to the circuit breaker
            return JSONResponse(
                content={"error": origin_data["error"]},
                status_code=origin_data["status_code"],
            )
    except Exception as e:
        logger.error(
            f"Origin fetch failed for {request.url.path}: {str(e)}", exc_info=True
        )
        circuit_breaker.record_failure()  # Report failure to the circuit breaker
        # --- Step 7: Fallback to Stale Data on Origin Failure ---
        if cache_key:
            cached, is_stale, content_type = await cache.get(cache_key)
            if cached is not None:
                cache_layer = "L2" if cache.redis else "L1"  # Determine cache layer
                record_cache_hit(
                    cache_layer
                )  # Record cache hit (for serving stale data)
                logger.info(
                    f"Serving stale data due to origin failure: {cache_key}, layer={cache_layer}"
                )
                return Response(
                    content=cached,
                    media_type=content_type or "application/octet-stream",
                    status_code=200,
                )
        return JSONResponse(content={"error": "Service Unavailable"}, status_code=503)


async def refresh_cache(cache: Cache, cache_key: str, lock_key: str, path: str) -> None:
    """
    Asynchronously refreshes the cache in the background for stale-while-revalidate.

    It attempts to acquire a lock to prevent multiple refreshes for the same key,
    checks the circuit breaker before attempting to fetch from the origin, and updates
    the cache with the fresh data if the origin call is successful.
    """
    logger.debug(f"Background refresh task started for path: {path}")
    try:
        lock_value = await cache.acquire_lock(lock_key, timeout=10)
        if not lock_value:
            logger.debug(
                f"Lock held for background refresh: {lock_key}, skipping refresh"
            )
            return
        try:
            # --- Step 1: Check Circuit Breaker State Before Refresh ---
            if not circuit_breaker.can_attempt():
                logger.warning(
                    f"Circuit breaker in OPEN state, skipping background refresh for {path}"
                )
                return
            # --- Step 2: Fetch Fresh Data from Origin ---
            logger.debug(f"Attempting background refresh for path: {path}")
            origin_data = await fetch_origin(path)
            if "error" not in origin_data:
                content_type = origin_data.get(
                    "content_type", "application/octet-stream"
                )
                status_code = origin_data.get("status_code", 200)
                ttl = calculate_ttl(path, content_type, status_code)
                # --- Step 3: Update Cache with Fresh Data ---
                await cache.set(
                    cache_key, origin_data["data"], content_type, ttl=ttl
                )  # Pass content_type to cache
                logger.info(f"Background cache refresh completed for: {cache_key}")
                # --- Step 4: Record Success in Circuit Breaker ---
                circuit_breaker.record_success()
            else:
                logger.warning(
                    f"Background refresh failed for {path}: {origin_data['error']}"
                )
                circuit_breaker.record_failure()
        except Exception as e:
            logger.error(
                f"Error during background cache refresh for {cache_key}: {str(e)}",
                exc_info=True,
            )
            circuit_breaker.record_failure()
        finally:
            await cache.release_lock(lock_key, lock_value)
            logger.debug(f"Background refresh completed for {cache_key}, lock released")
    except Exception as e:
        logger.error(
            f"Failed to execute background refresh task for {cache_key}: {str(e)}",
            exc_info=True,
        )
