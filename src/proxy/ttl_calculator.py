from typing import Optional
from fnmatch import fnmatch

from src.config import settings
from src.logging import logger

def calculate_ttl(path: str, content_type: Optional[str]) -> int:
    """ Calculate the TTL for a cache entry based on the request path and response content type."""
    # Step 1: Check path-based TTL rules
    for rule in settings.ttl_by_path_pattern:
        pattern = rule["pattern"]
        ttl = rule["ttl"]
        # Handle wildcard patterns (e.g., /static/*)
        if pattern.endswith("/*"):
            base_pattern = pattern[:-1]  # Remove "/*"
            if path.startswith(base_pattern.rstrip("*")):
                logger.debug(f"TTL matched path pattern {pattern}: {ttl} seconds")
                return ttl
        # Exact match for paths like /health
        elif path == pattern:
            logger.debug(f"TTL matched path pattern {pattern}: {ttl} seconds")
            return ttl

    # Step 2: Check content type-based TTL rules
    if content_type and content_type in settings.ttl_by_content_type:
        ttl = settings.ttl_by_content_type[content_type]
        logger.debug(f"TTL matched content type {content_type}: {ttl} seconds")
        return ttl

    # Step 3: Fallback to default TTL
    logger.debug(f"No TTL rules matched, using default TTL: {settings.cache_default_ttl} seconds")
    return settings.cache_default_ttl