"""
Encryption and session resolution shared across all routes.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import SourceConnection, UserSession
from services.acc_soap import (
    build_logon_envelope,
    parse_fault,
    parse_logon_response,
)

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"

log = logging.getLogger("acc_backend.security")

SESSION_TTL_DAYS = 7

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
    acc_user: Optional[str] = None,  # kept for signature compatibility, not used
) -> Optional[str]:
    """
    Resolve login_id from acc_session cookie only.
    Extends the session TTL by SESSION_TTL_DAYS on every valid call (rolling window).
    Returns None if session is missing or expired — caller must return 401.
    """
    if not acc_session:
        return None

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserSession).where(
            UserSession.id == acc_session,
            UserSession.expires_at > now,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    # Rolling window: push expiry forward on every active request
    session.expires_at = now + timedelta(days=SESSION_TTL_DAYS)

    return session.login_id


async def get_valid_acc_token(conn: SourceConnection, db: AsyncSession) -> str:
    """
    Returns a valid ACC SOAP session token for any auth type.

    Classic: returns conn.session_token directly (no expiry tracking).

    Technical: returns conn.session_token (obtained via BearerTokenLogon at connect time).
    If the IMS token is expired or within 60s of expiry, silently:
      1. Re-calls Adobe IMS to get a fresh IMS access token
      2. Calls xtk:session#BearerTokenLogon on the ACC instance to exchange it
         for a fresh SOAP session_token + security_token
      3. Updates all four fields in DB and returns the new session_token

    In both paths the caller gets back a plain SOAP session token string — no
    branch needed in routes or SOAP envelope builders.
    """
    now = datetime.now(timezone.utc)

    if conn.auth_type != "technical":
        # Classic: re-Logon if session_expires_at is missing or within 60s of expiry
        needs_refresh = (
            not conn.session_expires_at
            or conn.session_expires_at <= now + timedelta(seconds=60)
        )
        if not needs_refresh:
            return conn.session_token or ""

        log.info("Classic SOAP session expired for login_id=%s — re-running Logon", conn.login_id)
        if not conn.encrypted_password:
            raise RuntimeError("Classic session expired and no stored password to re-authenticate with")

        password = decrypt(conn.encrypted_password)
        soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"

        async with httpx.AsyncClient(timeout=30.0) as client:
            logon_resp = await client.post(
                soap_url,
                content=build_logon_envelope(conn.login_id, password),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "xtk:session#Logon",
                },
            )

        fault = parse_fault(logon_resp.text)
        if logon_resp.status_code != 200 or fault:
            raise RuntimeError(f"Classic re-Logon failed: {fault or logon_resp.status_code}")

        session_token, security_token = parse_logon_response(logon_resp.text)
        if not session_token:
            raise RuntimeError("Classic re-Logon did not return a session token")

        conn.session_token = session_token
        conn.security_token = security_token or ""
        conn.session_expires_at = now + timedelta(hours=23)
        conn.last_authenticated_at = now
        await db.commit()

        log.info("Classic session refreshed for login_id=%s", conn.login_id)
        return session_token

    # Technical auth — return current IMS access_token if still valid
    if conn.token_expires_at and conn.token_expires_at > now + timedelta(seconds=60):
        return decrypt(conn.encrypted_access_token) if conn.encrypted_access_token else ""

    # IMS token expired — refresh from IMS only (no BearerTokenLogon)
    log.info("IMS token expired for login_id=%s — refreshing via IMS", conn.login_id)
    creds = decrypt(conn.encrypted_credentials)
    client_id, client_secret = creds.split(":", 1)

    async with httpx.AsyncClient(timeout=30.0) as client:
        ims_resp = await client.post(
            IMS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": IMS_SCOPES,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if ims_resp.status_code != 200:
        raise RuntimeError(f"IMS token refresh failed: {ims_resp.status_code} {ims_resp.text[:200]}")

    ims_payload = ims_resp.json()
    new_ims_token = ims_payload["access_token"]
    expires_in = int(ims_payload.get("expires_in", 3600))

    conn.encrypted_access_token = encrypt(new_ims_token)
    conn.token_expires_at = now + timedelta(seconds=expires_in)
    conn.last_authenticated_at = now
    await db.commit()

    log.info("IMS token refreshed for login_id=%s, expires_in=%ss", conn.login_id, expires_in)
    return new_ims_token


def acc_soap_headers(conn: "SourceConnection", token: str) -> dict:
    """
    Returns auth-specific HTTP headers for ACC SOAP calls.

    Classic: Cookie + X-Security-Token (session_token in envelope, security_token in header)
    Technical: Authorization: Bearer (IMS access_token in header, empty envelope sessiontoken)
    """
    if conn.auth_type == "technical":
        return {"Authorization": f"Bearer {token}"}
    return {
        "Cookie": f"__sessiontoken={token}",
        "X-Security-Token": conn.security_token or "",
    }
