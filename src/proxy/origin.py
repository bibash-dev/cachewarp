from aiohttp import ClientSession, ClientConnectorError, ClientResponseError

from src.config import settings
from src.logging import logger

async def fetch_origin(path: str) -> dict:
    """Fetch content from origin API, with mock fallback for MVP."""
    origin_url = str(settings.origin_url).rstrip('/')
    target_url = f"{origin_url}/{path.lstrip('/')}"
    logger.info(f"Fetching from origin: {target_url}")
    session = None
    try:
        session = ClientSession()
        response = await session.get(target_url)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        content_type = response.headers.get("Content-Type", "application/json")
        data = await response.json()
        logger.info(f"Origin fetch successful for {target_url}, Content-Type: {content_type}")
        return {
            "content_type": content_type,
            "data": data
        }
    except ClientResponseError as e:
        logger.warning(f"Origin failed with status {e.status} for {target_url}: {e}")
        if e.status == 404:
            return {"error": "Not found"}
        return {"error": f"Origin failed: {e.status}"}
    except ClientConnectorError as e:
        logger.error(f"Origin connection error for {target_url}: {str(e)}", exc_info=True)
        return _mock_response(path)
    except Exception as e:
        logger.error(f"An unexpected error occurred during origin fetch for {target_url}: {e}", exc_info=True)
        return {"error": "Unexpected error fetching from origin"}
    finally:
        if session:
            await session.close()

def _mock_response(path: str) -> dict:
    """Returns a mock response for the MVP."""
    logger.debug(f"Returning mock response for path: {path}")
    if path.startswith("/static/"):
        return {
            "content_type": "image/png",
            "data": {"mock_image": True, "path": path}
        }
    return {
        "content_type": "application/json",
        "data": {f"mock_response_for_{path.lstrip('/')}": True, "path": path}
    }