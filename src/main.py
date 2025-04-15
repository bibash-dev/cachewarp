from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from src.config import settings
from src.proxy.cache import Cache
from src.proxy.middleware import caching_middleware
from src.logging import logger

cache = Cache()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting CacheWarp application")
    await cache.connect()
    yield
    await cache.close()
    logger.info("Shutting down CacheWarp application")

app = FastAPI(
    title="CacheWarp",
    lifespan=lifespan,
)

@app.middleware("http")
async def apply_caching(request: Request, call_next):
    try:
        return await caching_middleware(request, call_next, cache)
    except RuntimeError as e:
        logger.error(f"Middleware error: {str(e)}")
        return await call_next(request)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"error": "Invalid request", "details": exc.errors()}
    )

@app.get("/health")
async def health():
    status = {
        "status": "ok",
        "redis": "connected" if cache.redis else "disconnected",
    }
    logger.info(f"Health check: {status}")
    return status