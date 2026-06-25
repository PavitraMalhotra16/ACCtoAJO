"""
ACC template extraction — SOAP calls + DB persistence.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import AccTemplateRaw, AccTemplateParsed
from services.acc_soap import (
    build_count_templates_envelope,
    build_list_templates_envelope,
    build_get_delivery_envelope,
    parse_count_response,
    parse_template_list,
    parse_delivery_detail,
    parse_fault,
)

log = logging.getLogger("acc_backend.template_extractor")


def _soap_headers(session_token: str, security_token: str, action: str = "xtk:queryDef#ExecuteQuery") -> dict:
    return {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": action,
        "Cookie": f"__sessiontoken={session_token}",
        "X-Security-Token": security_token,
    }


async def count_templates(soap_url: str, session_token: str, security_token: str, auth_headers: dict | None = None) -> int:
    headers = {**_HEADERS, **(auth_headers or {})}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            soap_url,
            content=build_count_templates_envelope(session_token, security_token),
<<<<<<< HEAD
            headers=headers,
=======
            headers=_soap_headers(session_token, security_token),
>>>>>>> origin/template_ajo
        )
    if resp.status_code != 200:
        raise RuntimeError(parse_fault(resp.text) or f"HTTP {resp.status_code} from ACC count")
    return parse_count_response(resp.text)


async def fetch_template_list(
    soap_url: str, session_token: str, security_token: str, start_line: int = 0, auth_headers: dict | None = None
) -> list[dict]:
    """Fetch exactly one page of templates from ACC starting at start_line."""
    page_size = settings.template_page_size
    headers = {**_HEADERS, **(auth_headers or {})}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            soap_url,
            content=build_list_templates_envelope(session_token, security_token, page_size, start_line),
<<<<<<< HEAD
            headers=headers,
=======
            headers=_soap_headers(session_token, security_token),
>>>>>>> origin/template_ajo
        )
    if resp.status_code != 200:
        raise RuntimeError(parse_fault(resp.text) or f"HTTP {resp.status_code} fetching template list")
    return parse_template_list(resp.text)


async def fetch_delivery_detail(
    soap_url: str, session_token: str, security_token: str, delivery_id: str, auth_headers: dict | None = None
) -> dict:
    headers = {**_HEADERS, **(auth_headers or {})}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            soap_url,
            content=build_get_delivery_envelope(session_token, security_token, delivery_id),
<<<<<<< HEAD
            headers=headers,
=======
            headers=_soap_headers(session_token, security_token),
>>>>>>> origin/template_ajo
        )
    if resp.status_code != 200:
        raise RuntimeError(parse_fault(resp.text) or f"HTTP {resp.status_code} fetching delivery id={delivery_id}")
    return parse_delivery_detail(resp.text)


async def store_raw(db: AsyncSession, login_id: str, detail: dict, batch_id: str) -> AccTemplateRaw:
    """Store raw delivery XML in acc_template_raw."""
    existing = await db.execute(
        select(AccTemplateRaw).where(
            AccTemplateRaw.login_id == login_id,
            AccTemplateRaw.source_id == detail["id"],
        )
    )
    row = existing.scalars().first()
    if row is None:
        row = AccTemplateRaw(
            id=str(uuid.uuid4()),
            login_id=login_id,
            source_id=detail["id"],
            batch_id=batch_id,
            raw_xml=detail.get("rawXml"),
        )
        db.add(row)
    else:
        row.raw_xml = detail.get("rawXml")
        row.batch_id = batch_id
        row.fetched_at = datetime.now(timezone.utc)
    await db.flush()
    return row


async def store_parsed(db: AsyncSession, login_id: str, detail: dict, batch_id: str) -> AccTemplateParsed:
    """Store parsed JSON fields in acc_template_parsed."""
    existing = await db.execute(
        select(AccTemplateParsed).where(
            AccTemplateParsed.login_id == login_id,
            AccTemplateParsed.source_id == detail["id"],
        )
    )
    row = existing.scalars().first()
    channel = detail.get("channel", "email")
    base = {
        "sourceId": detail["id"],
        "internalName": detail.get("internalName"),
        "label": detail.get("label"),
        "description": detail.get("description"),
        "channel": channel,
        "lastModified": detail.get("lastModified"),
    }
    if channel == "sms":
        base["smsContent"] = detail.get("smsRaw")
    else:
        base["subject"] = detail.get("subjectRaw")
        base["htmlBody"] = detail.get("htmlRaw")
        base["textBody"] = detail.get("textRaw")
    template_data = json.dumps(base, ensure_ascii=False)
    if row is None:
        row = AccTemplateParsed(
            id=str(uuid.uuid4()),
            login_id=login_id,
            source_id=detail["id"],
            batch_id=batch_id,
            template_data=template_data,
        )
        db.add(row)
    else:
        row.template_data = template_data
        row.batch_id = batch_id
        row.created_at = datetime.now(timezone.utc)
    await db.flush()
    return row
