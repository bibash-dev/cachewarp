from typing import Optional
from fnmatch import fnmatch

from src.config import settings
from src.logging import logger


def calculate_ttl(path: str, content_type: Optional[str], status_code: Optional[int] = None) -> int:
    """
    Calculate the TTL for a cache entry based on request path, content type, and status code.
    Rules are checked in the following order: path patterns, status codes, content types, default.
    """
    logger.debug(f"Calculating TTL for path: '{path}', content_type: '{content_type}', status_code: '{status_code}'")

    # Step 1: Check path-based TTL rules (supports wildcards)
    logger.debug("Checking TTL rules based on path patterns...")
    for rule in settings.ttl_by_path_pattern:
        pattern = rule["pattern"]
        ttl = rule["ttl"]
        if pattern.endswith("/*"):
            base_pattern = pattern[:-2]  # Remove "/*"
            if path.startswith(base_pattern):
                logger.debug(f"TTL matched wildcard path pattern '{pattern}': {ttl} seconds")
                return ttl
        elif fnmatch(path, pattern):
            logger.debug(f"TTL matched path pattern '{pattern}': {ttl} seconds")
            return ttl

    # Step 2: Check status code-based TTL rules
    logger.debug("Checking TTL rules based on status code...")
    if status_code is not None and status_code in settings.ttl_by_status_code:
        ttl = settings.ttl_by_status_code[status_code]
        logger.debug(f"TTL matched status code '{status_code}': {ttl} seconds")
        return ttl

    # Step 3: Check content type-based TTL rules
    logger.debug("Checking TTL rules based on content type...")
    if content_type is not None and content_type in settings.ttl_by_content_type:
        ttl = settings.ttl_by_content_type[content_type]
        logger.debug(f"TTL matched content type '{content_type}': {ttl} seconds")
        return ttl

    # Step 4: Fallback to default TTL
    logger.debug(f"No specific TTL rules matched, using default TTL: {settings.cache_default_ttl} seconds")
    return settings.cache_default_ttl