"""
Application configuration – loaded once at import time from environment / .env file.
"""

from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Adobe Campaign Classic
    acc_endpoint: str = "http://127.0.0.1:8080/nl/jsp/soaprouter.jsp"
    soap_timeout: float = 30.0  # seconds

    # CORS – comma-separated origins e.g. "http://localhost:3000,https://app.example.com"
    cors_origins_raw: str = "http://localhost:3000"

    # General
    debug: bool = False
    secret_key: str = "change-me-in-production"  # used for future JWT / signed cookies

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# Module-level singleton so callers can do: from config import settings
settings = get_settings()
