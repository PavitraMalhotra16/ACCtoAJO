"""
ACC workflow extraction — SOAP calls + DB persistence.

Functions:
  count_workflows       — count all non-builtin xtk:workflow objects in ACC
  fetch_workflow_list   — list all workflows with metadata (no activity detail)
  fetch_workflow_detail — fetch one workflow's full XML and parse activities
  store_raw             — save raw XML to acc_workflow_raw (upsert)
  store_parsed          — save normalized JSON to acc_workflow_parsed (upsert)
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db import AccWorkflowRaw, AccWorkflowParsed
from services.acc_soap import (
    build_list_workflows_envelope,
    build_get_workflow_detail_envelope,
    parse_workflows,
    parse_workflow_detail,
    parse_fault,
)

log = logging.getLogger("acc_backend.workflow_extractor")

_SOAP_TIMEOUT = 30.0


def _base_headers(session_token: str, security_token: str) -> dict:
    """Classic auth headers used internally by this service."""
    return {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
        "Cookie": f"__sessiontoken={session_token}",
        "X-Security-Token": security_token,
    }


async def count_workflows(
    soap_url: str,
    session_token: str,
    security_token: str,
    auth_headers: dict | None = None,
) -> int:
    """
    Return total number of non-builtin workflows.

    auth_headers overrides the classic Cookie/X-Security-Token headers when
    the connection uses technical (IMS Bearer) auth — passed in from the route
    layer which already called acc_soap_headers(conn, token).
    """
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
        **(auth_headers or _base_headers(session_token, security_token)),
    }
    try:
        async with httpx.AsyncClient(timeout=_SOAP_TIMEOUT) as client:
            resp = await client.post(
                soap_url,
                content=build_list_workflows_envelope(session_token, security_token),
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise RuntimeError(f"Cannot reach ACC at {soap_url}: {exc}") from exc

    if resp.status_code != 200:
        log.error("Workflow list HTTP %d — body: %s", resp.status_code, resp.text[:500])
        raise RuntimeError(parse_fault(resp.text) or f"HTTP {resp.status_code} from ACC workflow list")

    log.info("Workflow list raw response (first 500): %s", resp.text[:500])
    workflows = parse_workflows(resp.text)
    log.info("Workflow list parsed count: %d", len(workflows))
    return len(workflows)


async def fetch_workflow_list(
    soap_url: str,
    session_token: str,
    security_token: str,
    auth_headers: dict | None = None,
) -> list[dict]:
    """
    Return list of workflow metadata dicts (no activity detail).
    Each dict: {internalName, label, desc, folder, status}
    """
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
        **(auth_headers or _base_headers(session_token, security_token)),
    }
    try:
        async with httpx.AsyncClient(timeout=_SOAP_TIMEOUT) as client:
            resp = await client.post(
                soap_url,
                content=build_list_workflows_envelope(session_token, security_token),
                headers=headers,
            )
    except httpx.RequestError as exc:
        raise RuntimeError(f"Cannot reach ACC at {soap_url}: {exc}") from exc

    if resp.status_code != 200:
        log.error("Workflow list HTTP %d — body: %s", resp.status_code, resp.text[:500])
        raise RuntimeError(parse_fault(resp.text) or f"HTTP {resp.status_code} fetching workflow list")

    log.info("fetch_workflow_list raw response (first 500): %s", resp.text[:500])
    result = parse_workflows(resp.text)
    log.info("fetch_workflow_list parsed %d workflows", len(result))
    return result


async def fetch_workflow_detail(
    soap_url: str,
    session_token: str,
    security_token: str,
    internal_name: str,
    workflow_id: str = "",
    auth_headers: dict | None = None,
) -> dict | None:
    """
    Fetch full workflow definition via queryDef requesting the 'data' child element.

    ACC stores workflow activities in SQL column mData. In XTK, mData (MEMO type)
    is exposed as child element 'data' (no @ prefix). The response contains:
      <workflow id="..." internalName="..." ...>
        <data>...full workflow XML including <activities>...</data>
      </workflow>

    The <data> element text is the serialized workflow XML that must be re-parsed
    to extract activities, transitions, and config.
    """
    envelope = build_get_workflow_detail_envelope(
        session_token, security_token, workflow_id, internal_name
    )
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
        **(auth_headers or _base_headers(session_token, security_token)),
    }

    try:
        async with httpx.AsyncClient(timeout=_SOAP_TIMEOUT) as client:
            resp = await client.post(soap_url, content=envelope, headers=headers)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Cannot reach ACC at {soap_url}: {exc}") from exc

    if resp.status_code != 200:
        log.error("Workflow detail HTTP %d for %s: %s", resp.status_code, internal_name, resp.text[:300])
        return None

    fault = parse_fault(resp.text)
    if fault:
        log.error("SOAP fault fetching detail for %s: %s", internal_name, fault)
        return None

    log.info("Detail (mData) response for %s (id=%s), first 1500: %s",
             internal_name, workflow_id, resp.text[:1500])
    return parse_workflow_detail(resp.text, internal_name)


async def store_raw(
    db: AsyncSession,
    login_id: str,
    internal_name: str,
    label: str,
    raw_xml: str,
) -> None:
    """
    Upsert raw workflow XML into acc_workflow_raw.
    Uses PostgreSQL INSERT ... ON CONFLICT DO UPDATE so re-extraction
    always overwrites without a race condition.
    acc_workflow_raw has no unique constraint, so we do a delete+insert.
    """
    await db.execute(
        text(
            "DELETE FROM acc_workflow_raw "
            "WHERE login_id = :login_id AND internal_name = :internal_name"
        ),
        {"login_id": login_id, "internal_name": internal_name},
    )
    db.add(AccWorkflowRaw(
        id=str(uuid.uuid4()),
        login_id=login_id,
        internal_name=internal_name,
        label=label,
        raw_xml=raw_xml,
    ))
    await db.flush()


async def store_parsed(
    db: AsyncSession,
    login_id: str,
    detail: dict,
) -> None:
    """
    Upsert normalized workflow JSON into acc_workflow_parsed.
    If a row already exists for (login_id, internal_name), overwrites workflow_data and updated_at.

    Stored JSON shape:
      {internalName, label, desc, folder, status, activities: [...], variables_xml}
    The raw_xml field is NOT stored here — it lives in AccWorkflowRaw.
    The activities list comes from parse_workflow_detail and contains normalized
    {type, name, label, x, y, config, transitions, children_xml} dicts.
    """
    internal_name = detail["internalName"]
    label = detail.get("label", "")
    now = datetime.now(timezone.utc)

    workflow_data = json.dumps(
        {
            "internalName": internal_name,
            "label": label,
            "folder": detail.get("folder", ""),
            "status": detail.get("status", ""),
            "description": detail.get("description", ""),
            "attributes": detail.get("attributes", {}),
            "activities": detail.get("activities", []),
            "edges": detail.get("edges", []),
            "variables_xml": detail.get("variables_xml", ""),
        },
        ensure_ascii=False,
    )

    stmt = (
        pg_insert(AccWorkflowParsed)
        .values(
            id=str(uuid.uuid4()),
            login_id=login_id,
            internal_name=internal_name,
            label=label,
            workflow_data=workflow_data,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_workflow_parsed_login_internal",
            set_={
                "label": label,
                "workflow_data": workflow_data,
                "updated_at": now,
            },
        )
    )
    await db.execute(stmt)
    await db.flush()


def _parse_rest_workflow(body: str, internal_name: str) -> dict | None:
    """
    Parse ACC REST API response for a single workflow.

    The REST API can return JSON or XML depending on Accept header and ACC version.
    If JSON: parse directly.
    If XML: fall through to parse_workflow_detail which already handles the full
    workflow XML tree including <activities>.
    """
    import xml.etree.ElementTree as ET
    from services.acc_soap import parse_workflow_detail, _local, _parse_activity, _parse_edges, _first_child

    body = body.strip()

    # JSON response (newer ACC instances)
    if body.startswith("{") or body.startswith("["):
        try:
            import json as _json
            data = _json.loads(body)
            # REST may wrap in {"content": [...]} or return the entity directly
            if isinstance(data, list):
                data = data[0] if data else {}
            if "content" in data and isinstance(data["content"], list):
                data = data["content"][0] if data["content"] else {}

            # The activities XML is usually in data["activities"] as a string or nested object
            activities_raw = data.get("activities", "")
            activities = []
            if isinstance(activities_raw, str) and activities_raw.strip():
                try:
                    acts_el = ET.fromstring(f"<activities>{activities_raw}</activities>"
                                            if not activities_raw.strip().startswith("<activities")
                                            else activities_raw)
                    for act in acts_el:
                        activities.append(_parse_activity(act))
                except ET.ParseError:
                    pass
            elif isinstance(activities_raw, dict):
                # Already parsed as object — wrap and re-parse as XML
                pass  # fall through to raw_xml parsing below

            log.info("REST JSON parse for %s: %d activities", internal_name, len(activities))
            return {
                "internalName": data.get("internalName", internal_name),
                "label": data.get("label", internal_name),
                "folder": data.get("folder", {}).get("name", "") if isinstance(data.get("folder"), dict) else str(data.get("folder", "")),
                "status": str(data.get("status", "")),
                "description": data.get("desc", ""),
                "attributes": {},
                "activities": activities,
                "edges": _parse_edges(activities),
                "variables_xml": "",
                "raw_xml": body,
            }
        except Exception as exc:
            log.warning("REST JSON parse failed for %s: %s — trying XML fallback", internal_name, exc)

    # XML response or JSON parse failed — try as workflow XML
    return parse_workflow_detail(body, internal_name)
