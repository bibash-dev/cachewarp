import aiohttp
from aiohttp import ClientConnectorError
from src.logging import logger
from src.config import settings
from src.proxy.metrics import record_origin_error  # Import metrics
from typing import Dict, Any


async def fetch_origin(path: str) -> Dict[str, Any]:
    """
    Asynchronously fetches data from the configured origin server.

    It constructs the target URL using the application's `origin_url` setting
    and the requested path. For paths starting with '/static', it adjusts the
    URL to remove the '/static' prefix before making the request to the origin.
    Handles potential connection errors and HTTP errors from the origin.
    """
    target_url = f"{settings.origin_url}{path}"
    # Strip '/static' prefix from the request path to match origin's file structure
    if path.startswith("/static"):
        target_url = f"{settings.origin_url}/{path[len('/static/'):]}"
    logger.info(f"Fetching from origin: {target_url}")

    async with aiohttp.ClientSession() as session:
        try:
            response = await session.get(target_url)
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
            # Assuming the origin serves text-based content (text files, JSON, etc.)
            data = await response.read()  # Read the response body as bytes
            content_type = response.headers.get("Content-Type", "text/plain")
            logger.info(
                f"Origin fetch successful for {target_url}, Content-Type: {content_type}"
            )
            return {
                "content_type": content_type,
                "data": data.decode("utf-8"),  # Decode the bytes to a string
                "status_code": response.status,
            }
        except ClientConnectorError as e:
            logger.error(
                f"Origin connection error for {target_url}: {str(e)}", exc_info=True
            )
            record_origin_error(
                "ClientConnectorError"
            )  # Record the connection error metric
            raise  # Re-raise the exception to be handled by the caller
        except aiohttp.ClientResponseError as e:
            logger.warning(
                f"Origin returned error for {target_url}: {e.status} {e.message}"
            )
            record_origin_error(
                "ClientResponseError"
            )  # Record the client response error metric
            return {"error": e.message, "status_code": e.status}
        except Exception as e:
            logger.error(
                f"Unexpected error fetching from origin {target_url}: {str(e)}",
                exc_info=True,
            )
            record_origin_error("UnexpectedError")  # Record the unexpected error metric
            return {"error": "Internal server error", "status_code": 500}


async def fetch_origin_with_mock(path: str) -> Dict[str, Any]:
    """
    Asynchronously fetches data, but falls back to mock responses for testing purposes
    if a connection to the origin cannot be established.

    This is particularly useful for development and testing environments where the
    origin server might not always be running or accessible. It provides predefined
    responses based on the requested path.
    """
    try:
        return await fetch_origin(path)  # Attempt to fetch from the real origin first
    except ClientConnectorError:
        logger.debug(f"Returning mock response for path: {path}")
        if path.startswith("/static/"):
            # Mock response for static content (e.g., images)
            return {
                "content_type": "image/png",
                "data": {"mock_image": True, "path": path},
                "status_code": 200,
            }
        # Default mock response for other paths (e.g., JSON data)
        return {
            "content_type": "application/json",
            "data": {f"mock_response_for_{path}": True, "path": path},
            "status_code": 200,
        }
