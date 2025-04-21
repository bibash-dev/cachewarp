from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Any

from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
)  # Added for metrics endpoint
from fastapi.exceptions import RequestValidationError
from prometheus_client import (
    generate_latest,
    CONTENT_TYPE_LATEST,
)  # Import Prometheus utilities

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
        await cache.connect()  # Establish connection to Redis on startup
    except Exception as e:
        logger.error(f"Error during cache connection at startup: {e}", exc_info=True)
        # Consider if you want the app to start if cache connection fails
        # For now, we'll log and try to proceed (middleware will handle if Redis is None)
    yield  # Application starts here
    await cache.close()  # Close the Redis connection on shutdown
    logger.info("Shutting down CacheWarp application")


app = FastAPI(
    title="CacheWarp",
    lifespan=lifespan,  # Integrate the lifespan context manager for startup and shutdown
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
    for the stale while revalidate caching strategy.
    """
    try:
        return await caching_middleware(
            request, call_next, cache, background_tasks
        )  # Delegate caching logic to the middleware
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


@app.get("/metrics")
async def metrics() -> Response:
    """
    Exposes Prometheus metrics for scraping.

    Returns a plain text response containing all collected metrics in Prometheus format.
    """
    try:
        return PlainTextResponse(
            content=generate_latest(),  # Generate the latest metrics data
            media_type=CONTENT_TYPE_LATEST,  # Set the correct content type for Prometheus
        )
    except Exception as e:
        logger.error(f"Error generating Prometheus metrics: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500, content={"error": "Failed to generate metrics"}
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
            await cache.redis.ping()  # Send a ping command to check Redis connection
            redis_status = "connected"
    except Exception as e:
        logger.error(f"Redis ping failed during health check: {e}")

    status = {
        "status": "ok",
        "redis": redis_status,
    }
    logger.info(f"Health check: {status}")
    return status
