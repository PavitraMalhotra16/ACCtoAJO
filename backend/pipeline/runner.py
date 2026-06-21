import asyncio
import importlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db import AsyncSessionLocal, ConvertedSchema, SchemaJobItem
from pipeline_steps import PIPELINE_STEPS

log = logging.getLogger("acc_backend.pipeline.runner")

_GLOBAL_SEM = asyncio.Semaphore(10)


async def _load_handler(dotted_path: str):
    module_path, fn_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


async def _update_item(
    item_id: str,
    status: str,
    step_name: str,
    step_order: int,
    error: str | None = None,
    identity_is_primary: bool | None = None,
    current_snapshot: str | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SchemaJobItem).where(SchemaJobItem.id == item_id)
        )
        item = result.scalar_one()
        item.status = status
        item.current_step = step_name
        item.current_step_order = step_order
        item.updated_at = datetime.now(timezone.utc)
        if error is not None:
            item.error_message = error
        if identity_is_primary is not None:
            item.identity_is_primary = identity_is_primary
        if current_snapshot is not None:
            item.current_snapshot = current_snapshot
        if status == "COMPLETED":
            item.completed_at = datetime.now(timezone.utc)
        await db.commit()


async def _write_enriched_json(converted_schema_id: str, payload: dict) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConvertedSchema).where(ConvertedSchema.id == converted_schema_id)
        )
        schema = result.scalar_one()
        schema.enriched_json = json.dumps(payload)
        await db.commit()


async def run_schema(
    item_id: str,
    login_id: str,
    schema_name: str,
    converted_schema_id: str,
    org_id: str,
    job_sem: asyncio.Semaphore,
    resume_from_step: int = 0,
    resume_data: dict | None = None,
) -> None:
    async with _GLOBAL_SEM:
        async with job_sem:
            ctx = {
                "login_id": login_id,
                "schema_name": schema_name,
                "converted_schema_id": converted_schema_id,
                "org_id": org_id,
            }
            data: dict = resume_data or {}

            for step in PIPELINE_STEPS:
                if step.order <= resume_from_step:
                    continue

                await _update_item(item_id, "RUNNING", step.name, step.order)
                try:
                    handler = await _load_handler(step.handler)
                    data = await handler(ctx, data)
                    await _update_item(
                        item_id, "RUNNING", step.name, step.order,
                        current_snapshot=json.dumps(data),
                    )

                    if step.name == "RESOLVE_IDENTITY":
                        identity = data.get("identityDecision", {})
                        await _update_item(
                            item_id, "RUNNING", step.name, step.order,
                            identity_is_primary=identity.get("isPrimary"),
                        )

                except Exception as exc:
                    log.exception("Schema %s failed at %s: %s", schema_name, step.name, exc)
                    error_msg = str(exc) or f"{type(exc).__name__} (no message)"
                    await _update_item(
                        item_id, "FAILED", step.name, step.order, error=error_msg
                    )
                    return

            ajo_payload = data.get("ajoPayload", data)
            await _write_enriched_json(converted_schema_id, ajo_payload)
            await _update_item(item_id, "COMPLETED", "COMPLETED", len(PIPELINE_STEPS))
            log.info("Schema %s migrated successfully", schema_name)


async def run_migration_job(
    job_id: str,
    login_id: str,
    schema_items: list[dict],
    org_id: str,
) -> None:
    job_sem = asyncio.Semaphore(3)
    tasks = [
        asyncio.create_task(
            run_schema(
                item_id=item["id"],
                login_id=login_id,
                schema_name=item["schema_name"],
                converted_schema_id=item["converted_schema_id"],
                org_id=org_id,
                job_sem=job_sem,
                resume_from_step=item.get("resume_from_step", 0),
                resume_data=item.get("resume_data"),
            )
        )
        for item in schema_items
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
