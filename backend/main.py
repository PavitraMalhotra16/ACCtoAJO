import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import httpx
import os
from cryptography.fernet import Fernet
from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from acc_soap import (
    build_bearer_token_logon_envelope,
    build_get_schema_envelope,
    build_list_schemas_envelope,
    build_logon_envelope,
    build_srcschema_get_envelope,
    build_test_cnx_envelope,
    parse_fault,
    parse_logon_response,
    parse_schema_detail,
    parse_schemas,
)
from acc_xml_parser import generate_ajo_ddl, parse_acc_file
from db import AsyncSessionLocal, DestinationConnection, SchemaRegistry, SourceConnection, UserSession, get_db, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("acc_backend")

_key = os.getenv("ENCRYPTION_KEY")
if not _key:
    raise RuntimeError("ENCRYPTION_KEY not set in .env – run: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
fernet = Fernet(_key.encode())

CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS_RAW", "http://localhost:3000,http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]
SOAP_TIMEOUT = float(os.getenv("SOAP_TIMEOUT", "30.0"))
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"
SESSION_TTL_DAYS = 7
USER_COOKIE_TTL_DAYS = 365


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


def _set_session_cookies(response: Response, session_id: str, login_id: str) -> None:
    response.set_cookie(
        key="acc_session", value=session_id,
        httponly=True, samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
    )
    response.set_cookie(
        key="acc_user", value=login_id,
        httponly=True, samesite="lax",
        max_age=USER_COOKIE_TTL_DAYS * 24 * 3600,
    )


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


# ── Pydantic models ───────────────────────────────────────────────────────────

class AccConnectRequest(BaseModel):
    auth_type: str = "classic"          # "classic" | "technical"
    instance_url: str
    # Classic fields
    login: Optional[str] = None
    password: Optional[str] = None
    # Technical account (IMS) fields
    org_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: Optional[str] = None


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str
    reference_token: Optional[str] = None


# ── Routes ───────────────────────────────────────────────────────────────────

@app.post("/api/acc/connect")
async def acc_connect(
    body: AccConnectRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    soap_url = body.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        if body.auth_type == "classic":
            if not body.login or not body.password:
                raise HTTPException(400, "login and password are required for classic auth")

            log.info("ACC classic login – login=%s url=%s", body.login, soap_url)
            try:
                logon = await client.post(
                    soap_url,
                    content=build_logon_envelope(body.login, body.password),
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "xtk:session#Logon"},
                )
            except httpx.RequestError:
                raise HTTPException(502, f"Cannot reach Campaign instance at {body.instance_url}")

            fault = parse_fault(logon.text)
            if fault:
                raise HTTPException(401, fault)

            session_token, security_token = parse_logon_response(logon.text)
            if not session_token:
                raise HTTPException(401, parse_fault(logon.text) or "Authentication failed – no session token")

            # TestCnx to confirm
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

            login_id = body.login
            result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
            conn = result.scalar_one_or_none()
            if conn:
                conn.auth_type = "classic"
                conn.instance_url = body.instance_url
                conn.encrypted_password = encrypt(body.password)
                conn.session_token = session_token
                conn.security_token = security_token
                conn.authenticated = True
                conn.last_authenticated_at = now
            else:
                conn = SourceConnection(
                    login_id=login_id,
                    auth_type="classic",
                    instance_url=body.instance_url,
                    encrypted_password=encrypt(body.password),
                    session_token=session_token,
                    security_token=security_token,
                    authenticated=True,
                    last_authenticated_at=now,
                )
                db.add(conn)

        else:  # technical
            if not body.client_id or not body.client_secret:
                raise HTTPException(400, "client_id and client_secret are required for technical auth")

            log.info("ACC technical account login – clientId=%s", body.client_id)
            scope = body.scope or IMS_SCOPES
            try:
                token_resp = await client.post(
                    IMS_TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": body.client_id,
                        "client_secret": body.client_secret,
                        "scope": scope,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.RequestError:
                raise HTTPException(502, "Cannot reach Adobe IMS")

            if token_resp.status_code != 200:
                raise HTTPException(401, "IMS authentication failed – check client ID and secret")

            ims_token = token_resp.json().get("access_token")
            if not ims_token:
                raise HTTPException(401, "IMS did not return an access token")

            # BearerTokenLogon against ACC
            try:
                logon = await client.post(
                    soap_url,
                    content=build_bearer_token_logon_envelope(ims_token),
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": "xtk:session#BearerTokenLogon"},
                )
            except httpx.RequestError:
                raise HTTPException(502, f"Cannot reach Campaign instance at {body.instance_url}")

            fault = parse_fault(logon.text)
            if fault:
                raise HTTPException(401, fault)

            session_token, security_token = parse_logon_response(logon.text)
            if not session_token:
                raise HTTPException(401, "BearerTokenLogon did not return a session token")

            login_id = body.client_id
            result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
            conn = result.scalar_one_or_none()
            if conn:
                conn.auth_type = "technical"
                conn.instance_url = body.instance_url
                conn.encrypted_client_secret = encrypt(body.client_secret)
                conn.scope = scope
                conn.session_token = session_token
                conn.security_token = security_token
                conn.authenticated = True
                conn.last_authenticated_at = now
            else:
                conn = SourceConnection(
                    login_id=login_id,
                    auth_type="technical",
                    instance_url=body.instance_url,
                    encrypted_client_secret=encrypt(body.client_secret),
                    scope=scope,
                    session_token=session_token,
                    security_token=security_token,
                    authenticated=True,
                    last_authenticated_at=now,
                )
                db.add(conn)

    session_id = str(uuid.uuid4())
    db.add(UserSession(
        id=session_id,
        login_id=login_id,
        expires_at=now + timedelta(days=SESSION_TTL_DAYS),
    ))
    await db.flush()
    _set_session_cookies(response, session_id, login_id)

    log.info("ACC authenticated – loginId=%s auth_type=%s", login_id, body.auth_type)
    return {"success": True, "login": login_id, "auth_type": body.auth_type}


@app.post("/api/acc/disconnect")
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


@app.get("/api/acc/status")
async def acc_status(
    response: Response,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)

    # Auto-restore: if no cookie at all (new browser, same machine), pick last authenticated
    if not login_id:
        result = await db.execute(
            select(SourceConnection)
            .where(SourceConnection.authenticated == True)
            .order_by(SourceConnection.last_authenticated_at.desc())
            .limit(1)
        )
        conn = result.scalar_one_or_none()
        if conn:
            login_id = conn.login_id
            session_id = str(uuid.uuid4())
            db.add(UserSession(
                id=session_id,
                login_id=login_id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
            ))
            _set_session_cookies(response, session_id, login_id)
            return {"connected": True, "login": login_id}
        return {"connected": False, "login": None}

    result = await db.execute(
        select(SourceConnection).where(
            SourceConnection.login_id == login_id,
            SourceConnection.authenticated == True,
        )
    )
    conn = result.scalar_one_or_none()
    return {"connected": conn is not None, "login": conn.login_id if conn else None}


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


@app.get("/api/ajo/status")
async def ajo_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.authenticated == True)
    )
    conn = result.scalar_one_or_none()
    return {
        "connected": conn is not None,
        "org_id": conn.org_id if conn else None,
        "sandbox_name": conn.sandbox_name if conn else None,
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

    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_list_schemas_envelope(conn.session_token, conn.security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={conn.session_token}",
                "X-Security-Token": conn.security_token,
            },
        )

    fault = parse_fault(resp.text)
    if fault:
        raise HTTPException(401, fault)

    schemas = parse_schemas(resp.text)
    if not schemas:
        log.warning("No schemas parsed – raw response: %s", resp.text[:1000])
    return {"schemas": schemas}


@app.get("/api/acc/schemas/{namespace}/{name}")
async def acc_schema_detail(
    namespace: str,
    name: str,
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

    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    headers_base = {
        "Content-Type": "text/xml; charset=utf-8",
        "Cookie": f"__sessiontoken={conn.session_token}",
        "X-Security-Token": conn.security_token,
    }

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        # First try xtk:schema#Get
        resp = await client.post(
            soap_url,
            content=build_get_schema_envelope(conn.session_token, conn.security_token, namespace, name),
            headers={**headers_base, "SOAPAction": "xtk:schema#Get"},
        )

        fault = parse_fault(resp.text)
        if fault:
            log.info("xtk:schema#Get returned fault (%s), trying srcSchema fallback", fault)
            resp = await client.post(
                soap_url,
                content=build_srcschema_get_envelope(conn.session_token, conn.security_token, namespace, name),
                headers={**headers_base, "SOAPAction": "xtk:queryDef#ExecuteQuery"},
            )
            fault2 = parse_fault(resp.text)
            if fault2:
                raise HTTPException(404, f"Schema {namespace}:{name} not found: {fault2}")

    detail = parse_schema_detail(resp.text)
    if not detail:
        raise HTTPException(404, f"Schema {namespace}:{name} could not be parsed")
    return detail


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

    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_list_schemas_envelope(conn.session_token, conn.security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={conn.session_token}",
                "X-Security-Token": conn.security_token,
            },
        )
    return {"status": resp.status_code, "raw_xml": resp.text}


@app.post("/api/schemas/upload")
async def upload_schema(
    file: UploadFile = File(...),
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Accept an ACC DDL file upload, convert to AJO DDL, create tables in Postgres,
    and register them in the schema_registry master table.

    # FORMAT ASSUMPTION: uploaded file is ACC XML (see acc_xml_parser.py).
    # If the format changes, update acc_xml_parser.parse_acc_file().
    """
    result = await db.execute(
        select(DestinationConnection).where(
            DestinationConnection.org_id == org_id,
            DestinationConnection.authenticated == True,
        )
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(401, "AJO not authenticated for this org_id")

    content = await file.read()

    try:
        tables = parse_acc_file(content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    ddl_sql = generate_ajo_ddl(tables)
    log.info("Generated AJO DDL for %d table(s)", len(tables))

    created = []
    replaced = []
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as raw_conn:
        async with raw_conn.begin():
            for table in tables:
                table_name = table["table_name"]

                # Check if already registered for this user
                reg_result = await raw_conn.execute(
                    select(SchemaRegistry).where(
                        SchemaRegistry.org_id == org_id,
                        SchemaRegistry.client_id == (dest.client_id or ""),
                        SchemaRegistry.sandbox_name == (dest.sandbox_name or ""),
                        SchemaRegistry.table_name == table_name,
                    )
                )
                existing_reg = reg_result.scalar_one_or_none()

                # Drop existing table if it exists (upsert behaviour)
                await raw_conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))

                # Find and execute the CREATE TABLE for this specific table
                create_stmt = _extract_create_stmt(ddl_sql, table_name)
                if create_stmt:
                    await raw_conn.execute(text(create_stmt))

                # Update or insert master table entry
                if existing_reg:
                    existing_reg.updated_at = now
                    replaced.append(table_name)
                else:
                    raw_conn.add(SchemaRegistry(
                        org_id=org_id,
                        client_id=dest.client_id or "",
                        sandbox_name=dest.sandbox_name or "",
                        table_name=table_name,
                        source_schema_name=table_name,
                        created_at=now,
                        updated_at=now,
                    ))
                    created.append(table_name)

        await raw_conn.commit()

    log.info("Schema upload done — created: %s, replaced: %s", created, replaced)
    return {
        "success": True,
        "created": created,
        "replaced": replaced,
        "total": len(tables),
        "ddl_preview": ddl_sql[:2000],
    }


@app.get("/api/schemas/existing")
async def existing_schemas(
    org_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Return all tables registered for the given org_id."""
    result = await db.execute(
        select(DestinationConnection).where(
            DestinationConnection.org_id == org_id,
            DestinationConnection.authenticated == True,
        )
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(401, "AJO not authenticated for this org_id")

    reg_result = await db.execute(
        select(SchemaRegistry).where(
            SchemaRegistry.org_id == org_id,
            SchemaRegistry.client_id == (dest.client_id or ""),
            SchemaRegistry.sandbox_name == (dest.sandbox_name or ""),
        )
    )
    rows = reg_result.scalars().all()

    return {
        "schemas": [
            {
                "table_name": r.table_name,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in rows
        ]
    }


def _extract_create_stmt(full_ddl: str, table_name: str) -> Optional[str]:
    """Extract the CREATE TABLE block for a specific table from the full DDL string."""
    marker = f"CREATE TABLE {table_name}"
    start = full_ddl.find(marker)
    if start == -1:
        return None
    end = full_ddl.find(");", start)
    if end == -1:
        return None
    return full_ddl[start:end + 2]


@app.get("/health")
async def health():
    return {"status": "ok"}
