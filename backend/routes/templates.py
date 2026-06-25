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
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AccTemplateRaw, AccTemplateParsed, SourceConnection, get_db
from core.security import get_login_from_cookie, get_valid_acc_token, acc_soap_headers
from db import (
    AccTemplateRaw, AccTemplateParsed, AsyncSessionLocal, SourceConnection, get_db,
    DestinationConnection, TemplateFolderConfig,
    TemplateMigrationRun, TemplateJobItem,
)
from core.security import get_login_from_cookie, get_valid_acc_token
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

# Templates that must never be extracted or migrated regardless of what ACC returns
_EXCLUDED_INTERNAL_NAMES = {"notifyWkfToStop"}


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


async def _soap_offset(db: AsyncSession, login_id: str) -> int:
    """Total rows in DB for this user — used as SOAP start_line so we skip already-fetched templates."""
    result = await db.execute(
        select(func.count()).select_from(AccTemplateParsed)
        .where(AccTemplateParsed.login_id == login_id)
    )
    return result.scalar() or 0


async def _count_valid_stored(db: AsyncSession, login_id: str) -> int:
    """Count stored templates excluding any that carry an excluded internalName.
    Used for display and to_migrate calculation — does not include excluded rows."""
    result = await db.execute(
        select(AccTemplateParsed.template_data)
        .where(AccTemplateParsed.login_id == login_id)
    )
    return sum(
        1 for td in result.scalars().all()
        if json.loads(td or "{}").get("internalName") not in _EXCLUDED_INTERNAL_NAMES
    )


@router.get("/api/templates/stored-count")
async def get_stored_count(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        return {"stored": 0}  # session may have briefly expired during polling — return 0 silently
    return {"stored": await _count_valid_stored(db, login_id)}


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
    stored = await _count_valid_stored(db, login_id)
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

    # Cursor = total rows in DB (including excluded) so the SOAP offset stays aligned
    # with ACC's fixed ordering even when some rows were previously skipped/excluded
    start_line = await _soap_offset(db, login_id)

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

    for meta in templates:
        try:
            if meta.get("internalName") in _EXCLUDED_INTERNAL_NAMES:
                skipped += 1
                continue

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
                soap_url, token, conn.security_token or "", meta["id"]
            )
            if not detail:
                detail = meta

            await store_raw(db, login_id, detail, batch_id)
            await store_parsed(db, login_id, detail, batch_id)
            await db.commit()
            extracted += 1

        except Exception as exc:
            await db.rollback()
            log.warning("Failed to process template id=%s: %s", meta.get("id"), exc)
            errors.append({"id": meta.get("id"), "error": str(exc)})

    return {"extracted": extracted, "total_found": len(templates), "skipped": skipped,
            "batch_id": batch_id, "errors": errors}


@router.delete("/api/templates/stored")
async def clear_stored_templates(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Delete all previously stored templates for this user so extraction always starts fresh."""
    from sqlalchemy import delete as sa_delete
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    await db.execute(sa_delete(AccTemplateParsed).where(AccTemplateParsed.login_id == login_id))
    await db.execute(sa_delete(AccTemplateRaw).where(AccTemplateRaw.login_id == login_id))
    await db.commit()
    log.info("Cleared stored templates for login_id=%s", login_id)
    return {"cleared": True}


# ── Template migration routes ─────────────────────────────────────────────────

@router.get("/api/templates/folder-config")
async def get_folder_config(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    dest_result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.authenticated == True)
    )
    dest = dest_result.scalar_one_or_none()
    if not dest:
        return {"configured": False}

    rows = await db.execute(
        select(TemplateFolderConfig).where(TemplateFolderConfig.destination_conn_id == dest.id)
    )
    configs = {r.channel: r for r in rows.scalars().all()}
    if "email" not in configs or "sms" not in configs:
        return {"configured": False}

    return {
        "configured": True,
        "email_folder_name": configs["email"].folder_name,
        "email_folder_id": configs["email"].parent_folder_id,
        "sms_folder_name": configs["sms"].folder_name,
        "sms_folder_id": configs["sms"].parent_folder_id,
    }

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
        "x-api-key": (dest.client_id or "").strip(),
        "x-gw-ims-org-id": dest.org_id.strip(),
        "x-sandbox-name": (dest.sandbox_name or "prod").strip(),
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
    rows = [
        r for r in result.scalars().all()
        if json.loads(r.template_data or "{}").get("internalName") not in _EXCLUDED_INTERNAL_NAMES
    ]

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
                # Use config mapping if known; otherwise show raw field for user to edit
                unique_recipient[field] = get_ajo_mapping(field) or field
        for m in re_target.finditer(text):
            field = m.group(1)
            if field not in unique_target:
                # No config for targetData — show raw field, user decides the AJO path
                unique_target[field] = field

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
    templates = [
        t for t in templates_result.scalars().all()
        if json.loads(t.template_data or "{}").get("internalName") not in _EXCLUDED_INTERNAL_NAMES
    ]
    if not templates:
        raise HTTPException(400, "No templates found in acc_deliverytemplate_parsed for this user")

    # Find source_ids that already completed successfully in any prior run for this user —
    # so we never push the same template twice.
    completed_result = await db.execute(
        select(TemplateJobItem.source_id)
        .join(TemplateMigrationRun, TemplateJobItem.run_id == TemplateMigrationRun.run_id)
        .where(
            TemplateMigrationRun.login_id == login_id,
            TemplateJobItem.status == "COMPLETED",
        )
    )
    already_done: set[str] = {row[0] for row in completed_result.all()}

    # For failed templates, find the latest failed item per source_id so we can resume
    # from the step before where it broke rather than restarting from step 1.
    failed_result = await db.execute(
        select(TemplateJobItem)
        .join(TemplateMigrationRun, TemplateJobItem.run_id == TemplateMigrationRun.run_id)
        .where(
            TemplateMigrationRun.login_id == login_id,
            TemplateJobItem.status == "FAILED",
        )
        .order_by(TemplateJobItem.created_at.desc())
    )
    last_failed: dict[str, TemplateJobItem] = {}
    for fi in failed_result.scalars().all():
        if fi.source_id not in last_failed:
            last_failed[fi.source_id] = fi

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
    skipped_already_done = 0
    for tmpl in templates:
        parsed = json.loads(tmpl.template_data) if tmpl.template_data else {}
        channel = parsed.get("channel", "email")

        # Already fully migrated — skip entirely, no DB row needed
        if tmpl.source_id in already_done:
            skipped_already_done += 1
            continue

        # Unsupported channel — skip without creating a job row
        if channel not in ("email", "sms"):
            continue

        prev_failed = last_failed.get(tmpl.source_id)
        resume_from_step = max(0, (prev_failed.current_step_order or 1) - 1) if prev_failed else 0

        job_item = TemplateJobItem(
            run_id=run_id,
            source_id=tmpl.source_id,
            internal_name=parsed.get("internalName"),
            channel=channel,
            status="PENDING",
        )
        db.add(job_item)
        await db.flush()

        items.append({
            "id": job_item.id,
            "source_id": tmpl.source_id,
            "login_id": login_id,
            "destination_conn_id": dest.id,
            "channel": channel,
            "resume_from_step": resume_from_step,
        })

    await db.commit()

    if not items:
        # Nothing new to migrate — mark run complete immediately
        async with AsyncSessionLocal() as close_db:
            res = await close_db.execute(select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id))
            run_row = res.scalar_one()
            run_row.status = "COMPLETED"
            run_row.completed_at = datetime.now(timezone.utc)
            await close_db.commit()
        return {"run_id": run_id, "total": 0, "skipped_already_migrated": skipped_already_done}

    asyncio.create_task(
        run_template_migration(run_id, items, body.placeholder_map)
    )
    return {"run_id": run_id, "total": len(items), "skipped_already_migrated": skipped_already_done}


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
