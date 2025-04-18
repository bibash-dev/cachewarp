from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, RedisDsn
from typing import List, Dict


class Settings(BaseSettings):
    # Redis connection URL
    redis_url: RedisDsn = Field(
        default="redis://localhost:6379",
        description="Redis connection URL"
    )

    # Origin API URL
    origin_url: str = Field(
        default="http://localhost:8080",
        description="API origin URL"
    )

    # Default cache TTL in seconds
    cache_default_ttl: int = Field(
        default=30,
        ge=1,
        description="Default Time-to-Live for cache in seconds"
    )

    # Paths to skip caching
    cache_skip_paths: List[str] = Field(
        default=["/favicon.ico", "/health", "/metrics"],
        description="URL paths to bypass caching"
    )

    # L1 cache maximum size
    l1_cache_maxsize: int = Field(
        default=1000,
        ge=1,
        description="Maximum number of items in the L1 in-memory cache"
    )

    # Dynamic TTL rules based on content type
    ttl_by_content_type: Dict[str, int] = Field(
        default={
            "application/json": 30,
            "image/png": 300,
            "text/html": 60,
        },
        description="TTL in seconds for different content types"
    )

    # Dynamic TTL rules based on path patterns
    ttl_by_path_pattern: List[Dict[str, str | int]] = Field(
        default=[
            {"pattern": "/health", "ttl": 5},
            {"pattern": "/static/*", "ttl": 600},
        ],
        description="TTL in seconds for specific path patterns"
    )

    # Dynamic TTL rules based on HTTP status codes
    ttl_by_status_code: Dict[int, int] = Field(
        default={
            200: 5,
            404: 10,
            500: 0
        },
        description="TTL in seconds for different HTTP status codes"
    )

    # Configuration settings
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        validate_assignment=True,
        extra="allow"
    )


# Initialize the settings instance
settings = Settings()