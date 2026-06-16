"""
Loads AJO/AEP credentials from a .env file (or the process environment).

Values are read once at import time. The .env file lives at the backend root
and is git-ignored — secrets are never committed and never written to the DB.
Request payloads may still override any of these per-call.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from app.services.ajo_profile_lookup import (
    DEFAULT_AEP_BASE_URL,
    DEFAULT_IMS_TOKEN_URL,
    DEFAULT_SCOPES,
)

# backend/app/config.py -> backend/.env
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


class Settings:
    """Credential defaults sourced from the environment / .env file."""

    client_id: str | None = os.getenv("AJO_CLIENT_ID")
    client_secret: str | None = os.getenv("AJO_CLIENT_SECRET")
    ims_org_id: str | None = os.getenv("AJO_ORG_ID")
    sandbox_name: str = os.getenv("AJO_SANDBOX", "prod")
    scopes: str = os.getenv("AJO_SCOPES", DEFAULT_SCOPES)
    ims_token_url: str = os.getenv("AJO_IMS_TOKEN_URL", DEFAULT_IMS_TOKEN_URL)
    aep_base_url: str = os.getenv("AJO_AEP_BASE_URL", DEFAULT_AEP_BASE_URL)
    reference_access_token: str | None = os.getenv("AJO_REFERENCE_ACCESS_TOKEN")


settings = Settings()
