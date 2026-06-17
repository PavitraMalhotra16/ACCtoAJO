"""
Routes for converting ACC schemas to JSON format.
POST /api/convert/start   — start background conversion job
GET  /api/convert/status/{job_id} — poll progress
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.acc_soap import build_schema_inventory_envelope, build_srcschema_get_envelope, parse_fault, parse_schema_inventory
from db import AsyncSessionLocal, ConvertedSchema, SourceConnection, get_db
from services.schema_inspector import parse_schema_to_xdm
from storage import save_schema
from core.security import get_login_from_cookie

log = logging.getLogger("acc_backend.conversion")
router = APIRouter(prefix="/api/convert")

SOAP_TIMEOUT = 30.0
_jobs: dict[str, dict] = {}

EXCLUDED_NAMESPACES = {"crm", "ncm", "nms", "xtk"}


class SchemaRef(BaseModel):
    namespace: str
    name: str
    label: Optional[str] = None


class ConvertStartRequest(BaseModel):
    schemas: list[SchemaRef]


async def _run_conversion_job(job_id: str, schemas: list[SchemaRef], acc_conn, login_id: str):
    job = _jobs[job_id]
    job["status"] = "running"
    soap_url = acc_conn.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
        "Cookie": f"__sessiontoken={acc_conn.session_token}",
        "X-Security-Token": acc_conn.security_token,
    }

    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as soap:
        for s in schemas:
            key = f"{s.namespace}:{s.name}"
            job["current_schema"] = key

            step = {
                "schemaName": key,
                "status": "running",
                "error": None,
            }
            job["steps"].append(step)

            try:
                # Fetch raw XML via xtk:srcSchema
                resp = await soap.post(
                    soap_url,
                    content=build_srcschema_get_envelope(
                        acc_conn.session_token, acc_conn.security_token, s.namespace, s.name),
                    headers=headers,
                )
                fault = parse_fault(resp.text)
                if fault:
                    raise ValueError(f"SOAP fault: {fault}")

                # Convert XML → JSON
                parsed = parse_schema_to_xdm(resp.text, s.namespace, s.name)
                if not parsed:
                    raise ValueError("Could not parse schema XML")

                # Save JSON to disk, store path in DB
                file_path = save_schema(login_id, job_id, key, parsed)
                async with AsyncSessionLocal() as db_session:
                    db_session.add(ConvertedSchema(
                        job_id=job_id,
                        login_id=login_id,
                        schema_name=key,
                        namespace=s.namespace,
                        storage_path=file_path,
                    ))
                    await db_session.commit()

                step["status"] = "success"
                job["success_count"] += 1
                log.info("Converted %s", key)

            except Exception as e:
                step["status"] = "failed"
                step["error"] = str(e)
                job["failed_count"] += 1
                log.error("Failed to convert %s: %s", key, e)

    job["status"] = "completed"
    job["current_schema"] = None
    log.info("Conversion job %s done — %d success, %d failed",
             job_id, job["success_count"], job["failed_count"])


@router.post("/start")
async def convert_start(
    body: ConvertStartRequest,
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "ACC not authenticated")

    r = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    acc = r.scalar_one_or_none()
    if not acc or not acc.session_token:
        raise HTTPException(401, "ACC session not found")

    if not body.schemas:
        raise HTTPException(400, "No schemas selected")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id":             job_id,
        "status":         "pending",
        "schema_count":   len(body.schemas),
        "current_schema": None,
        "steps":          [],
        "success_count":  0,
        "failed_count":   0,
    }

    asyncio.create_task(_run_conversion_job(job_id, body.schemas, acc, login_id))
    return {"job_id": job_id}


@router.post("/start-all")
async def convert_start_all(
    acc_session: Optional[str] = Cookie(default=None),
    acc_user: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "ACC not authenticated")

    r = await db.execute(select(SourceConnection).where(SourceConnection.login_id == login_id))
    acc = r.scalar_one_or_none()
    if not acc or not acc.session_token:
        raise HTTPException(401, "ACC session not found")

    # Fetch all schemas from ACC
    soap_url = acc.instance_url.rstrip("/") + "/nl/jsp/soaprouter.jsp"
    async with httpx.AsyncClient(timeout=SOAP_TIMEOUT) as client:
        resp = await client.post(
            soap_url,
            content=build_schema_inventory_envelope(acc.session_token, acc.security_token),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
                "Cookie": f"__sessiontoken={acc.session_token}",
                "X-Security-Token": acc.security_token,
            },
        )
    fault = parse_fault(resp.text)
    if fault:
        raise HTTPException(400, fault)

    all_schemas = parse_schema_inventory(resp.text)

    # Filter out excluded namespaces
    schemas = [
        SchemaRef(namespace=s["namespace"], name=s["name"], label=s.get("label", ""))
        for s in all_schemas
        if s.get("namespace", "").lower() not in EXCLUDED_NAMESPACES
    ]

    if not schemas:
        raise HTTPException(400, "No schemas found after filtering")

    # Check which schemas are already converted in DB
    already_done_result = await db.execute(
        select(ConvertedSchema.schema_name).where(ConvertedSchema.login_id == login_id)
    )
    already_done = {row[0] for row in already_done_result.fetchall()}

    schemas_to_convert = [
        s for s in schemas
        if f"{s.namespace}:{s.name}" not in already_done
    ]

    if not schemas_to_convert:
        return {"job_id": None, "message": "all_done", "total": len(schemas), "skipped": len(already_done)}

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id":             job_id,
        "status":         "pending",
        "schema_count":   len(schemas_to_convert),
        "skipped_count":  len(schemas) - len(schemas_to_convert),
        "current_schema": None,
        "steps":          [],
        "success_count":  0,
        "failed_count":   0,
    }

    asyncio.create_task(_run_conversion_job(job_id, schemas_to_convert, acc, login_id))
    return {"job_id": job_id, "message": "started", "total": len(schemas), "skipped": len(schemas) - len(schemas_to_convert)}


@router.get("/status/{job_id}")
async def convert_status(job_id: str, db: AsyncSession = Depends(get_db)):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {
        "id":             job["id"],
        "status":         job["status"],
        "schema_count":   job["schema_count"],
        "skipped_count":  job.get("skipped_count", 0),
        "current_schema": job["current_schema"],
        "success_count":  job["success_count"],
        "failed_count":   job["failed_count"],
        "steps":          job["steps"],
    }
