"""
Application configuration – loaded once at import time from environment / .env file.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL  – asyncpg driver
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/acc_ajo"

    # Fernet encryption key for secrets stored in DB
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = "CHANGE_ME_generate_a_real_fernet_key"

    # Adobe Campaign Classic
    acc_endpoint: str = "http://127.0.0.1:8080/nl/jsp/soaprouter.jsp"
    soap_timeout: float = 30.0

    # CORS – comma-separated origins
    cors_origins_raw: str = "http://localhost:3000,http://localhost:5173"

    # Schema storage
    schema_storage_dir: str = "schema_files"

    # General
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
