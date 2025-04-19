from typing import Optional, Any
from fnmatch import fnmatch
from typing import Dict, List, Union

from src.config import settings
from src.logging import logger


def calculate_ttl(
    path: str, content_type: Optional[str], status_code: Optional[int] = None
) -> int:
    """
    Calculates the Time-to-Live (TTL) for a cache entry in seconds.

    The TTL is determined based on a set of rules, checked in the following order:
    1. Path patterns (supports wildcard matching).
    2. HTTP status codes.
    3. Content types.
    4. A default TTL if no specific rule matches.

    Args:
        path (str): The request path.
        content_type (Optional[str]): The Content-Type header of the response (can be None).
        status_code (Optional[int]): The HTTP status code of the response (can be None).

    Returns:
        int: The calculated TTL in seconds.
    """
    logger.debug(
        f"Calculating TTL for path: '{path}', content_type: '{content_type}', status_code: '{status_code}'"
    )

    # --- Step 1: Check TTL rules based on path patterns ---
    logger.debug("Checking TTL rules based on path patterns...")
    for rule in settings.ttl_by_path_pattern:
        pattern: str = str(rule["pattern"])
        ttl_value: Union[str, int] = rule["ttl"]
        if isinstance(ttl_value, int):
            ttl = ttl_value
        else:
            try:
                ttl = int(ttl_value)
            except ValueError:
                logger.warning(
                    f"Invalid TTL value '{ttl_value}' for pattern '{pattern}', using default."
                )
                continue

        # Check for wildcard pattern matching (e.g., /static/*)
        if pattern.endswith("/*"):
            base_pattern = pattern[:-2]  # Remove "/*" to get the base path
            if path.startswith(base_pattern):
                logger.debug(
                    f"TTL matched wildcard path pattern '{pattern}': {ttl} seconds"
                )
                return ttl
        # Check for exact or fnmatch-style pattern matching
        elif fnmatch(path, pattern):
            logger.debug(f"TTL matched path pattern '{pattern}': {ttl} seconds")
            return ttl

    # --- Step 2: Check TTL rules based on HTTP status codes ---
    logger.debug("Checking TTL rules based on status code...")
    if status_code is not None and status_code in settings.ttl_by_status_code:
        ttl = settings.ttl_by_status_code[status_code]
        logger.debug(f"TTL matched status code '{status_code}': {ttl} seconds")
        return ttl

    # --- Step 3: Check TTL rules based on content type ---
    logger.debug("Checking TTL rules based on content type...")
    if content_type is not None and content_type in settings.ttl_by_content_type:
        ttl = settings.ttl_by_content_type[content_type]
        logger.debug(f"TTL matched content type '{content_type}': {ttl} seconds")
        return ttl

    # --- Step 4: Fallback to default TTL if no specific rule matched ---
    logger.debug(
        f"No specific TTL rules matched, using default TTL: {settings.cache_default_ttl} seconds"
    )
    return settings.cache_default_ttl