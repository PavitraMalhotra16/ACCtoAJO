"""
Template extraction routes.

GET  /api/templates/count         — count ACC delivery templates (isModel=1, schema=nms:delivery)
GET  /api/templates/stored-count  — count templates already stored in DB for this user
POST /api/templates/extract       — extract all templates → store raw XML + payload fields in DB
GET  /api/templates               — list stored templates with their payload-ready fields
GET  /api/templates/{id}          — single template payload-ready fields
"""

import asyncio
import json
import logging
import re
import uuid

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import (
    AccTemplateRaw, AccTemplateParsed, SourceConnection, get_db,
    DestinationConnection, TemplateFolderConfig,
    TemplateMigrationRun, TemplateJobItem,
)
from core.security import get_login_from_cookie
from pipeline.placeholder_config import RECIPIENT_MAPPINGS, get_ajo_mapping
from pipeline.template_runner import run_template_migration
from services.template_extractor import (
    count_templates,
    fetch_delivery_detail,
    fetch_template_list,
    store_raw,
    store_parsed,
)

log = logging.getLogger("acc_backend.templates")
router = APIRouter()


async def _require_acc(db: AsyncSession, login_id: str | None) -> SourceConnection:
    if not login_id:
        raise HTTPException(401, "Not authenticated — connect to ACC first")
    result = await db.execute(
        select(SourceConnection).where(SourceConnection.login_id == login_id)
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.authenticated:
        raise HTTPException(401, "ACC not authenticated — connect first")
    return conn


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
    conn = await _require_acc(db, login_id)
    total = await count_templates(
        _soap_url(conn.instance_url), conn.session_token, conn.security_token
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
    conn = await _require_acc(db, login_id)
    soap_url = _soap_url(conn.instance_url)

    # Use stored count as cursor — next batch starts where the last one ended
    stored_result = await db.execute(
        select(func.count()).select_from(AccTemplateParsed)
        .where(AccTemplateParsed.login_id == login_id)
    )
    start_line = stored_result.scalar_one()

    templates = await fetch_template_list(
        soap_url, conn.session_token, conn.security_token, start_line=start_line
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

    for meta in templates:
        try:
            existing = await db.execute(
                select(AccTemplateParsed).where(
                    AccTemplateParsed.login_id == login_id,
                    AccTemplateParsed.source_id == meta["id"],
                )
            )
            if existing.scalars().first() is not None:
                skipped += 1
                continue

            detail = await fetch_delivery_detail(
                soap_url, conn.session_token, conn.security_token, meta["id"]
            )
            if not detail:
                detail = meta

            await store_raw(db, login_id, detail, batch_id)
            await store_parsed(db, login_id, detail, batch_id)
            await db.commit()
            extracted += 1
        except Exception as exc:
            await db.rollback()
            log.warning("Failed to extract template id=%s: %s", meta.get("id"), exc)
            errors.append({"id": meta.get("id"), "error": str(exc)})

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


# ── Template migration routes ─────────────────────────────────────────────────

async def _require_ajo(db: AsyncSession) -> DestinationConnection:
    result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.authenticated == True)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(400, "AJO not connected — connect AJO first")
    return dest


async def _get_valid_ajo_token(dest: DestinationConnection, db: AsyncSession) -> str:
    from pipeline.handlers import get_valid_access_token  # deferred to avoid circular import
    return await get_valid_access_token(dest, db)


class SetupRequest(BaseModel):
    email_sample_name: str
    sms_sample_name: str


@router.post("/api/templates/setup")
async def template_setup(
    body: SetupRequest,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    dest = await _require_ajo(db)
    token = await _get_valid_ajo_token(dest, db)

    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": dest.client_id or "",
        "x-gw-ims-org-id": dest.org_id,
        "x-sandbox-name": dest.sandbox_name or "prod",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://platform.adobe.io/ajo/content/templates",
            headers=headers,
            params={"orderBy": "-modifiedAt", "limit": 200},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"AJO GET /templates failed: {resp.status_code} {resp.text[:200]}")

    items = resp.json().get("items", [])
    name_to_folder: dict[str, str] = {
        item["name"]: item.get("parentFolderId", "")
        for item in items
        if item.get("parentFolderId")
    }

    results = {}
    for channel, sample_name in [("email", body.email_sample_name), ("sms", body.sms_sample_name)]:
        folder_id = name_to_folder.get(sample_name)
        if not folder_id:
            raise HTTPException(
                404,
                f"No template named '{sample_name}' with a parentFolderId found in AJO. "
                "Create the sample template inside a folder first."
            )
        existing = await db.execute(
            select(TemplateFolderConfig).where(
                TemplateFolderConfig.destination_conn_id == dest.id,
                TemplateFolderConfig.channel == channel,
            )
        )
        cfg = existing.scalar_one_or_none()
        if cfg:
            cfg.parent_folder_id = folder_id
            cfg.folder_name = sample_name
        else:
            db.add(TemplateFolderConfig(
                destination_conn_id=dest.id,
                channel=channel,
                folder_name=sample_name,
                parent_folder_id=folder_id,
            ))
        results[channel] = folder_id

    await db.commit()
    return {"email_folder_id": results["email"], "sms_folder_id": results["sms"]}


@router.get("/api/templates/analysis")
async def template_analysis(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(AccTemplateParsed).where(AccTemplateParsed.login_id == login_id)
    )
    rows = result.scalars().all()

    re_recipient = re.compile(r"<%=\s*(recipient\.\w+)\s*%>")
    re_target = re.compile(r"<%=\s*(targetData\.\w+)\s*%>")

    unique_recipient: dict[str, str] = {}
    unique_target: dict[str, str] = {}

    for row in rows:
        if not row.template_data:
            continue
        parsed = json.loads(row.template_data)
        text = (parsed.get("htmlBody", "") or "") + " " + (parsed.get("smsContent", "") or "")
        for m in re_recipient.finditer(text):
            field = m.group(1)
            if field not in unique_recipient:
                unique_recipient[field] = get_ajo_mapping(field) or f"profile.{field.split('.', 1)[-1]}"
        for m in re_target.finditer(text):
            field = m.group(1)
            if field not in unique_target:
                unique_target[field] = f"context.{field}"

    return {
        "recipient": [
            {"acc": f"<%= {k} %>", "field": k, "ajo": v}
            for k, v in sorted(unique_recipient.items())
        ],
        "targetData": [
            {"acc": f"<%= {k} %>", "field": k, "ajo": v}
            for k, v in sorted(unique_target.items())
        ],
    }


class MigrateRequest(BaseModel):
    placeholder_map: dict[str, str]


@router.post("/api/templates/migrate")
async def template_migrate(
    body: MigrateRequest,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    dest = await _require_ajo(db)

    templates_result = await db.execute(
        select(AccTemplateParsed).where(AccTemplateParsed.login_id == login_id)
    )
    templates = templates_result.scalars().all()
    if not templates:
        raise HTTPException(400, "No templates found in acc_deliverytemplate_parsed for this user")

    run_id = str(uuid.uuid4())
    run = TemplateMigrationRun(
        run_id=run_id,
        destination_conn_id=dest.id,
        login_id=login_id,
        status="RUNNING",
        placeholder_map=json.dumps(body.placeholder_map),
    )
    db.add(run)
    await db.flush()

    items: list[dict] = []
    for tmpl in templates:
        parsed = json.loads(tmpl.template_data) if tmpl.template_data else {}
        channel = parsed.get("channel", "email")
        if channel not in ("email", "sms"):
            channel_status = "SKIPPED"
        else:
            channel_status = "PENDING"

        job_item = TemplateJobItem(
            run_id=run_id,
            source_id=tmpl.source_id,
            internal_name=parsed.get("internalName"),
            channel=channel,
            status=channel_status,
        )
        db.add(job_item)
        await db.flush()

        if channel_status == "PENDING":
            items.append({
                "id": job_item.id,
                "source_id": tmpl.source_id,
                "login_id": login_id,
                "destination_conn_id": dest.id,
                "channel": channel,
            })

    await db.commit()

    asyncio.create_task(
        run_template_migration(run_id, items, body.placeholder_map)
    )
    return {"run_id": run_id, "total": len(items)}


@router.get("/api/templates/runs/{run_id}/status")
async def template_run_status(
    run_id: str,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    run_result = await db.execute(
        select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    counts = await db.execute(
        select(
            TemplateJobItem.channel,
            TemplateJobItem.status,
            func.count().label("cnt"),
        )
        .where(TemplateJobItem.run_id == run_id)
        .group_by(TemplateJobItem.channel, TemplateJobItem.status)
    )
    rows = counts.all()

    def _tally(channel: str) -> dict:
        total = completed = failed = 0
        for r in rows:
            if r.channel == channel:
                total += r.cnt
                if r.status == "COMPLETED":
                    completed += r.cnt
                elif r.status == "FAILED":
                    failed += r.cnt
        return {"total": total, "completed": completed, "failed": failed}

    failures = []
    if run.status == "COMPLETED":
        fail_result = await db.execute(
            select(TemplateJobItem).where(
                TemplateJobItem.run_id == run_id,
                TemplateJobItem.status == "FAILED",
            )
        )
        for fi in fail_result.scalars().all():
            failures.append({
                "source_id": fi.source_id,
                "internal_name": fi.internal_name,
                "channel": fi.channel,
                "error_step": fi.error_step,
                "error_message": fi.error_message,
            })

    return {
        "status": run.status,
        "email": _tally("email"),
        "sms": _tally("sms"),
        "failures": failures,
    }
