from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Any

from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from src.config import settings
from src.proxy.cache import Cache
from src.proxy.middleware import caching_middleware
from src.logging import logger

# Initialize the cache instance
cache: Cache = Cache()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Handles application startup and shutdown events.

    This context manager ensures that the Redis connection is established when
    the application starts and closed when it shuts down.
    """
    logger.info("Starting CacheWarp application")
    logger.info(f"Redis URL: {settings.redis_url}")
    logger.info(f"Default Cache TTL: {settings.cache_default_ttl} seconds")
    try:
        await cache.connect()
    except Exception as e:
        logger.error(f"Error during cache connection at startup: {e}", exc_info=True)
        # Consider if you want the app to start if cache connection fails
        # For now, we'll log and try to proceed (middleware will handle if Redis is None)
    yield
    await cache.close()
    logger.info("Shutting down CacheWarp application")


app = FastAPI(
    title="CacheWarp",
    lifespan=lifespan,
)


@app.middleware("http")
async def apply_caching(
    request: Request,
    call_next: Callable[[Request], Any],
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> Response:
    """
    Applies the caching middleware to all HTTP requests.

    This middleware intercepts HTTP requests and attempts to serve responses
    from the cache. For cache misses, it forwards the request to the next
    handler and then caches the response. It also utilizes BackgroundTasks
    for the stale-while-revalidate caching strategy.
    """
    try:
        return await caching_middleware(request, call_next, cache, background_tasks)
    except RuntimeError as e:
        logger.error(
            f"Cache runtime error in middleware (e.g., Redis not connected): {str(e)}"
        )
        return await call_next(
            request
        )  # Proceed without caching if there's a cache issue
    except Exception as e:
        logger.error(f"Unexpected error in caching middleware: {str(e)}", exc_info=True)
        return await call_next(request)  # Proceed without caching on unexpected error


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handles all unhandled exceptions that occur within the application.

    This ensures that the application returns a consistent JSON error response
    for unexpected errors, rather than crashing.
    """
    logger.error(
        f"Unhandled exception for URL: {request.url} - {str(exc)}", exc_info=True
    )
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handles request validation errors raised by FastAPI's data validation.

    This returns a JSON response with a 422 status code and details about
    the validation errors.
    """
    logger.error(f"Validation error for URL: {request.url} - {exc.errors()}")
    return JSONResponse(
        status_code=422, content={"error": "Invalid request", "details": exc.errors()}
    )


@app.get("/favicon.ico")
async def favicon() -> Response:
    """
    Returns a 204 No Content response for requests to /favicon.ico.

    Browsers often automatically request this file, and we can safely ignore it.
    """
    return Response(status_code=204)  # No Content


@app.get("/health")
async def health() -> dict[str, str]:
    """
    Performs a health check for the application.

    This endpoint checks if the application is running and if the connection
    to the Redis cache is healthy.
    """
    redis_status = "disconnected"
    try:
        if cache.redis:
            await cache.redis.ping()
            redis_status = "connected"
    except Exception as e:
        logger.error(f"Redis ping failed during health check: {e}")

    status = {
        "status": "ok",
        "redis": redis_status,
    }
    logger.info(f"Health check: {status}")
    return status