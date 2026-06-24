import asyncio
import importlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db import AsyncSessionLocal, TemplateMigrationRun, TemplateJobItem
from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS

log = logging.getLogger("acc_backend.pipeline.template_runner")

_ACTIVE_STEPS = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
_GLOBAL_SEM = asyncio.Semaphore(10)


async def _load_handler(dotted_path: str):
    module_path, fn_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


async def _update_item(item_id: str, status: str, step_name: str, step_order: int,
                       error_step: str | None = None, error_message: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TemplateJobItem).where(TemplateJobItem.id == item_id))
        item = result.scalar_one()
        item.status = status
        item.current_step = step_name
        item.current_step_order = step_order
        item.updated_at = datetime.now(timezone.utc)
        if error_step is not None:
            item.error_step = error_step
        if error_message is not None:
            item.error_message = error_message
        await db.commit()


async def run_template(
    item_id: str,
    source_id: str,
    login_id: str,
    destination_conn_id: str,
    placeholder_map: dict,
    channel: str,
    db,
) -> bool:
    """Run all active pipeline steps for one template. Returns True on success."""
    ctx = {
        "item_id": item_id,
        "source_id": source_id,
        "login_id": login_id,
        "destination_conn_id": destination_conn_id,
        "placeholder_map": placeholder_map,
    }
    data: dict = {"channel": channel}

    for step in _ACTIVE_STEPS:
        await _update_item(item_id, "RUNNING", step.name, step.order)
        try:
            handler = await _load_handler(step.handler)
            data = await handler(ctx, data, db)
        except Exception as exc:
            log.exception("Template %s failed at %s: %s", source_id, step.name, exc)
            await _update_item(
                item_id, "FAILED", step.name, step.order,
                error_step=step.name,
                error_message=str(exc) or type(exc).__name__,
            )
            return False

    await _update_item(item_id, "COMPLETED", "BUILD_ENRICHED", len(_ACTIVE_STEPS))
    return True


async def _run_one(item: dict, placeholder_map: dict, sem: asyncio.Semaphore) -> None:
    async with _GLOBAL_SEM:
        async with sem:
            async with AsyncSessionLocal() as db:
                await run_template(
                    item_id=item["id"],
                    source_id=item["source_id"],
                    login_id=item["login_id"],
                    destination_conn_id=item["destination_conn_id"],
                    placeholder_map=placeholder_map,
                    channel=item["channel"],
                    db=db,
                )


async def run_template_migration(run_id: str, items: list[dict], placeholder_map: dict) -> None:
    """Orchestrate concurrent template migration for all items in a run."""
    sem = asyncio.Semaphore(5)
    tasks = [asyncio.create_task(_run_one(item, placeholder_map, sem)) for item in items]
    await asyncio.gather(*tasks, return_exceptions=True)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id)
        )
        run = result.scalar_one()
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    log.info("Template migration run %s complete", run_id)
