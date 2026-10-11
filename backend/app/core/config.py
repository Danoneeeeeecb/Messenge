from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Realtime Messenger"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite+aiosqlite:///./messenger.db"
    cors_origins: str = "http://localhost:5173"
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=20, ge=1, le=120)
    message_max_length: int = Field(default=10_000, ge=1, le=10_000)
    message_rate_limit_count: int = Field(default=10, ge=1)
    message_rate_limit_window_seconds: int = Field(default=10, ge=1)
    websocket_max_message_bytes: int = Field(default=16_384, ge=1_024, le=1_048_576)
    attachment_storage_path: str = "uploads"
    attachment_max_size_bytes: int = Field(default=10_485_760, ge=1_024, le=104_857_600)
    max_websocket_connections_per_user: int = Field(default=5, ge=1, le=100)
    user_search_rate_limit_count: int = Field(default=30, ge=1)
    user_search_rate_limit_window_seconds: int = Field(default=60, ge=1)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Values are loaded from environment by pydantic-settings.
