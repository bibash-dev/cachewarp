from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from src.config import settings
from src.proxy.cache import Cache
from src.proxy.middleware import caching_middleware
from src.logging import logger

# Initialize the cache instance
cache = Cache()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
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
async def apply_caching(request: Request, call_next, background_tasks: BackgroundTasks = BackgroundTasks()):
    """Applies the caching middleware to all HTTP requests.

    Utilizes BackgroundTasks for stale-while-revalidate functionality.
    """
    try:
        return await caching_middleware(request, call_next, cache, background_tasks)
    except RuntimeError as e:
        logger.error(f"Cache runtime error in middleware (e.g., Redis not connected): {str(e)}")
        return await call_next(request) # Proceed without caching if there's a cache issue
    except Exception as e:
        logger.error(f"Unexpected error in caching middleware: {str(e)}", exc_info=True)
        return await call_next(request) # Proceed without caching on unexpected error

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handles all unhandled exceptions."""
    logger.error(f"Unhandled exception for URL: {request.url} - {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles request validation errors."""
    logger.error(f"Validation error for URL: {request.url} - {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"error": "Invalid request", "details": exc.errors()}
    )

@app.get("/favicon.ico")
async def favicon():
    """Returns a 204 No Content for favicon requests."""
    return Response(status_code=204)  # No Content

@app.get("/health")
async def health():
    """Performs a health check, including Redis connection status."""
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