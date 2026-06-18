import asyncio
import importlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db import AsyncSessionLocal, SchemaJobItem
from pipeline_steps import PIPELINE_STEPS
from pipeline.file_manager import write_tmp, finalize, cleanup_tmp

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
    final_file_path: str | None = None,
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
        if final_file_path is not None:
            item.final_file_path = final_file_path
        if status == "COMPLETED":
            item.completed_at = datetime.now(timezone.utc)
        await db.commit()


async def run_schema(
    item_id: str,
    login_id: str,
    schema_name: str,
    schema_storage_path: str,
    org_id: str,
    job_sem: asyncio.Semaphore,
) -> None:
    async with _GLOBAL_SEM:
        async with job_sem:
            ctx = {
                "login_id": login_id,
                "schema_name": schema_name,
                "schema_storage_path": schema_storage_path,
                "org_id": org_id,
            }
            data: dict = {}

            for step in PIPELINE_STEPS:
                await _update_item(item_id, "RUNNING", step.name, step.order)
                try:
                    handler = await _load_handler(step.handler)
                    data = await handler(ctx, data)
                    write_tmp(login_id, schema_name, data)

                    if step.name == "RESOLVE_IDENTITY":
                        identity = data.get("identityDecision", {})
                        await _update_item(
                            item_id, "RUNNING", step.name, step.order,
                            identity_is_primary=identity.get("isPrimary"),
                        )

                except Exception as exc:
                    log.error("Schema %s failed at %s: %s", schema_name, step.name, exc)
                    await _update_item(
                        item_id, "FAILED", step.name, step.order, error=str(exc)
                    )
                    return

            final_path = finalize(login_id, schema_name)
            await _update_item(
                item_id, "COMPLETED", "COMPLETED", len(PIPELINE_STEPS),
                final_file_path=str(final_path),
            )
            cleanup_tmp(login_id)
            log.info("Schema %s migrated successfully → %s", schema_name, final_path)


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
                schema_storage_path=item["storage_path"],
                org_id=org_id,
                job_sem=job_sem,
            )
        )
        for item in schema_items
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
