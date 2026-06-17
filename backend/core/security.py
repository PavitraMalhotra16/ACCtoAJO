"""
Encryption and session resolution shared across all routes.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import SourceConnection, UserSession

log = logging.getLogger("acc_backend.security")

_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise RuntimeError(
        "ENCRYPTION_KEY not set in .env – generate one with: "
        "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
fernet = Fernet(_key.encode())


def encrypt(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return fernet.decrypt(value.encode()).decode()


async def get_login_from_cookie(
    acc_session: Optional[str],
    db: AsyncSession,
    acc_user: Optional[str] = None,
) -> Optional[str]:
    if acc_session:
        result = await db.execute(
            select(UserSession).where(
                UserSession.id == acc_session,
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
        session = result.scalar_one_or_none()
        if session:
            return session.login_id

    if acc_user:
        result = await db.execute(
            select(SourceConnection).where(
                SourceConnection.login_id == acc_user,
                SourceConnection.authenticated == True,
            )
        )
        conn = result.scalar_one_or_none()
        if conn:
            log.info("Auto-restored session from DB for loginId=%s", acc_user)
            return acc_user

    return None
