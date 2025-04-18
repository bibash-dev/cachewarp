import pytest
from httpx import AsyncClient
from src.proxy.cache import Cache
from src.config import settings
from typing import AsyncGenerator, Any


@pytest.fixture
async def cache() -> AsyncGenerator[Cache, None]:
    cache_instance = Cache()
    await cache_instance.connect()
    yield cache_instance
    await cache_instance.close()


@pytest.mark.asyncio
async def test_cache_control_no_cache(async_client: AsyncClient, cache: Cache) -> None:
    response = await async_client.get(
        "/some/path", headers={"Cache-Control": "no-cache"}
    )
    assert response.status_code == 200
    cached_data, _ = await cache.get("cache:/some/path")
    assert cached_data is None


@pytest.mark.asyncio
async def test_cache_control_max_age(async_client: AsyncClient, cache: Cache) -> None:
    response = await async_client.get(
        "/another/path", headers={"Cache-Control": "max-age=5"}
    )
    assert response.status_code == 200
    cached_data, _ = await cache.get("cache:/another/path")
    assert cached_data is not None
    await asyncio.sleep(6)
    response_again = await async_client.get(
        "/another/path", headers={"Cache-Control": "max-age=5"}
    )
    assert (
        response_again.status_code == 200
    )  # Might still hit stale depending on timing
    cached_data_again, is_stale = await cache.get("cache:/another/path")
    assert cached_data_again is not None


@pytest.mark.asyncio
async def test_stale_while_revalidate(async_client: AsyncClient, cache: Cache) -> None:
    # Initial request to cache
    response = await async_client.get("/yet/another", headers={})
    assert response.status_code == 200
    cached_data, _ = await cache.get("cache:/yet/another")
    assert cached_data is not None
    initial_data = response.json()

    # Wait for TTL to expire (default is 30, let's use slightly more)
    await asyncio.sleep(settings.cache_default_ttl + 1)

    # Subsequent request should serve stale data
    stale_response = await async_client.get("/yet/another", headers={})
    assert stale_response.status_code == 200
    stale_cached_data, is_stale = await cache.get("cache:/yet/another")
    assert is_stale is True
    assert stale_response.json() == initial_data  # Should be the stale data

    # Wait a bit for background refresh to complete (give it some time)
    await asyncio.sleep(0.5)  # Adjust as needed

    # Subsequent request should get fresh data
    fresh_response = await async_client.get("/yet/another", headers={})
    assert fresh_response.status_code == 200
    fresh_cached_data, is_stale_now = await cache.get("cache:/yet/another")
    assert is_stale_now is False
    assert (
        fresh_response.json() != initial_data
    )  # Assuming origin returns different data
