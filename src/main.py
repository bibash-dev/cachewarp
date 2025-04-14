from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from src.config import settings
from src.proxy.cache import Cache
from src.proxy.middleware import caching_middleware

cache = Cache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache.connect()
    yield
    await cache.close()


app = FastAPI(
    title="CacheWarp",
    lifespan=lifespan,
)


@app.middleware("http")
async def apply_caching(request: Request, call_next):
    try:
        return await caching_middleware(request, call_next, cache)
    except RuntimeError:
        return await call_next(request)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "redis": "connected" if cache.redis else "disconnected",
    }
