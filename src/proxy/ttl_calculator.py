from typing import Optional, Any
from fnmatch import fnmatch
from typing import Dict, List, Union

from src.config import settings
from src.logging import logger


def calculate_ttl(
    path: str, content_type: Optional[str], status_code: Optional[int] = None
) -> int:
    """
    Calculates the Time-to-Live (TTL) in seconds for a cache entry.

    The TTL is determined by evaluating a series of rules based on the
    request path, the Content-Type of the response, and the HTTP status code.
    These rules are checked in a specific order of precedence:

    1. **Path Patterns:** Rules defined using wildcard patterns to match request paths.
    2. **HTTP Status Codes:** Rules associated with specific HTTP status codes.
    3. **Content Types:** Rules based on the Content-Type header of the response.
    4. **Default TTL:** A fallback TTL used if no other rule matches.

    Args:
        path (str): The request path (e.g., '/api/data' or '/static/image.png').
        content_type (Optional[str]): The Content-Type header of the HTTP response
                                       (e.g., 'application/json', 'image/png'). Can be None.
        status_code (Optional[int]): The HTTP status code of the response (e.g., 200, 404).
                                     Can be None.

    Returns:
        int: The calculated TTL in seconds. A non-positive value indicates that the
             resource should not be cached (or should use a very short TTL).
    """
    logger.debug(
        f"Calculating TTL for path: '{path}', content_type: '{content_type}', status_code: '{status_code}'"
    )

    # --- Step 1: Check TTL rules based on defined path patterns ---
    logger.debug("Checking TTL rules based on path patterns...")
    for rule in settings.ttl_by_path_pattern:
        pattern: str = str(rule["pattern"])  # The wildcard pattern to match against the path
        ttl_value: Union[str, int] = rule["ttl"]  # The TTL value associated with the pattern

        # Ensure the TTL value is an integer
        if isinstance(ttl_value, int):
            ttl = ttl_value
        else:
            try:
                ttl = int(ttl_value)
            except ValueError:
                logger.warning(
                    f"Invalid TTL value '{ttl_value}' for pattern '{pattern}', skipping this rule."
                )
                continue  # Move to the next TTL rule

        # Implement wildcard matching for paths (e.g., '/static/*')
        if pattern.endswith("/*"):
            base_pattern = pattern[:-2]  # Extract the base path (remove '/*')
            if path.startswith(base_pattern):
                logger.debug(
                    f"TTL matched wildcard path pattern '{pattern}': {ttl} seconds"
                )
                return ttl  # Return the TTL if the path starts with the base pattern
        # Implement more general pattern matching using fnmatch (supports more complex patterns)
        elif fnmatch(path, pattern):
            logger.debug(f"TTL matched path pattern '{pattern}': {ttl} seconds")
            return ttl  # Return the TTL if the path matches the pattern

    # --- Step 2: Check TTL rules based on HTTP status codes ---
    logger.debug("Checking TTL rules based on status code...")
    if status_code is not None and status_code in settings.ttl_by_status_code:
        ttl = settings.ttl_by_status_code[status_code]  # Retrieve TTL for the given status code
        logger.debug(f"TTL matched status code '{status_code}': {ttl} seconds")
        return ttl  # Return the TTL if the status code matches a defined rule

    # --- Step 3: Check TTL rules based on content type ---
    logger.debug("Checking TTL rules based on content type...")
    if content_type is not None and content_type in settings.ttl_by_content_type:
        ttl = settings.ttl_by_content_type[content_type]  # Retrieve TTL for the given content type
        logger.debug(f"TTL matched content type '{content_type}': {ttl} seconds")
        return ttl  # Return the TTL if the content type matches a defined rule

    # --- Step 4: Fallback to the default TTL if no specific rule was matched ---
    logger.debug(
        f"No specific TTL rules matched, using default TTL: {settings.cache_default_ttl} seconds"
    )
    return settings.cache_default_ttl  # Return the default TTL defined in the application settings