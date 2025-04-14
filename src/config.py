from pydantic import Field, RedisDsn, HttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    redis_url: RedisDsn = Field(default="redis://localhost:6379")
    origin_url: HttpUrl = Field(default="http://localhost:8080")
    cache_default_ttl: int = Field(default=30, ge=1, le=86400)  # TTL in seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        extra = "allow"

settings = Settings()