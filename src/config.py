from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, HttpUrl, RedisDsn


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
