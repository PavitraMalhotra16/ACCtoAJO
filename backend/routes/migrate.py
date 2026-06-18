import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_login_from_cookie
from db import ConvertedSchema, DestinationConnection, SchemaJobItem, get_db
from pipeline.runner import run_migration_job

log = logging.getLogger("acc_backend.migrate")
router = APIRouter(prefix="/api/migrate")


@router.post("/start")
async def migrate_start(
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

    converted_result = await db.execute(
        select(ConvertedSchema).where(ConvertedSchema.login_id == login_id)
    )
    converted = converted_result.scalars().all()
    if not converted:
        raise HTTPException(400, "No extracted schemas found — run schema extraction first")

    done_result = await db.execute(
        select(SchemaJobItem.schema_name).where(
            SchemaJobItem.login_id == login_id,
            SchemaJobItem.status == "COMPLETED",
        )
    )
    done_names = {row[0] for row in done_result.fetchall()}

    to_migrate = [s for s in converted if s.schema_name not in done_names]
    if not to_migrate:
        return {
            "message": "all_done",
            "total": len(converted),
            "skipped": len(done_names),
        }

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
        items.append({
            "id": item.id,
            "schema_name": s.schema_name,
            "storage_path": s.storage_path,
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
async def migrate_status(job_id: str, db: AsyncSession = Depends(get_db)):
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
        "schemas": [
            {
                "id": i.id,
                "schema_name": i.schema_name,
                "status": i.status,
                "current_step": i.current_step,
                "current_step_order": i.current_step_order,
                "identity_is_primary": i.identity_is_primary,
                "error_message": i.error_message,
                "completed_at": i.completed_at.isoformat() if i.completed_at else None,
            }
            for i in items
        ],
    }


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
        .order_by(SchemaJobItem.created_at.desc())
    )
    rows = result.fetchall()
    return {"jobs": [{"job_id": r[0], "created_at": r[1].isoformat()} for r in rows]}


@router.get("/schema/{item_id}")
async def schema_item_detail(item_id: str, db: AsyncSession = Depends(get_db)):
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
        "tmp_file_path": item.tmp_file_path,
        "final_file_path": item.final_file_path,
        "error_message": item.error_message,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }
