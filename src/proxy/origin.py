import aiohttp
from aiohttp import ClientConnectorError
from src.logging import logger
from src.config import settings
from typing import Dict, Any

async def fetch_origin(path: str) -> Dict[str, Any]:
    """Fetch data from the origin server."""
    target_url = f"{settings.origin_url}{path}"
    logger.info(f"Fetching from origin: {target_url}")

    async with aiohttp.ClientSession() as session:
        try:
            response = await session.get(target_url)
            response.raise_for_status()
            data = await response.json()
            content_type = response.headers.get("Content-Type", "application/json")
            logger.info(f"Origin fetch successful for {target_url}, Content-Type: {content_type}")
            return {
                "content_type": content_type,
                "data": data,
                "status_code": response.status
            }
        except ClientConnectorError as e:
            logger.error(f"Origin connection error for {target_url}: {str(e)}", exc_info=True)
            # Do not fall back to mock response in production; let the caller handle the failure
            raise
        except aiohttp.ClientResponseError as e:
            logger.warning(f"Origin returned error for {target_url}: {e.status} {e.message}")
            return {
                "error": e.message,
                "status_code": e.status
            }
        except Exception as e:
            logger.error(f"Unexpected error fetching from origin {target_url}: {str(e)}", exc_info=True)
            return {
                "error": "Internal server error",
                "status_code": 500
            }

async def fetch_origin_with_mock(path: str) -> Dict[str, Any]:
    """Fetch data with mock fallback for testing purposes."""
    try:
        return await fetch_origin(path)
    except ClientConnectorError:
        logger.debug(f"Returning mock response for path: {path}")
        if path.startswith("/static/"):
            return {
                "content_type": "image/png",
                "data": {"mock_image": True, "path": path},
                "status_code": 200
            }
        return {
            "content_type": "application/json",
            "data": {f"mock_response_for_{path}": True, "path": path},
            "status_code": 200
        }