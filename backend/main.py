"""
Adobe Campaign Classic → AJO  –  FastAPI backend.

Routes consumed by the React frontend (proxied via Vite /api → :8000):
  POST /api/acc/connect       ACC SOAP Logon + TestCnx
  GET  /api/acc/status        is there a live ACC session?
  GET  /api/acc/schemas       list xtk:schema entries from ACC
  POST /api/ajo/connect       IMS OAuth2 for AJO
  GET  /api/ajo/status        is there a live AJO token?
  GET  /health
"""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Cookie, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from acc_soap import (
    build_logon_envelope,
    build_test_cnx_envelope,
    build_list_schemas_envelope,
    parse_logon_response,
    parse_fault,
    parse_schemas,
)
from config import settings
from session_store import SessionStore

# ---------------------------------------------------------------------------
# Logging  (never log secrets)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("acc_backend")

# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
acc_store = SessionStore()   # session_id → { session_token, security_token }

# AJO state (single-user in-memory; swap for Redis in production)
_ajo_state: dict = {
    "connected": False,
    "org_id": None,
    "sandbox_name": None,
    "access_token": None,
    "expires_at": 0.0,
}


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Backend starting – ACC endpoint: %s", settings.acc_endpoint)
    yield
    log.info("Backend shutting down")


app = FastAPI(title="ACC→AJO Backend", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas (Pydantic)
# ---------------------------------------------------------------------------
class AccConnectRequest(BaseModel):
    login: str
    password: str


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str


# ---------------------------------------------------------------------------
# Helper – resolve ACC session from cookie
# ---------------------------------------------------------------------------
def _require_acc_session(acc_session: Optional[str]) -> dict:
    if not acc_session:
        raise HTTPException(401, "Not authenticated – call /api/acc/connect first")
    tokens = acc_store.get(acc_session)
    if not tokens:
        raise HTTPException(401, "Session expired – please reconnect")
    return tokens


# ===========================================================================
# ACC routes
# ===========================================================================

@app.post("/api/acc/connect")
async def acc_connect(body: AccConnectRequest, response: Response):
    """
    1. SOAP Logon with credentials.
    2. Parse session + security tokens.
    3. SOAP TestCnx to verify session is live.
    4. Store tokens server-side; return opaque session cookie.
    """
    log.info("ACC connect attempt – login=%s", body.login)

    async with httpx.AsyncClient(timeout=settings.soap_timeout) as client:

        # ── Logon ────────────────────────────────────────────────────────────
        try:
            logon_resp = await client.post(
                settings.acc_endpoint,
                content=build_logon_envelope(body.login, body.password),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "xtk:session#Logon",
                },
            )
        except httpx.RequestError as exc:
            log.error("Network error reaching ACC: %s", exc)
            raise HTTPException(502, "Cannot reach Adobe Campaign Classic")

        if logon_resp.status_code != 200:
            fault = parse_fault(logon_resp.text)
            raise HTTPException(401, fault or "Logon failed")

        session_token, security_token = parse_logon_response(logon_resp.text)
        if not session_token or not security_token:
            fault = parse_fault(logon_resp.text)
            raise HTTPException(401, fault or "Authentication failed: tokens missing")

        log.info("ACC Logon succeeded – login=%s", body.login)

        # ── TestCnx ──────────────────────────────────────────────────────────
        try:
            test_resp = await client.post(
                settings.acc_endpoint,
                content=build_test_cnx_envelope(session_token, security_token),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "xtk:session#TestCnx",
                    "Cookie": f"__sessiontoken={session_token}",
                    "X-Security-Token": security_token,
                },
            )
        except httpx.RequestError as exc:
            log.error("Network error during TestCnx: %s", exc)
            raise HTTPException(502, "Cannot reach Adobe Campaign Classic")

        if test_resp.status_code != 200:
            fault = parse_fault(test_resp.text)
            raise HTTPException(401, fault or "Session verification failed")

        fault = parse_fault(test_resp.text)
        if fault:
            raise HTTPException(401, fault)

    # ── Store & respond ──────────────────────────────────────────────────────
    session_id = str(uuid.uuid4())
    acc_store.set(session_id, session_token=session_token, security_token=security_token,
                  login=body.login)

    response.set_cookie(
        key="acc_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
    )

    log.info("ACC session stored – session_id=%s login=%s", session_id, body.login)
    return {"connected": True, "login": body.login}


@app.get("/api/acc/status")
async def acc_status(acc_session: Optional[str] = Cookie(default=None)):
    entry = acc_store.get(acc_session) if acc_session else None
    if entry:
        return {"connected": True, "login": entry.get("login")}
    return {"connected": False, "login": None}


@app.get("/api/acc/schemas")
async def acc_schemas(acc_session: Optional[str] = Cookie(default=None)):
    tokens = _require_acc_session(acc_session)

    async with httpx.AsyncClient(timeout=settings.soap_timeout) as client:
        try:
            resp = await client.post(
                settings.acc_endpoint,
                content=build_list_schemas_envelope(
                    tokens["session_token"], tokens["security_token"]
                ),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": "xtk:queryDef#ExecuteQuery",
                    "Cookie": f"__sessiontoken={tokens['session_token']}",
                    "X-Security-Token": tokens["security_token"],
                },
            )
        except httpx.RequestError as exc:
            log.error("Network error fetching schemas: %s", exc)
            raise HTTPException(502, "Cannot reach Adobe Campaign Classic")

    if resp.status_code != 200:
        fault = parse_fault(resp.text)
        raise HTTPException(502, fault or "Failed to fetch schemas")

    fault = parse_fault(resp.text)
    if fault:
        raise HTTPException(502, fault)

    schemas = parse_schemas(resp.text)
    log.info("Fetched %d schemas from ACC", len(schemas))
    return {"schemas": schemas}


# ===========================================================================
# AJO routes  (IMS OAuth 2.0 – service account / client-credentials flow)
# ===========================================================================

@app.post("/api/ajo/connect")
async def ajo_connect(body: AjoConnectRequest):
    """
    Authenticate against Adobe IMS using client-credentials grant.
    Stores the access token server-side.
    """
    log.info("AJO connect attempt – org_id=%s sandbox=%s", body.org_id, body.sandbox_name)

    ims_url = "https://ims-na1.adobelogin.com/ims/token/v3"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            token_resp = await client.post(
                ims_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": body.client_id,
                    "client_secret": body.client_secret,
                    "scope": "openid,AdobeID,read_organizations,additional_info.projectedProductContext",
                },
            )
        except httpx.RequestError as exc:
            log.error("Network error reaching IMS: %s", exc)
            raise HTTPException(502, "Cannot reach Adobe IMS")

    if token_resp.status_code != 200:
        log.warning("IMS token error: %s", token_resp.text[:200])
        raise HTTPException(401, "AJO authentication failed – check credentials")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        raise HTTPException(401, "IMS did not return an access token")

    _ajo_state.update({
        "connected": True,
        "org_id": body.org_id,
        "sandbox_name": body.sandbox_name,
        "access_token": access_token,
        "expires_at": time.monotonic() + expires_in,
    })

    log.info("AJO connected – org_id=%s", body.org_id)
    return {"connected": True, "org_id": body.org_id, "sandbox_name": body.sandbox_name}


@app.get("/api/ajo/status")
async def ajo_status():
    alive = (
        _ajo_state["connected"]
        and _ajo_state["access_token"] is not None
        and time.monotonic() < _ajo_state["expires_at"]
    )
    if alive:
        return {
            "connected": True,
            "org_id": _ajo_state["org_id"],
            "sandbox_name": _ajo_state["sandbox_name"],
        }
    return {"connected": False, "org_id": None, "sandbox_name": None}


# ===========================================================================
# Health
# ===========================================================================

@app.get("/health")
async def health():
    return {"status": "ok"}


# ===========================================================================
# Legacy endpoint (kept for backward-compat / direct curl testing)
# ===========================================================================

@app.post("/login")
async def login_legacy(body: AccConnectRequest, response: Response):
    return await acc_connect(body, response)
