"""
Routes for listing and inspecting ACC schemas.
"""

import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import SourceConnection, get_db
from core.security import get_login_from_cookie, get_valid_acc_token, acc_soap_headers
from services.acc_soap import build_list_schemas_envelope, build_srcschema_get_envelope, parse_schemas, parse_fault
from services.schema_preview import parse_schema_preview

log = logging.getLogger("acc_backend.schemas")
router = APIRouter()

SOAP_TIMEOUT = 30.0


async def _get_acc_conn(acc_session, acc_user, db):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    conn = result.scalar_one_or_none()
    if not conn or not conn.authenticated:
        raise HTTPException(401, "ACC session not found")
    try:
        token = await get_valid_acc_token(conn, db)
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    return conn, token


@router.get("/api/acc/schemas")
async def list_schemas(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    conn, token = await _get_acc_conn(acc_session, acc_user, db)
    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    soap_token = "" if conn.auth_type == "technical" else token

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_list_schemas_envelope(soap_token, conn.security_token or ""),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                **acc_soap_headers(conn, token),
            },
        )

    if resp.status_code == 403 or "Session has expired" in resp.text:
        raise HTTPException(401, "ACC session expired. Please log in again.")

    all_schemas = parse_schemas(resp.text)
    schemas = [s for s in all_schemas if s.get("namespace", "").lower() not in SYSTEM_NAMESPACES]
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
    conn, token = await _get_acc_conn(acc_session, acc_user, db)
    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    soap_token = "" if conn.auth_type == "technical" else token

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_srcschema_get_envelope(soap_token, conn.security_token or "", namespace, name),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                **acc_soap_headers(conn, token),
            },
        )

    fault = parse_fault(resp.text)
    if fault:
        raise HTTPException(400, fault)

    parsed = parse_schema_preview(resp.text, namespace, name)
    if not parsed:
        raise HTTPException(404, f"Schema {namespace}:{name} not found or empty")
    return parsed


SYSTEM_NAMESPACES = {
    "xtk", "nms", "nl", "ncm", "crm",
    "bur", "sfa", "ext", "offer", "mkt",
    "wpa", "sup", "temp", "ghost",
    "nav", "acs", "fda",
}

_DEP_HEADERS = {
    "Content-Type": "text/xml; charset=utf-8",
    "SOAPAction": "xtk:queryDef#ExecuteQuery",
}


async def _fetch_links(
    client: httpx.AsyncClient,
    soap_url: str,
    soap_token: str,
    security_token: str,
    namespace: str,
    name: str,
    auth_headers: dict,
) -> tuple[str, list[dict]]:
    """Fetch a single srcSchema and return (schema_key, links[])."""
    try:
        resp = await client.post(
            soap_url,
            content=build_srcschema_get_envelope(soap_token, security_token, namespace, name),
            headers={**_DEP_HEADERS, **auth_headers},
        )
        parsed = parse_schema_preview(resp.text, namespace, name)
        return f"{namespace}:{name}", parsed.get("links", [])
    except Exception:
        return f"{namespace}:{name}", []


@router.get("/api/schemas/dependencies")
async def get_dependency_graph(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Build the schema dependency graph by fetching all custom schema XMLs live
    from ACC SOAP concurrently.

    Always uses live SOAP — the DB path was removed because it only covers
    extracted schemas, missing dependencies for schemas the user never selected
    for extraction.

    A schema is DEPENDENT if it has a link (FK) pointing to another custom schema.
    A schema is INDEPENDENT if nothing links away from it to another custom schema.
    """
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    conn_result = await db.execute(
        select(SourceConnection).where(SourceConnection.login_id == login_id)
    )
    conn = conn_result.scalar_one_or_none()
    if not conn or not conn.authenticated:
        raise HTTPException(401, "ACC session not found")
    try:
        token = await get_valid_acc_token(conn, db)
    except RuntimeError as e:
        raise HTTPException(401, str(e))

    soap_url = conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        list_resp = await client.post(
            soap_url,
            content=build_list_schemas_envelope(soap_token, conn.security_token or ""),
            headers={**_DEP_HEADERS, **auth_hdrs},
        )
    all_schemas = parse_schemas(list_resp.text)
    custom = [s for s in all_schemas if s.get("namespace", "").lower() not in SYSTEM_NAMESPACES]
    all_names = {f"{s['namespace']}:{s['name']}" for s in custom}

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        tasks = [
            _fetch_links(client, soap_url, soap_token, conn.security_token or "", s["namespace"], s["name"], auth_hdrs)
            for s in custom
        ]
        results = await asyncio.gather(*tasks)

    dependents_of: dict[str, list[str]] = {}
    dependent_set: set[str] = set()

    for schema_key, links in results:
        for link in links:
            target = link.get("targetSchema", "")
            if not target or target == schema_key or target not in all_names:
                continue
            dependents_of.setdefault(target, [])
            if schema_key not in dependents_of[target]:
                dependents_of[target].append(schema_key)
            dependent_set.add(schema_key)

    return {
        "dependents_of": dependents_of,
        "dependent_set": list(dependent_set),
    }
