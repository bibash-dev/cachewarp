import json
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .cache import Cache
from .origin import fetch_origin
from src.logging import logger

async def caching_middleware(request: Request, call_next, cache: Cache):
    if request.url.path == "/favicon.ico":
        return await call_next(request)

    logger.info(f"Processing request: {request.url.path}")
    if request.method != "GET":
        logger.debug("Non-GET request, bypassing cache")
        return await call_next(request)

    cache_key = f"cache:{request.url.path}"
    try:
        if cached := await cache.get(cache_key):
            logger.info(f"Cache hit: {cache_key}")
            return JSONResponse(content=cached)
        logger.info(f"Cache miss: {cache_key}")
    except Exception as e:
        logger.error(f"Cache get error: {str(e)}", exc_info=True)
        pass

    if request.url.path == "/health":
        return await call_next(request)

    origin_data = await fetch_origin(request.url.path)
    if "error" not in origin_data:
        try:
            await cache.set(cache_key, origin_data)
            logger.info(f"Cache set: {cache_key}")
        except Exception as e:
            logger.error(f"Cache set error: {str(e)}", exc_info=True)
            pass
        return JSONResponse(content=origin_data, status_code=200)

    logger.warning(f"Origin error: {origin_data['error']}")
    return JSONResponse(
        content=origin_data,
        status_code=404 if origin_data["error"] == "Not found" else 500
    )