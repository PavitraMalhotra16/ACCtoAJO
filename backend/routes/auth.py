"""
Authentication routes for ACC (source) and AJO (destination).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import DestinationConnection, SourceConnection, UserSession, get_db
from core.security import encrypt, get_login_from_cookie
from services.acc_soap import (
    build_logon_envelope,
    build_test_cnx_envelope,
    parse_fault,
    parse_logon_response,
)

log = logging.getLogger("acc_backend.auth")
router = APIRouter()

SESSION_TTL_DAYS = 7
USER_COOKIE_TTL_DAYS = 365
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"


class AccConnectRequest(BaseModel):
    auth_type: str = "classic"
    instance_url: str
    login: str
    password: str


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str


@router.post("/api/acc/connect")
async def acc_connect(
    body: AccConnectRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    log.info("ACC login attempt – login=%s", body.login)
    soap_url = body.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            logon = await client.post(
                soap_url,
                content=build_logon_envelope(body.login, body.password),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "xtk:session#Logon"},
            )
        except httpx.RequestError:
            raise HTTPException(502, "Cannot reach Adobe Campaign Classic")

        if logon.status_code != 200:
            raise HTTPException(401, parse_fault(logon.text) or "Logon failed")

        session_token, security_token = parse_logon_response(logon.text)
        if not session_token:
            raise HTTPException(401, parse_fault(logon.text) or "Authentication failed")

        test = await client.post(
            soap_url,
            content=build_test_cnx_envelope(session_token, security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:session#TestCnx",
                "Cookie": f"__sessiontoken={session_token}",
                "X-Security-Token": security_token,
            },
        )
        if parse_fault(test.text):
            raise HTTPException(401, parse_fault(test.text))

    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == body.login))
    conn = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if conn:
        conn.encrypted_password = encrypt(body.password)
        conn.instance_url = body.instance_url
        conn.session_token = session_token
        conn.security_token = security_token
        conn.authenticated = True
        conn.last_authenticated_at = now
    else:
        conn = SourceConnection(
            login_id=body.login,
            instance_url=body.instance_url,
            encrypted_password=encrypt(body.password),
            session_token=session_token,
            security_token=security_token,
            authenticated=True,
            last_authenticated_at=now,
        )
        db.add(conn)

    session_id = str(uuid.uuid4())
    db.add(UserSession(
        id=session_id,
        login_id=body.login,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
    ))
    response.set_cookie(key="acc_session", value=session_id, httponly=True, samesite="lax",
                        max_age=SESSION_TTL_DAYS * 24 * 3600)
    response.set_cookie(key="acc_user", value=body.login, httponly=True, samesite="lax",
                        max_age=USER_COOKIE_TTL_DAYS * 24 * 3600)

    log.info("ACC authenticated – login=%s", body.login)
    return {"success": True, "authenticated": True}


@router.post("/api/acc/disconnect")
async def acc_disconnect(
    response: Response,
    acc_session: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    if acc_session:
        result = await db.execute(select(UserSession).where(UserSession.id == acc_session))
        session = result.scalar_one_or_none()
        if session:
            await db.delete(session)
    response.delete_cookie("acc_session")
    response.delete_cookie("acc_user")
    return {"success": True}


@router.get("/api/acc/status")
async def acc_status(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        return {"connected": False, "login": None}

    result = await db.execute(
        select(SourceConnection).where(
            SourceConnection.login_id == login_id,
            SourceConnection.authenticated == True,
        )
    )
    conn = result.scalar_one_or_none()
    return {"connected": conn is not None, "login": login_id if conn else None}


@router.post("/api/ajo/connect")
async def ajo_connect(
    body: AjoConnectRequest,
    db: AsyncSession = Depends(get_db),
):
    log.info("AJO connect attempt – orgId=%s", body.org_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            token_resp = await client.post(
                IMS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": body.client_id,
                    "client_secret": body.client_secret,
                    "scope": IMS_SCOPES,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.RequestError:
            raise HTTPException(502, "Cannot reach Adobe IMS")

    if token_resp.status_code != 200:
        raise HTTPException(401, "AJO authentication failed – check credentials")

    payload = token_resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise HTTPException(401, "IMS did not return an access token")

    expires_in = int(payload.get("expires_in", 3600))
    if expires_in > 86_400:
        expires_in //= 1000
    now = datetime.now(timezone.utc)
    token_expires_at = now + timedelta(seconds=expires_in)

    result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.org_id == body.org_id)
    )
    conn = result.scalar_one_or_none()
    encrypted_creds = encrypt(f"{body.client_id}:{body.client_secret}")
    encrypted_token = encrypt(access_token)

    if conn:
        conn.client_id = body.client_id
        conn.sandbox_name = body.sandbox_name
        conn.encrypted_credentials = encrypted_creds
        conn.encrypted_access_token = encrypted_token
        conn.token_expires_at = token_expires_at
        conn.authenticated = True
        conn.last_authenticated_at = now
    else:
        conn = DestinationConnection(
            org_id=body.org_id,
            client_id=body.client_id,
            sandbox_name=body.sandbox_name,
            encrypted_credentials=encrypted_creds,
            encrypted_access_token=encrypted_token,
            token_expires_at=token_expires_at,
            authenticated=True,
            last_authenticated_at=now,
        )
        db.add(conn)

    log.info("AJO authenticated – orgId=%s", body.org_id)
    return {"success": True, "authenticated": True, "expires_in": expires_in}


@router.get("/api/ajo/status")
async def ajo_status(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.authenticated == True)
    )
    conn = result.scalar_one_or_none()
    return {
        "connected": conn is not None,
        "org_id": conn.org_id if conn else None,
        "sandbox_name": conn.sandbox_name if conn else None,
    }


@router.get("/api/connections/status")
async def connections_status(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)

    src = dst = None
    if login_id:
        result = await db.execute(
            select(SourceConnection).where(
                SourceConnection.login_id == login_id,
                SourceConnection.authenticated == True,
            )
        )
        src = result.scalar_one_or_none()
        if src:
            result = await db.execute(
                select(DestinationConnection).where(DestinationConnection.authenticated == True)
            )
            dst = result.scalar_one_or_none()

    return {
        "sourceAuthenticated": src is not None,
        "destinationAuthenticated": dst is not None,
        "sourceLoginId": src.login_id if src else None,
        "destinationOrgId": dst.org_id if dst else None,
        "destinationSandboxName": dst.sandbox_name if dst else None,
    }
