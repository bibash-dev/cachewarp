from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, HttpUrl, RedisDsn
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
        ge=1,  # Minimum value constraint
        description="Default Time-to-Live for cache in seconds"
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
            "application/json": 30,  # JSON responses (e.g., API data)
            "image/png": 300,  # Images (longer TTL due to static nature)
            "text/html": 60,  # HTML pages
        },
        description="TTL in seconds for different content types"
    )

    # Dynamic TTL rules based on path patterns (e.g., /health, /static/*)
    ttl_by_path_pattern: List[Dict[str, str | int]] = Field(
        default=[
            {"pattern": "/health", "ttl": 5},
            {"pattern": "/static/*", "ttl": 600},
        ],
        description="TTL in seconds for specific path patterns"
    )

    # Configuration settings
    model_config = SettingsConfigDict(
        env_file=".env",  # Use .env file for environment variables
        env_file_encoding="utf-8",  # Define encoding for the env file
        case_sensitive=True,  # Case-sensitive environment variables
        validate_assignment=True,  # Validate fields during runtime assignments
        extra="allow"  # Allow additional fields not defined in the model
    )


# Initialize the settings instance
settings = Settings()
