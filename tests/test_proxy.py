import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from src.main import app
from src.proxy.cache import Cache
from unittest.mock import AsyncMock, patch

@pytest_asyncio.fixture(scope="module")
async def cache():
    """Async cache fixture."""
    cache = Cache()
    await cache.connect()
    yield cache
    await cache.close()

@pytest_asyncio.fixture(scope="module")
def client():
    """Standard TestClient fixture."""
    return TestClient(app)

@pytest.mark.asyncio(loop_scope="module")
async def test_origin_flow(cache, client):
    """Test origin fetch and caching for /mock."""
    mock_response = {"data": "mock"}
    error_404 = {"error": "Not found"}
    error_unreachable = {"error": "Origin unreachable"}

    await cache.redis.flushdb()

    # Cache miss → origin success
    with patch("src.proxy.origin.fetch_origin", AsyncMock(return_value=mock_response)) as mocked:
        resp = client.get("/mock")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.json() == mock_response
        assert mocked.called, "fetch_origin was not called"

        cached = await cache.get("cache:/mock")
        assert cached == mock_response, "Cache miss for /mock"

        resp = client.get("/mock")
        assert resp.status_code == 200
        assert resp.json() == mock_response

    # Origin 404
    with patch("src.proxy.origin.fetch_origin", AsyncMock(return_value=error_404)):
        resp = client.get("/missing")
        assert resp.status_code == 404
        assert resp.json() == error_404

        cached = await cache.get("cache:/missing")
        assert cached is None, "Unexpected cache for /missing"

    # Origin unreachable (mocked)
    with patch("src.proxy.origin.fetch_origin", AsyncMock(return_value=error_unreachable)):
        resp = client.get("/unreachable")
        assert resp.status_code == 500
        assert resp.json() == error_unreachable

        cached = await cache.get("cache:/unreachable")
        assert cached is None, "Unexpected cache for /unreachable"