import asyncio
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_login_from_cookie
from db import ConvertedSchema, DestinationConnection, SchemaJobItem, get_db
from pipeline.runner import run_migration_job
from pipeline_steps import PIPELINE_STEPS

log = logging.getLogger("acc_backend.migrate")
router = APIRouter(prefix="/api/migrate")

# Used to ignore SchemaJobItem rows left behind by a previous pipeline design:
# a schema counts as "done" only if it completed at the current final step, and a
# FAILED row is only resumable if its step is still part of the current pipeline.
_CURRENT_STEP_NAMES = {s.name for s in PIPELINE_STEPS}
_TOTAL_STEPS = len(PIPELINE_STEPS)


def _warnings_of(item: SchemaJobItem) -> list[str]:
    """Non-fatal reconcile warnings, carried in the step snapshot (e.g. field-type
    or behavior mismatch on an already-existing schema)."""
    if not item.current_snapshot:
        return []
    try:
        snap = json.loads(item.current_snapshot)
    except (json.JSONDecodeError, TypeError):
        return []
    warnings = snap.get("warnings") if isinstance(snap, dict) else None
    return warnings if isinstance(warnings, list) else []


class MigrateStartRequest(BaseModel):
    extract_job_id: Optional[str] = None


@router.post("/start")
async def migrate_start(
    body: MigrateStartRequest = Body(default_factory=MigrateStartRequest),
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
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
        raise HTTPException(400, "AJO not connected — connect AJO before starting migration")

    # Filter by extract_job_id — only migrate schemas from this specific extraction job
    if body.extract_job_id:
        converted_result = await db.execute(
            select(ConvertedSchema).where(
                ConvertedSchema.login_id == login_id,
                ConvertedSchema.job_id == body.extract_job_id,
            )
        )
    else:
        converted_result = await db.execute(
            select(ConvertedSchema).where(ConvertedSchema.login_id == login_id)
        )
    all_converted = converted_result.scalars().all()

    # Deduplicate by schema_name — keep only the latest row per schema
    seen: set[str] = set()
    converted = []
    for s in all_converted:
        if s.schema_name not in seen:
            seen.add(s.schema_name)
            converted.append(s)
    if not converted:
        raise HTTPException(400, "No extracted schemas found — run schema extraction first")

    fresh = bool(body.extract_job_id)
    last_failed: dict[str, SchemaJobItem] = {}
    done_names: set[str] = set()

    if fresh:
        # Explicit (re-)migration from the Select page: the user just re-extracted
        # these from ACC, so migrate every schema in this job from step 0 — even ones
        # already pushed — and never resume a stale snapshot. The push reconcile is
        # idempotent, so unchanged schemas no-op and changed ones get topped up.
        to_migrate = converted
    else:
        # "Migrate everything pending" path (e.g. resume): skip schemas already pushed
        # under the current pipeline, and resume failed ones from their last snapshot.
        done_result = await db.execute(
            select(SchemaJobItem.schema_name).where(
                SchemaJobItem.login_id == login_id,
                SchemaJobItem.status == "COMPLETED",
                SchemaJobItem.current_step_order >= _TOTAL_STEPS,
            )
        )
        done_names = {row[0] for row in done_result.fetchall()}
        to_migrate = [s for s in converted if s.schema_name not in done_names]
        if not to_migrate:
            return {"message": "all_done", "total": len(converted), "skipped": len(done_names)}

        failed_result = await db.execute(
            select(SchemaJobItem).where(
                SchemaJobItem.login_id == login_id,
                SchemaJobItem.status == "FAILED",
            ).order_by(SchemaJobItem.created_at.desc())
        )
        for fi in failed_result.scalars().all():
            # Skip rows from an older pipeline design — their snapshot/step-order is
            # not compatible with the current steps, so resuming would break.
            if fi.current_step not in _CURRENT_STEP_NAMES:
                continue
            if fi.schema_name not in last_failed:
                last_failed[fi.schema_name] = fi

    job_id = str(uuid.uuid4())
    items: list[dict] = []
    for s in to_migrate:
        item = SchemaJobItem(
            job_id=job_id,
            login_id=login_id,
            schema_name=s.schema_name,
            status="QUEUED",
        )
        db.add(item)
        await db.flush()

        prev_failed = last_failed.get(s.schema_name)
        # The snapshot is taken after each *successful* step, so resume re-runs the
        # failed step itself (step_order - 1). Handlers are idempotent, so re-running
        # an already-applied step is safe.
        resume_from_step = max(0, prev_failed.current_step_order - 1) if prev_failed and prev_failed.current_snapshot else 0
        resume_data = json.loads(prev_failed.current_snapshot) if prev_failed and prev_failed.current_snapshot else None

        items.append({
            "id": item.id,
            "schema_name": s.schema_name,
            "converted_schema_id": s.id,
            "resume_from_step": resume_from_step,
            "resume_data": resume_data,
        })
    await db.commit()

    asyncio.create_task(run_migration_job(job_id, login_id, items, dest.org_id))

    return {
        "job_id": job_id,
        "message": "started",
        "total": len(converted),
        "queued": len(to_migrate),
        "skipped": len(done_names),
    }


@router.get("/status/{job_id}")
async def migrate_status(
    job_id: str,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(SchemaJobItem)
        .where(SchemaJobItem.job_id == job_id)
        .order_by(SchemaJobItem.created_at)
    )
    items = result.scalars().all()
    if not items:
        raise HTTPException(404, "Job not found")

    return {
        "job_id": job_id,
        "total": len(items),
        "completed": sum(1 for i in items if i.status == "COMPLETED"),
        "running": sum(1 for i in items if i.status == "RUNNING"),
        "queued": sum(1 for i in items if i.status == "QUEUED"),
        "failed": sum(1 for i in items if i.status == "FAILED"),
        "started_at": items[0].created_at.isoformat() if items else None,
        "schemas": [
            {
                "id": i.id,
                "schema_name": i.schema_name,
                "status": i.status,
                "current_step": i.current_step,
                "current_step_order": i.current_step_order,
                "identity_is_primary": i.identity_is_primary,
                "error_message": i.error_message,
                "warnings": _warnings_of(i),
                "created_at": i.created_at.isoformat(),
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
            }
            for i in items
        ],
    }


@router.get("/incomplete")
async def incomplete_schemas(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Return the latest pipeline state per schema that has started but not COMPLETED."""
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(SchemaJobItem)
        .where(SchemaJobItem.login_id == login_id)
        .order_by(SchemaJobItem.created_at.desc())
    )
    all_items = result.scalars().all()

    # For each schema look only at its *latest* item: surface it as incomplete only
    # if that latest item is still RUNNING/FAILED/QUEUED. A newer COMPLETED item means
    # it's done, so an older FAILED row must not resurface. Skip old-pipeline rows.
    seen: set[str] = set()
    items = []
    for i in all_items:
        if i.schema_name in seen:
            continue
        seen.add(i.schema_name)
        if i.current_step is not None and i.current_step not in _CURRENT_STEP_NAMES:
            continue
        if i.status in ("RUNNING", "FAILED", "QUEUED"):
            items.append(i)

    return {
        "schemas": [
            {
                "schema_name": i.schema_name,
                "status": i.status,
                "current_step": i.current_step,
                "current_step_order": i.current_step_order or 0,
                "error_message": i.error_message,
            }
            for i in items
        ]
    }


@router.get("/completed")
async def completed_schemas(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Schema names that have been fully pushed to AJO under the current pipeline."""
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    result = await db.execute(
        select(SchemaJobItem.schema_name).where(
            SchemaJobItem.login_id == login_id,
            SchemaJobItem.status == "COMPLETED",
            SchemaJobItem.current_step_order >= _TOTAL_STEPS,
        )
    )
    return {"schemas": sorted({row[0] for row in result.fetchall()})}


@router.get("/jobs")
async def list_jobs(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(SchemaJobItem.job_id, SchemaJobItem.created_at)
        .where(SchemaJobItem.login_id == login_id)
        .distinct(SchemaJobItem.job_id)
        .order_by(SchemaJobItem.job_id, SchemaJobItem.created_at.desc())
    )
    rows = result.fetchall()
    # Sort by created_at desc after deduplication
    sorted_rows = sorted(rows, key=lambda r: r[1], reverse=True)
    return {"jobs": [{"job_id": r[0], "created_at": r[1].isoformat()} for r in sorted_rows]}


@router.get("/schema/{item_id}")
async def schema_item_detail(
    item_id: str,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(SchemaJobItem).where(SchemaJobItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Schema item not found")
    return {
        "id": item.id,
        "schema_name": item.schema_name,
        "status": item.status,
        "current_step": item.current_step,
        "current_step_order": item.current_step_order,
        "identity_is_primary": item.identity_is_primary,
        "error_message": item.error_message,
        "warnings": _warnings_of(item),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
