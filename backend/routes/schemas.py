"""
Routes for listing and inspecting ACC schemas.
"""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import SourceConnection, get_db
from core.security import get_login_from_cookie
from services.acc_soap import build_list_schemas_envelope, parse_schemas, parse_fault
from services.schema_inspector import parse_schema_to_xdm
from services.acc_soap import build_srcschema_get_envelope

log = logging.getLogger("acc_backend.schemas")
router = APIRouter()

SOAP_TIMEOUT = 30.0


async def _get_acc_conn(acc_session, acc_user, db):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    conn = result.scalar_one_or_none()
    if not conn or not conn.session_token:
        raise HTTPException(401, "ACC session not found")
    return conn


@router.get("/api/acc/schemas")
async def list_schemas(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_acc_conn(acc_session, acc_user, db)
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

    EXCLUDED = {"crm", "ncm", "nms", "xtk", "nl"}
    all_schemas = parse_schemas(resp.text)
    schemas = [s for s in all_schemas if s.get("namespace", "").lower() not in EXCLUDED]
    if not schemas:
        log.warning("No schemas parsed – raw: %s", resp.text[:500])
    return {"schemas": schemas}


@router.get("/api/acc/schemas/{namespace}/{name}")
async def inspect_schema(
    namespace: str,
    name: str,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_acc_conn(acc_session, acc_user, db)
    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_srcschema_get_envelope(conn.session_token, conn.security_token, namespace, name),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={conn.session_token}",
                "X-Security-Token": conn.security_token,
            },
        )

    fault = parse_fault(resp.text)
    if fault:
        raise HTTPException(400, fault)

    parsed = parse_schema_to_xdm(resp.text, namespace, name)
    if not parsed:
        raise HTTPException(404, f"Schema {namespace}:{name} not found or empty")
    return parsed
