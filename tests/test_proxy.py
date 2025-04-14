import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.proxy.cache import Cache

@pytest.fixture(scope="module")
async def cache():
    """Async cache fixture."""
    cache = Cache()
    await cache.connect()
    yield cache
    await cache.close()

@pytest.fixture(scope="module")
def client():
    """Standard TestClient fixture."""
    with TestClient(app) as client:
        yield client

@pytest.mark.asyncio(loop_scope="module")
async def test_caching_flow(cache, client):
    """Async test to verify caching behavior."""
    # Clear cache
    await cache.redis.flushdb()

    # First request (cache miss)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify caching occurred
    cached_data = await cache.get("cache:/health")
    assert cached_data is not None, "Cache miss, no data found for key 'cache:/health'"
    assert cached_data["status"] == "ok"

    # Second request (cache hit)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
