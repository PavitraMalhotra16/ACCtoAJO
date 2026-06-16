import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import httpx
from cryptography.fernet import Fernet
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timedelta

from acc_soap import (
    build_list_schemas_envelope,
    build_logon_envelope,
    build_test_cnx_envelope,
    parse_fault,
    parse_logon_response,
    parse_schemas,
)
from db import DestinationConnection, SourceConnection, UserSession, get_db, init_db, AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("acc_backend")

ACC_ENDPOINT = "http://127.0.0.1:8080/nl/jsp/soaprouter.jsp"
CORS_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

# Encryption key – in production load from environment variable
import os
_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("ENCRYPTION_KEY not set in .env – run: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
fernet = Fernet(_key.encode())

SESSION_TTL_DAYS = 7
USER_COOKIE_TTL_DAYS = 365  # long-lived identity cookie


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc))
        )
        expired = result.scalars().all()
        for s in expired:
            await db.delete(s)
        await db.commit()
        if expired:
            log.info("Cleaned up %d expired session(s)", len(expired))
    log.info("DB tables ready")
    yield


app = FastAPI(title="ACC→AJO Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def encrypt(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


async def get_login_from_cookie(
    acc_session: Optional[str],
    db: AsyncSession,
    acc_user: Optional[str] = None,
) -> Optional[str]:
    # 1. Try short-lived session cookie first
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

    # 2. Session missing/expired – fall back to long-lived identity cookie
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


# ── Schemas ──────────────────────────────────────────────────────────────────

class AccLoginRequest(BaseModel):
    loginId: str
    password: str


class AjoLoginRequest(BaseModel):
    orgId: str
    clientId: str
    clientSecret: str
    sandboxName: str


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str


# ── Routes ───────────────────────────────────────────────────────────────────

@app.post("/api/source/authenticate")
async def source_authenticate(
    body: AccLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    log.info("ACC login attempt – loginId=%s", body.loginId)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Logon
        try:
            logon = await client.post(
                ACC_ENDPOINT,
                content=build_logon_envelope(body.loginId, body.password),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "xtk:session#Logon"},
            )
        except httpx.RequestError:
            raise HTTPException(502, "Cannot reach Adobe Campaign Classic")

        if logon.status_code != 200:
            raise HTTPException(401, parse_fault(logon.text) or "Logon failed")

        session_token, security_token = parse_logon_response(logon.text)
        if not session_token:
            raise HTTPException(401, parse_fault(logon.text) or "Authentication failed")

        # TestCnx
        test = await client.post(
            ACC_ENDPOINT,
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

    # Save to DB
    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == body.loginId))
    conn = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if conn:
        conn.encrypted_password = encrypt(body.password)
        conn.session_token = session_token
        conn.security_token = security_token
        conn.authenticated = True
        conn.last_authenticated_at = now
    else:
        conn = SourceConnection(
            login_id=body.loginId,
            encrypted_password=encrypt(body.password),
            session_token=session_token,
            security_token=security_token,
            authenticated=True,
            last_authenticated_at=now,
        )
        db.add(conn)

    # Create DB-backed session
    session_id = str(uuid.uuid4())
    db.add(UserSession(
        id=session_id,
        login_id=body.loginId,
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
    ))
    # Short-lived session cookie (7 days)
    response.set_cookie(
        key="acc_session", value=session_id,
        httponly=True, samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
    )
    # Long-lived identity cookie (1 year) – lets backend skip login on return visits
    response.set_cookie(
        key="acc_user", value=body.loginId,
        httponly=True, samesite="lax",
        max_age=USER_COOKIE_TTL_DAYS * 24 * 3600,
    )

    log.info("ACC authenticated – loginId=%s", body.loginId)
    return {"success": True, "authenticated": True}


@app.post("/api/destination/authenticate")
async def destination_authenticate(
    body: AjoLoginRequest,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Authenticate source first")

    log.info("AJO login attempt – orgId=%s", body.orgId)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            token_resp = await client.post(
                "https://ims-na1.adobelogin.com/ims/token/v3",
                data={
                    "grant_type": "client_credentials",
                    "client_id": body.clientId,
                    "client_secret": body.clientSecret,
                    "scope": "openid,AdobeID,read_organizations",
                },
            )
        except httpx.RequestError:
            raise HTTPException(502, "Cannot reach Adobe IMS")

    if token_resp.status_code != 200:
        raise HTTPException(401, "AJO authentication failed – check credentials")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(401, "IMS did not return an access token")

    # Save to DB
    result = await db.execute(select(DestinationConnection).where(DestinationConnection.org_id == body.orgId))
    conn = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)

    encrypted = encrypt(f"{body.clientId}:{body.clientSecret}")
    if conn:
        conn.client_id = body.clientId
        conn.sandbox_name = body.sandboxName
        conn.encrypted_credentials = encrypted
        conn.authenticated = True
        conn.last_authenticated_at = now
    else:
        conn = DestinationConnection(
            org_id=body.orgId,
            client_id=body.clientId,
            sandbox_name=body.sandboxName,
            encrypted_credentials=encrypted,
            authenticated=True,
            last_authenticated_at=now,
        )
        db.add(conn)

    log.info("AJO authenticated – orgId=%s", body.orgId)
    return {"success": True, "authenticated": True}


IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"


@app.post("/api/ajo/connect")
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
    # IMS v3 returns expires_in in seconds; older responses use milliseconds
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

    log.info("AJO authenticated – orgId=%s, token expires at %s", body.org_id, token_expires_at)
    return {"success": True, "authenticated": True, "expires_in": expires_in}


@app.get("/api/connections/status")
async def connections_status(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)

    src = None
    dst = None

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


@app.get("/api/acc/schemas")
async def acc_schemas(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(401, "Source not found")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            ACC_ENDPOINT,
            content=build_list_schemas_envelope(conn.session_token, conn.security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={conn.session_token}",
                "X-Security-Token": conn.security_token,
            },
        )

    schemas = parse_schemas(resp.text)
    if not schemas:
        log.warning("No schemas parsed – raw response: %s", resp.text[:1000])
    return {"schemas": schemas}


@app.get("/debug/schemas-raw")
async def schemas_raw(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(401, "Source not found")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            ACC_ENDPOINT,
            content=build_list_schemas_envelope(conn.session_token, conn.security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={conn.session_token}",
                "X-Security-Token": conn.security_token,
            },
        )
    return {"status": resp.status_code, "raw_xml": resp.text}


@app.get("/health")
async def health():
    return {"status": "ok"}
