import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import DestinationConnection, SchemaJobItem, get_db
from pipeline import batch_client
from pipeline.handlers import get_valid_access_token

log = logging.getLogger("acc_backend.datasets")

router = APIRouter(prefix="/api/datasets")

_SUPPORTED_FORMATS = {"csv": "csv", "json": "json", "parquet": "parquet"}
_MAX_BYTES = 256 * 1024 * 1024  # 256 MB single-upload limit
_SUCCESS_STATUSES = ("COMPLETED", "UPDATED", "ALREADY_EXISTS")


def _detect_format(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    fmt = _SUPPORTED_FORMATS.get(ext)
    if not fmt:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '.{ext}'. Supported formats: csv, json, parquet.",
        )
    return fmt


def _step(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


async def _require_ajo(db: AsyncSession) -> DestinationConnection:
    result = await db.execute(
        select(DestinationConnection)
        .where(DestinationConnection.authenticated == True)
        .order_by(DestinationConnection.last_authenticated_at.desc())
        .limit(1)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(status_code=401, detail="AJO not connected — connect first")
    return dest


@router.get("/schemas")
async def list_dataset_schemas(
    db: AsyncSession = Depends(get_db),
    acc_session: Optional[str] = Cookie(default=None),
):
    """Return all successfully migrated schemas that have an AEP dataset ID.

    Deduplicates by schema_name, keeping the most recent successful run.
    """
    await _require_ajo(db)

    # Use subquery approach for portable deduplication (avoids DISTINCT ON which is Postgres-specific)
    subq = (
        select(SchemaJobItem.schema_name, func.max(SchemaJobItem.updated_at).label("max_updated"))
        .where(
            SchemaJobItem.aep_dataset_id.isnot(None),
            SchemaJobItem.status.in_(_SUCCESS_STATUSES),
        )
        .group_by(SchemaJobItem.schema_name)
        .subquery()
    )
    result = await db.execute(
        select(SchemaJobItem.schema_name, SchemaJobItem.aep_dataset_id)
        .join(
            subq,
            (SchemaJobItem.schema_name == subq.c.schema_name)
            & (SchemaJobItem.updated_at == subq.c.max_updated),
        )
    )
    rows = result.all()
    return [{"schema_name": r.schema_name, "aep_dataset_id": r.aep_dataset_id} for r in rows]


@router.post("/ingest")
async def ingest_dataset(
    schema_name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    acc_session: Optional[str] = Cookie(default=None),
):
    """Upload a CSV/JSON/Parquet file into the AEP dataset for the given schema."""
    dest = await _require_ajo(db)

    # Resolve dataset ID from schema_job_items
    result = await db.execute(
        select(SchemaJobItem)
        .where(
            SchemaJobItem.schema_name == schema_name,
            SchemaJobItem.aep_dataset_id.isnot(None),
            SchemaJobItem.status.in_(_SUCCESS_STATUSES),
        )
        .order_by(SchemaJobItem.updated_at.desc())
        .limit(1)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"No migrated dataset found for schema '{schema_name}'",
        )
    dataset_id = item.aep_dataset_id

    # Validate file format from extension
    fmt = _detect_format(file.filename or "")

    # Read file bytes
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 256 MB single-upload limit")

    size_label = (
        f"{len(file_bytes) / 1024:.1f} KB"
        if len(file_bytes) < 1_048_576
        else f"{len(file_bytes) / 1_048_576:.1f} MB"
    )

    # Get valid access token (auto-refresh if expired)
    try:
        token = await get_valid_access_token(dest, db)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": (dest.client_id or "").strip(),
        "x-gw-ims-org-id": dest.org_id.strip(),
        "x-sandbox-name": (dest.sandbox_name or "prod").strip(),
    }

    steps: list[dict] = []
    batch_id: str = ""

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Step 1 — Create batch
        try:
            batch = await batch_client.create_batch(client, headers, dataset_id, fmt)
            batch_id = batch.get("id", "")
            steps.append(_step("CREATE_BATCH", "COMPLETED", f"Batch {batch_id} created"))
        except Exception as exc:
            steps.append(_step("CREATE_BATCH", "FAILED", str(exc)))
            steps.append(_step("UPLOAD_FILE", "SKIPPED", "Skipped — batch creation failed"))
            steps.append(_step("COMPLETE_BATCH", "SKIPPED", "Skipped — batch creation failed"))
            return {"batch_id": "", "steps": steps, "status": "FAILED"}

        # Step 2 — Upload file
        try:
            await batch_client.upload_file(
                client, headers, batch_id, dataset_id, file.filename or "upload", file_bytes
            )
            steps.append(_step("UPLOAD_FILE", "COMPLETED", f"Uploaded {file.filename} ({size_label})"))
        except Exception as exc:
            steps.append(_step("UPLOAD_FILE", "FAILED", str(exc)))
            steps.append(_step("COMPLETE_BATCH", "SKIPPED", "Skipped — upload failed"))
            return {"batch_id": batch_id, "steps": steps, "status": "FAILED"}

        # Step 3 — Complete batch
        try:
            await batch_client.complete_batch(client, headers, batch_id)
            steps.append(_step("COMPLETE_BATCH", "COMPLETED", "Batch signaled as complete — ingestion queued"))
        except Exception as exc:
            steps.append(_step("COMPLETE_BATCH", "FAILED", str(exc)))
            return {"batch_id": batch_id, "steps": steps, "status": "FAILED"}

    log.info(
        "Dataset ingest complete: batch=%s schema=%s dataset=%s file=%s",
        batch_id, schema_name, dataset_id, file.filename,
    )
    return {"batch_id": batch_id, "steps": steps, "status": "SUCCESS"}
