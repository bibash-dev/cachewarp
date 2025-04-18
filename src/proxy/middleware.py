import json
import re
import asyncio
from fastapi import Request, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from typing import Optional

from .cache import Cache
from .origin import fetch_origin
from src.proxy.ttl_calculator import calculate_ttl
from src.logging import logger
from src.config import settings


async def caching_middleware(request: Request, call_next, cache: Cache, background_tasks: BackgroundTasks):
    """Middleware to handle caching of HTTP responses."""
    # Skip caching for specific paths defined in settings
    if request.url.path in settings.cache_skip_paths:
        logger.debug(f"Bypassing cache for excluded path: {request.url.path}")
        return await call_next(request)

    # Only cache GET requests
    if request.method != "GET":
        logger.debug(f"Bypassing cache for non-GET request: {request.method}")
        return await call_next(request)

    # Check Cache-Control header from the client
    cache_control = request.headers.get("Cache-Control", "").lower()
    if "no-cache" in cache_control or "no-store" in cache_control:
        logger.debug(f"Bypassing cache due to Cache-Control: {cache_control}")
        return await fetch_and_return(request, cache, None)

    # Try to get max-age from Cache-Control header
    max_age_match = re.search(r"max-age=(\d+)", cache_control)
    client_ttl: Optional[int] = int(max_age_match.group(1)) if max_age_match else None
    if client_ttl is not None:
        logger.debug(f"Client requested max-age: {client_ttl} seconds")

    # Construct cache keys
    cache_key = f"cache:{request.url.path}"
    lock_key = f"lock:{cache_key}"
    logger.info(f"Processing request: {request.url.path}")

    # Attempt to retrieve from cache
    try:
        cached, is_stale = await cache.get(cache_key)
        if cached is not None:
            logger.info(f"{'Stale ' if is_stale else ''}Cache hit for: {cache_key}")
            if is_stale:
                # Serve stale data and refresh in the background
                background_tasks.add_task(refresh_cache, cache, cache_key, lock_key, request.url.path)
                logger.debug(f"Serving stale data and scheduling background refresh for: {cache_key}")
            return JSONResponse(content=cached)
        logger.info(f"Cache miss for: {cache_key}")
    except RuntimeError as e:
        logger.error(f"Error during cache retrieval: {str(e)}")
        # If there's an error with the cache, proceed to fetch from origin
        return await call_next(request)
    except Exception as e:
        logger.error(f"Unexpected error during cache retrieval: {str(e)}", exc_info=True)
        # If there's an unexpected error with the cache, proceed to fetch from origin
        return await call_next(request)

    # Handle cache miss: Acquire lock to prevent cache stampede
    lock_value = await cache.acquire_lock(lock_key, timeout=10)
    if lock_value:
        try:
            # Double-check cache after acquiring the lock
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
    """Fetch data from the origin, cache the response if cache_key is provided, and return the response."""
    origin_data = await fetch_origin(request.url.path)
    if "error" not in origin_data:
        try:
            content_type = origin_data.get("content_type", "application/json")
            status_code = origin_data.get("status_code", 200)
            # Calculate TTL based on our rules and client's max-age
            ttl = client_ttl if client_ttl is not None else calculate_ttl(request.url.path, content_type, status_code)
            logger.info(f"Calculated TTL for {cache_key or request.url.path}: {ttl} seconds")
            if cache_key and ttl > 0:
                await cache.set(cache_key, origin_data["data"], ttl=ttl)
                logger.info(f"Cache set for: {cache_key}")
            return JSONResponse(content=origin_data["data"], status_code=status_code)
        except Exception as e:
            logger.error(f"Error processing origin response or setting cache: {str(e)}", exc_info=True)
            return JSONResponse(content={"error": "Invalid origin response"}, status_code=500)
    logger.warning(f"Origin error for {request.url.path}: {origin_data['error']}")
    return JSONResponse(
        content=origin_data,
        status_code=404 if origin_data["error"] == "Not found" else 500
    )


async def refresh_cache(cache: Cache, cache_key: str, lock_key: str, path: str):
    """Refresh cache in the background."""
    lock_value = await cache.acquire_lock(lock_key, timeout=10)
    if not lock_value:
        logger.debug(f"Lock held for background refresh: {lock_key}, skipping refresh")
        return
    try:
        origin_data = await fetch_origin(path)
        if "error" not in origin_data:
            content_type = origin_data.get("content_type", "application/json")
            status_code = origin_data.get("status_code", 200)
            ttl = calculate_ttl(path, content_type, status_code)
            await cache.set(cache_key, origin_data["data"], ttl=ttl)
            logger.info(f"Background cache refresh completed for: {cache_key}")
        else:
            logger.warning(f"Background refresh failed for {path}: {origin_data['error']}")
    except Exception as e:
        logger.error(f"Error during background cache refresh for {cache_key}: {str(e)}", exc_info=True)
    finally:
        await cache.release_lock(lock_key, lock_value)