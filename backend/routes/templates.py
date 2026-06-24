"""
Template extraction routes.

GET  /api/templates/count         — count ACC delivery templates (isModel=1, schema=nms:delivery)
GET  /api/templates/stored-count  — count templates already stored in DB for this user
POST /api/templates/extract       — extract all templates → store raw XML + payload fields in DB
GET  /api/templates               — list stored templates with their payload-ready fields
GET  /api/templates/{id}          — single template payload-ready fields
"""

import json
import logging
import uuid

from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AccTemplateRaw, AccTemplateParsed, SourceConnection, get_db
from core.security import get_login_from_cookie, get_valid_acc_token, acc_soap_headers
from services.template_extractor import (
    count_templates,
    fetch_delivery_detail,
    fetch_template_list,
    store_raw,
    store_parsed,
)

log = logging.getLogger("acc_backend.templates")
router = APIRouter()


async def _require_acc(db: AsyncSession, login_id: str | None) -> tuple[SourceConnection, str]:
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
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    return conn, token


def _soap_url(instance_url: str) -> str:
    return instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"


@router.get("/api/templates/stored-count")
async def get_stored_count(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        return {"stored": 0}  # session may have briefly expired during polling — return 0 silently
    result = await db.execute(
        select(func.count()).select_from(AccTemplateParsed)
        .where(AccTemplateParsed.login_id == login_id)
    )
    return {"stored": result.scalar_one()}


@router.get("/api/templates/count")
async def get_template_count(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    conn, token = await _require_acc(db, login_id)
    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)
    total = await count_templates(
        _soap_url(conn.instance_url), soap_token, conn.security_token or "", auth_headers=auth_hdrs
    )
    stored_result = await db.execute(
        select(func.count()).select_from(AccTemplateParsed)
        .where(AccTemplateParsed.login_id == login_id)
    )
    stored = stored_result.scalar_one()
    to_migrate = max(0, total - stored)
    return {"total": total, "stored": stored, "to_migrate": to_migrate}


@router.post("/api/templates/extract")
async def extract_templates(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    conn, token = await _require_acc(db, login_id)
    soap_url = _soap_url(conn.instance_url)
    soap_token = "" if conn.auth_type == "technical" else token
    auth_hdrs = acc_soap_headers(conn, token)

    # Use raw count as cursor — next batch starts after all templates already fetched from ACC
    stored_result = await db.execute(
        select(func.count()).select_from(AccTemplateRaw)
        .where(AccTemplateRaw.login_id == login_id)
    )
    start_line = stored_result.scalar_one()

    templates = await fetch_template_list(
        soap_url, soap_token, conn.security_token or "", start_line=start_line, auth_headers=auth_hdrs
    )
    log.info("ACC template list returned %d template(s) (start_line=%d)", len(templates), start_line)
    if not templates:
        return {"extracted": 0, "total_found": 0, "skipped": 0, "batch_id": None, "errors": []}

    batch_id = str(uuid.uuid4())
    extracted = 0
    skipped = 0
    errors = []

    log.info("Processing batch (batch_id=%s): %d template(s) starting at offset %d",
             batch_id, len(templates), start_line)

    # Pre-load source_ids already in raw and parsed — one query each, used for all templates.
    raw_ids_result = await db.execute(
        select(AccTemplateRaw.source_id).where(AccTemplateRaw.login_id == login_id)
    )
    already_in_raw: set[str] = {r[0] for r in raw_ids_result.all()}

    parsed_ids_result = await db.execute(
        select(AccTemplateParsed.source_id).where(AccTemplateParsed.login_id == login_id)
    )
    already_in_parsed: set[str] = {r[0] for r in parsed_ids_result.all()}

    for meta in templates:
        tid = meta["id"]
        try:
            detail = None

            # Step 1: store raw only if not already extracted
            if tid not in already_in_raw:
                detail = await fetch_delivery_detail(
                    soap_url, soap_token, conn.security_token or "", tid, auth_headers=auth_hdrs
                )
                if not detail:
                    detail = meta
                await store_raw(db, login_id, detail, batch_id)
                already_in_raw.add(tid)

            # Step 2: store parsed only if not already parsed
            if tid not in already_in_parsed:
                if detail is None:
                    # Raw exists in DB but parsed doesn't — reload from stored raw XML
                    raw_row_result = await db.execute(
                        select(AccTemplateRaw).where(
                            AccTemplateRaw.login_id == login_id,
                            AccTemplateRaw.source_id == tid,
                        )
                    )
                    raw_row = raw_row_result.scalars().first()
                    if raw_row and raw_row.raw_xml:
                        from services.acc_soap import parse_delivery_detail
                        detail = parse_delivery_detail(raw_row.raw_xml)
                    else:
                        detail = meta
                await store_parsed(db, login_id, detail, batch_id)
                already_in_parsed.add(tid)
                await db.commit()
                extracted += 1
            else:
                skipped += 1

        except Exception as exc:
            await db.rollback()
            log.warning("Failed to process template id=%s: %s", tid, exc)
            errors.append({"id": tid, "error": str(exc)})

    return {"extracted": extracted, "total_found": len(templates), "skipped": skipped,
            "batch_id": batch_id, "errors": errors}


@router.get("/api/templates")
async def list_templates(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(
        select(AccTemplateNormalized)
        .where(AccTemplateNormalized.login_id == login_id)
        .order_by(AccTemplateNormalized.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        {
            "id": r.id,
            "payloadFields": json.loads(r.payload_fields_json) if r.payload_fields_json else None,
        }
        for r in rows
    ]


@router.get("/api/templates/{template_id}")
async def get_template(
    template_id: str,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(
        select(AccTemplateNormalized).where(
            AccTemplateNormalized.id == template_id,
            AccTemplateNormalized.login_id == login_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Template not found")
    return {
        "id": row.id,
        "payloadFields": json.loads(row.payload_fields_json) if row.payload_fields_json else None,
    }
