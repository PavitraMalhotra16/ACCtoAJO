import csv
import io
import json
import logging
import re
from typing import Optional

import httpx
from dateutil import parser as dateutil_parser
from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import DestinationConnection, SchemaJobItem, get_db
from pipeline import batch_client
from pipeline.handlers import get_valid_access_token

log = logging.getLogger("acc_backend.datasets")

# ── Type-normalization helpers ────────────────────────────────────────────────

# Date/datetime: digits + separators, optional time component.
_DATE_HINT = re.compile(
    r"^\d{1,4}[/\-]\d{1,2}[/\-]\d{1,4}"
    r"([ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$"
)

# Whole-number float: e.g. "3011.00", "42.0"  (no non-zero fractional digits)
_WHOLE_FLOAT = re.compile(r"^-?\d+\.0+$")

# Boolean-like strings
_BOOL_TRUE  = {"true",  "yes", "1", "on"}
_BOOL_FALSE = {"false", "no",  "0", "off"}


def _to_iso(value: str) -> str:
    """Parse a date-like string → ISO 8601 UTC.  Returns original on failure."""
    try:
        from datetime import timezone
        dt = dateutil_parser.parse(value)
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return value


def _coerce_value(val: str) -> str:
    """Apply all type coercions to a single CSV cell value (string in, string out).

    Order matters — date check before numeric so '2023/01/15' isn't mis-coerced.
    """
    v = val.strip()
    if not v:
        return val

    # 1. Date / datetime → ISO 8601
    if _DATE_HINT.match(v):
        return _to_iso(v)

    # 2. Whole-number float → integer string  ("3011.00" → "3011")
    if _WHOLE_FLOAT.match(v):
        return str(int(float(v)))

    # 3. Boolean strings → lowercase canonical ("True" → "true", "YES" → "true")
    vl = v.lower()
    if vl in _BOOL_TRUE:
        return "true"
    if vl in _BOOL_FALSE:
        return "false"

    return val


def _normalize_csv(data: bytes) -> tuple[bytes, int]:
    """Coerce every cell in a CSV to its AEP-compatible type representation.

    Returns (normalised_bytes, cells_changed).
    """
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return data, 0

    rows = list(reader)
    if not rows:
        return data, 0

    changed = 0
    for row in rows:
        for col in reader.fieldnames:
            original = row.get(col, "")
            coerced = _coerce_value(original)
            if coerced != original:
                row[col] = coerced
                changed += 1

    if not changed:
        return data, 0

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8"), changed


def _normalize_json(data: bytes) -> tuple[bytes, int]:
    """Coerce string values in a JSON array-of-objects to AEP-compatible types.

    Returns (normalised_bytes, values_changed).
    """
    try:
        records = json.loads(data)
    except Exception:
        return data, 0

    if not isinstance(records, list):
        return data, 0

    changed = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, val in list(record.items()):
            if not isinstance(val, str):
                continue
            coerced = _coerce_value(val)
            if coerced != val:
                # For JSON, also convert numeric/bool strings to native types
                if _WHOLE_FLOAT.match(val.strip()):
                    record[key] = int(float(val.strip()))
                elif val.strip().lower() in _BOOL_TRUE:
                    record[key] = True
                elif val.strip().lower() in _BOOL_FALSE:
                    record[key] = False
                else:
                    record[key] = coerced
                changed += 1

    return json.dumps(records, ensure_ascii=False).encode("utf-8"), changed

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

    # Auto-normalize date/datetime columns to ISO 8601 before upload.
    fixed_cols = 0
    if fmt == "csv":
        file_bytes, fixed_cols = _normalize_csv(file_bytes)
    elif fmt == "json":
        file_bytes, fixed_cols = _normalize_json(file_bytes)

    if fixed_cols:
        log.info("Normalized %d value(s) (dates/ints/bools) in %s before upload", fixed_cols, file.filename)

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
