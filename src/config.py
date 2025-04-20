from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, RedisDsn
from typing import List, Dict
from src.logging import logger  # Import logger to debug


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and defaults.

    This class defines all the configurable parameters for the cachewarp proxy,
    including connection details for Redis and the origin API, various cache
    behavior settings (TTLs, sizes, skip paths), and circuit breaker configurations.
    Pydantic's `BaseSettings` provides automatic loading of these settings from
    environment variables, with defaults specified as class attributes.
    """

    # Redis Configuration
    redis_url: RedisDsn = Field(
        default=RedisDsn("redis://redis:6379"),
        description="URL for connecting to the Redis server. Supports various schemes (e.g., redis://, rediss://).",
    )

    # Origin API Configuration
    origin_url: str = Field(
        default="http://origin:8080",
        description="Base URL of the origin API server that the proxy will forward requests to.",
    )

    # Default Cache Behavior
    cache_default_ttl: int = Field(
        default=30,
        ge=1,
        description="Default Time-to-Live (in seconds) for cached responses when no specific rule applies.",
    )

    # Cache Skipping
    cache_skip_paths: List[str] = Field(
        default=["/favicon.ico", "/health", "/metrics"],
        description="List of URL paths for which caching will be completely bypassed. Useful for dynamic endpoints or static assets that should always be fresh.",
    )

    # L1 (In Memory) Cache Configuration
    l1_cache_maxsize: int = Field(
        default=1000,
        ge=1,
        description="Maximum number of items to store in the L1 in memory cache. When this limit is reached, older entries are evicted based on the cache's eviction policy (usually LRU).",
    )

    # Dynamic TTL Rules
    ttl_by_content_type: Dict[str, int] = Field(
        default={
            "application/json": 30,
            "image/png": 300,
            "text/html": 60,
        },
        description="Dictionary defining TTLs (in seconds) for different Content-Type headers of the origin response. This allows fine grained control over how long different types of content are cached.",
    )

    ttl_by_path_pattern: List[Dict[str, str | int]] = Field(
        default=[
            {"pattern": "/health", "ttl": 5},
            {"pattern": "/static/*", "ttl": 600},
        ],
        description="List of rules that define TTLs (in seconds) based on URL path patterns. Supports wildcard matching (e.g., '/api/*' or '/static/*.js'). The rules are evaluated in order.",
    )

    ttl_by_status_code: Dict[int, int] = Field(
        default={200: 5, 404: 10, 500: 0},
        description="Dictionary defining TTLs (in seconds) for different HTTP status codes returned by the origin server. For example, you might want to cache successful responses for a short time and not cache error responses.",
    )

    # Stale While Revalidate Configuration
    stale_ttl_offset: int = Field(
        default=30,
        ge=0,
        description="Additional TTL (in seconds) to keep stale data in the cache while a background refresh is attempted. This improves perceived performance by serving potentially outdated content quickly.",
    )

    # Circuit Breaker Configuration
    circuit_breaker_failure_threshold: int = Field(
        default=3,
        ge=1,
        description="Number of consecutive failures when connecting to the origin API before the circuit breaker trips into the 'OPEN' state.",
    )
    circuit_breaker_recovery_timeout: int = Field(
        default=30,
        ge=1,
        description="Time (in seconds) the circuit breaker remains in the 'OPEN' state before allowing a single 'half open' attempt to check if the origin has recovered.",
    )

    # Pydantic Configuration
    model_config = SettingsConfigDict(
        env_file=".env",  # Load settings from a .env file
        env_file_encoding="utf-8",  # Encoding for the .env file
        case_sensitive=True,  # Environment variable names are case-sensitive
        validate_assignment=True,  # Validate values when assigning to fields
        extra="allow",  # Allow extra fields in the environment variables (they won't be mapped to the model)
    )


# Instantiate the Settings class, which will load configurations from the environment
# and use the default values defined above.
settings = Settings()
