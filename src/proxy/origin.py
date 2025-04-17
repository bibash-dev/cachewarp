from aiohttp import ClientSession, ClientConnectorError

from src.config import settings
from src.logging import logger

async def fetch_origin(path: str) -> dict:
    """Fetch JSON from origin API, with mock fallback for MVP."""
    logger.info(f"Fetching from origin: {path}")
    try:
        async with ClientSession() as session:
            url = f"{settings.origin_url.rstrip('/')}/{path.lstrip('/')}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Origin fetch successful: {path}")
                    return {
                        "content_type": "application/json",
                        "data": data
                    }
                logger.warning(f"Origin failed with status {response.status}: {path}")
                return {"error": f"Origin failed: {response.status}"}
    except ClientConnectorError as e:
        logger.error(f"Origin connection error: {str(e)}", exc_info=True)
        # Mock response for all paths during MVP
        logger.debug(f"Returning mock response for path: {path}")
        if path.startswith("/static/"):
            return {
                "content_type": "image/png",
                "data": {"data": "mock_image", "path": path}
            }
        return {
            "content_type": "application/json",
            "data": {"data": f"mock_response_for_{path.lstrip('/')}", "path": path}
        }