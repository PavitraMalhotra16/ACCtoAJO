"""
Workflow extraction routes.

GET  /api/workflows/count          — count ACC workflows (live SOAP call)
GET  /api/workflows/stored-count   — count workflows already stored in DB for this user
POST /api/workflows/extract        — start background extraction of all workflows
GET  /api/workflows/extract/status — poll extraction progress by batch_id
GET  /api/workflows                — list all stored (extracted) workflows for this user
GET  /api/workflows/{internal_name} — get one stored workflow's full parsed JSON
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AccWorkflowRaw, AccWorkflowParsed, AsyncSessionLocal, SourceConnection, get_db
from core.security import get_login_from_cookie, get_valid_acc_token, acc_soap_headers
from services.workflow_extractor import (
    count_workflows,
    fetch_workflow_list,
    fetch_workflow_detail,
    store_raw,
    store_parsed,
)

log = logging.getLogger("acc_backend.workflows")
router = APIRouter()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _soap_url(instance_url: str) -> str:
    return instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"


async def _require_acc(db: AsyncSession, login_id: str | None) -> tuple[SourceConnection, str]:
    """Resolve ACC connection + valid token, or raise 401."""
    if not login_id:
        raise HTTPException(401, "Not authenticated — connect to ACC first")
    result = await db.execute(
        select(SourceConnection).where(SourceConnection.login_id == login_id)
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.authenticated:
        raise HTTPException(401, "ACC not authenticated — connect first")
    try:
        token = await get_valid_acc_token(conn, db)
    except RuntimeError as exc:
        raise HTTPException(401, str(exc))
    return conn, token


# In-memory job state for background extraction.
# Key: batch_id  Value: {status, done, total, errors, started_at, finished_at}
_extraction_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# GET /api/workflows/acc-db-schema  — discover ACC workflow table structure
# ---------------------------------------------------------------------------

@router.get("/api/workflows/acc-db-schema")
async def get_acc_db_schema():
    """
    Diagnostic: connect to the ACC PostgreSQL database (ACC_DB_URL env var) and
    return the column names + types of the workflow table so we know which column
    holds the activities XML.
    """
    import os
    acc_db_url = os.getenv("ACC_DB_URL", "").strip()
    if not acc_db_url:
        return {"error": "ACC_DB_URL not set in .env", "columns": []}

    sync_url = acc_db_url.replace("postgresql+asyncpg://", "postgresql://").replace("asyncpg://", "postgresql://")
    try:
        import asyncpg
        url = acc_db_url.replace("postgresql://", "").replace("postgresql+asyncpg://", "")
        # Parse connection string manually
        conn = await asyncpg.connect(dsn=f"postgresql://{url}" if not acc_db_url.startswith("postgresql") else acc_db_url.replace("+asyncpg", ""))
        cols = await conn.fetch(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_name ILIKE 'xtkworkflow'
            ORDER BY ordinal_position
            """
        )
        await conn.close()
        return {"table": "XtkWorkflow", "columns": [dict(r) for r in cols]}
    except Exception as exc:
        return {"error": str(exc), "columns": []}


# ---------------------------------------------------------------------------
# GET /api/workflows/sample-spec   — fetch a real specFile from ACC for debugging
# ---------------------------------------------------------------------------

@router.get("/api/workflows/sample-spec")
async def get_sample_spec(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Diagnostic: query xtk:specFile from ACC to see the real spec format ACC uses.
    Fetches any existing specFile records so we can inspect the XML structure
    that GenerateDoc expects as input.
    GET /api/workflows/sample-spec
    """
    from services.acc_soap import build_list_workflows_envelope, parse_fault
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    conn, token = await _require_acc(db, login_id)
    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)
    soap_url = _soap_url(conn.instance_url)

    # Query xtk:specFile for existing spec files (use @id/@name/@label — no @internalName)
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">'
        '<soapenv:Header><urn:SecurityHeader xmlns:urn="urn:xtk:session">'
        f'<urn:sessiontoken>{soap_token}</urn:sessiontoken>'
        f'<urn:securityToken>{conn.security_token or ""}</urn:securityToken>'
        '</urn:SecurityHeader></soapenv:Header>'
        '<soapenv:Body><urn:ExecuteQuery>'
        f'<urn:sessiontoken>{soap_token}</urn:sessiontoken>'
        '<urn:entity>'
        '<queryDef schema="xtk:specFile" operation="select" lineCount="5">'
        '<select>'
        '<node expr="@id"/>'
        '<node expr="@name"/>'
        '<node expr="@label"/>'
        '</select>'
        '</queryDef>'
        '</urn:entity>'
        '</urn:ExecuteQuery></soapenv:Body></soapenv:Envelope>'
    ).encode("utf-8")

    headers = {**auth_hdrs, "Content-Type": "text/xml; charset=utf-8", "SOAPAction": "xtk:queryDef#ExecuteQuery"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(soap_url, content=envelope, headers=headers)

    return {"status": resp.status_code, "body": resp.text}


# ---------------------------------------------------------------------------
# GET /api/workflows/wsdl?schema=xtk:specFile
# ---------------------------------------------------------------------------

@router.get("/api/workflows/wsdl")
async def get_wsdl(
    schema: str = "xtk:specFile",
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Diagnostic: fetch the WSDL for any ACC schema from schemawsdl.jsp.
    Useful for discovering available SOAP methods before coding against them.
    GET /api/workflows/wsdl?schema=xtk:specFile
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    conn, token = await _require_acc(db, login_id)

    from urllib.parse import urlparse
    parsed = urlparse(_soap_url(conn.instance_url))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    wsdl_url = f"{base_url}/nl/jsp/schemawsdl.jsp?schema={schema}"

    cookies = {"__sessiontoken": token} if token else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(wsdl_url, cookies=cookies)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Cannot reach ACC WSDL endpoint: {exc}")

    return {"schema": schema, "status": resp.status_code, "wsdl": resp.text[:8000]}


# ---------------------------------------------------------------------------
# GET /api/workflows/count
# ---------------------------------------------------------------------------

@router.get("/api/workflows/count")
async def get_workflow_count(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns:
      total    — count from ACC (live SOAP call when nothing stored yet)
      stored   — count already in this user's DB
      to_fetch — total - stored (workflows not yet extracted)

    If workflows are already stored, returns stored count immediately without
    hitting ACC — same pattern as /api/templates/count.
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)

    stored_result = await db.execute(
        select(func.count()).select_from(AccWorkflowParsed)
        .where(AccWorkflowParsed.login_id == login_id)
    )
    stored = stored_result.scalar() or 0

    if stored > 0:
        return {"total": stored, "stored": stored, "to_fetch": 0}

    conn, token = await _require_acc(db, login_id)
    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)

    try:
        total = await count_workflows(
            _soap_url(conn.instance_url), soap_token, conn.security_token or "", auth_headers=auth_hdrs
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    return {"total": total, "stored": stored, "to_fetch": max(0, total - stored)}


# ---------------------------------------------------------------------------
# GET /api/workflows/stored-count
# ---------------------------------------------------------------------------

@router.get("/api/workflows/stored-count")
async def get_stored_count(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Quick count of workflows already in DB — used to poll during extraction."""
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        return {"stored": 0}
    result = await db.execute(
        select(func.count()).select_from(AccWorkflowParsed)
        .where(AccWorkflowParsed.login_id == login_id)
    )
    return {"stored": result.scalar() or 0}


# ---------------------------------------------------------------------------
# POST /api/workflows/extract
# ---------------------------------------------------------------------------

async def _run_extraction_job(
    batch_id: str,
    login_id: str,
    soap_url: str,
    soap_token: str,
    security_token: str,
    auth_hdrs: dict,
) -> None:
    """
    Background task: fetch every workflow's full XML from ACC and store both
    the raw XML and parsed JSON in DB.

    Runs in a separate asyncio task — the route returns immediately with the
    batch_id and the frontend polls /extract/status to track progress.
    """
    job = _extraction_jobs[batch_id]
    job["status"] = "running"

    try:
        workflows = await fetch_workflow_list(
            soap_url, soap_token, security_token, auth_headers=auth_hdrs
        )
        job["total"] = len(workflows)
        log.info("Extraction job %s: found %d workflows", batch_id, len(workflows))

        async with AsyncSessionLocal() as db:
            for meta in workflows:
                internal_name = meta.get("internalName", "")
                if not internal_name:
                    job["done"] += 1
                    continue
                try:
                    detail = await fetch_workflow_detail(
                        soap_url, soap_token, security_token, internal_name,
                        workflow_id=meta.get("id", ""),
                        auth_headers=auth_hdrs,
                    )
                    if detail is None:
                        log.warning("No detail returned for workflow %s — skipping", internal_name)
                        job["done"] += 1
                        continue

                    await store_raw(db, login_id, internal_name, detail.get("label", ""), detail.get("raw_xml", ""))
                    await store_parsed(db, login_id, detail)
                    await db.commit()

                except Exception as exc:
                    await db.rollback()
                    log.exception("Failed to extract workflow %s: %s", internal_name, exc)
                    job["errors"].append({"internalName": internal_name, "error": str(exc)})
                finally:
                    job["done"] += 1

    except Exception as exc:
        log.exception("Extraction job %s failed: %s", batch_id, exc)
        job["status"] = "error"
        job["errors"].append({"error": str(exc)})
    else:
        job["status"] = "done"
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.post("/api/workflows/extract")
async def extract_workflows(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Start background extraction of all ACC workflows.

    Returns immediately with a batch_id. The frontend polls
    GET /api/workflows/extract/status?batch_id=<id> to track progress.

    Workflows already in DB are overwritten — extraction is always a full refresh
    because workflows update frequently and the upsert is safe.
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    conn, token = await _require_acc(db, login_id)

    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)
    soap_url = _soap_url(conn.instance_url)

    batch_id = str(uuid.uuid4())
    _extraction_jobs[batch_id] = {
        "status": "queued",
        "done": 0,
        "total": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }

    asyncio.create_task(
        _run_extraction_job(batch_id, login_id, soap_url, soap_token, conn.security_token or "", auth_hdrs)
    )

    return {"batch_id": batch_id, "status": "queued"}


# ---------------------------------------------------------------------------
# GET /api/workflows/extract/status
# ---------------------------------------------------------------------------

@router.get("/api/workflows/extract/status")
async def get_extraction_status(
    batch_id: str,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Poll extraction progress for a given batch_id.

    Response:
      status     — 'queued' | 'running' | 'done' | 'error'
      done       — number of workflows processed so far
      total      — total workflows found (0 while still queued)
      errors     — list of {internalName, error} for any failed workflows
      stored     — live count from DB (cross-checks against in-memory job state)
    """
    job = _extraction_jobs.get(batch_id)
    if job is None:
        raise HTTPException(404, f"No extraction job found for batch_id={batch_id}")

    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    stored_result = await db.execute(
        select(func.count()).select_from(AccWorkflowParsed)
        .where(AccWorkflowParsed.login_id == login_id)
    )
    stored = stored_result.scalar() or 0

    return {
        "batch_id": batch_id,
        "status": job["status"],
        "done": job["done"],
        "total": job["total"],
        "errors": job["errors"],
        "stored": stored,
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
    }


# ---------------------------------------------------------------------------
# GET /api/workflows
# ---------------------------------------------------------------------------

@router.get("/api/workflows")
async def list_stored_workflows(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all extracted workflows for this user.
    Each entry includes the full parsed workflow_data JSON so the UI can
    display activity counts, types, folder grouping, etc.
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(AccWorkflowParsed)
        .where(AccWorkflowParsed.login_id == login_id)
        .order_by(AccWorkflowParsed.label)
    )
    rows = result.scalars().all()

    workflows = []
    for row in rows:
        data = json.loads(row.workflow_data or "{}")
        activity_count = len(data.get("activities", []))
        workflows.append({
            "internalName": row.internal_name,
            "label": row.label or row.internal_name,
            "folder": data.get("folder", ""),
            "status": data.get("status", ""),
            "activityCount": activity_count,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        })

    return {"workflows": workflows, "total": len(workflows)}


# ---------------------------------------------------------------------------
# GET /api/workflows/{internal_name}
# ---------------------------------------------------------------------------

@router.get("/api/workflows/{internal_name}")
async def get_workflow(
    internal_name: str,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Return full parsed JSON for one workflow (all activities, transitions, config).
    Used when the user clicks into a workflow detail view.
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(AccWorkflowParsed).where(
            AccWorkflowParsed.login_id == login_id,
            AccWorkflowParsed.internal_name == internal_name,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, f"Workflow '{internal_name}' not found — extract it first")

    data = json.loads(row.workflow_data or "{}")
    return {
        "internalName": row.internal_name,
        "label": row.label,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        "folder": data.get("folder", ""),
        "status": data.get("status", ""),
        "description": data.get("description", ""),
        "attributes": data.get("attributes", {}),
        "activities": data.get("activities", []),
        "edges": data.get("edges", []),
        "variables_xml": data.get("variables_xml", ""),
    }
