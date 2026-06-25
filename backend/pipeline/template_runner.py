import asyncio
import importlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db import AsyncSessionLocal, TemplateMigrationRun, TemplateJobItem
from pipeline.template_handlers import (
    FatalRunError,
    TemplateFailed,
    TemplateManual,
    TemplateSkipped,
    VerificationFailed,
)
from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS

log = logging.getLogger("acc_backend.pipeline.template_runner")

_ACTIVE_STEPS = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
_GLOBAL_SEM = asyncio.Semaphore(10)

# TEMPLATES.md §9: push in groups of 20–25, then pause to stay within AJO rate limits.
BATCH_SIZE = 25
BATCH_PAUSE_SECONDS = 2

# Typed exception → terminal status. Anything else falls through to FAILED.
_STATUS_BY_EXC: dict[type, str] = {
    TemplateSkipped: "SKIPPED",
    TemplateFailed: "FAILED",
    TemplateManual: "MANUAL",
    VerificationFailed: "VERIFICATION_FAILED",
    FatalRunError: "HALTED",
}


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
    resume_from_step: int = 0,
    abort_event: asyncio.Event | None = None,
) -> bool:
    """Run all active pipeline steps for one template. Returns True on success.

    resume_from_step: steps with order <= this value are skipped (already done).
    abort_event: set on a config-level failure (403/406) so the orchestrator stops the run.
    """
    ctx = {
        "item_id": item_id,
        "source_id": source_id,
        "login_id": login_id,
        "destination_conn_id": destination_conn_id,
        "placeholder_map": placeholder_map,
    }
    data: dict = {"channel": channel}

    for step in _ACTIVE_STEPS:
        if step.order <= resume_from_step:
            log.info("Template %s — skipping step %s (already completed)", source_id, step.name)
            continue
        try:
            await _update_item(item_id, "RUNNING", step.name, step.order)
            handler = await _load_handler(step.handler)
            data = await handler(ctx, data, db)
        except Exception as exc:
            status = _STATUS_BY_EXC.get(type(exc), "FAILED")
            log.exception("Template %s -> %s at step %s: %s", source_id, status, step.name, exc)
            try:
                await _update_item(
                    item_id, status, step.name, step.order,
                    error_step=f"{step.order} ({step.name})",
                    error_message=str(exc) or type(exc).__name__,
                )
            except Exception:
                log.exception("Could not mark item %s %s after step %s error", item_id, status, step.name)
            # 403/406 are config-level — signal the whole run to stop.
            if isinstance(exc, FatalRunError) and abort_event is not None:
                abort_event.set()
            return False

    # COMPLETED records the actual last step (VERIFY), not a hardcoded label.
    await _update_item(item_id, "COMPLETED", _ACTIVE_STEPS[-1].name, len(_ACTIVE_STEPS))
    return True


async def _mark_halted(items: list[dict]) -> None:
    """Mark not-yet-terminal items HALTED when the run is aborted mid-flight."""
    if not items:
        return
    async with AsyncSessionLocal() as db:
        for item in items:
            row = (
                await db.execute(select(TemplateJobItem).where(TemplateJobItem.id == item["id"]))
            ).scalar_one_or_none()
            if row and row.status in ("PENDING", "RUNNING"):
                row.status = "HALTED"
                row.error_step = row.error_step or "—"
                row.error_message = (
                    "Run halted by a config-level error (403/406) on another template"
                )
        await db.commit()


async def _run_one(item: dict, placeholder_map: dict, sem: asyncio.Semaphore,
                   abort_event: asyncio.Event) -> None:
    if abort_event.is_set():
        await _mark_halted([item])
        return
    async with _GLOBAL_SEM:
        async with sem:
            try:
                async with AsyncSessionLocal() as db:
                    await run_template(
                        item_id=item["id"],
                        source_id=item["source_id"],
                        login_id=item["login_id"],
                        destination_conn_id=item["destination_conn_id"],
                        placeholder_map=placeholder_map,
                        channel=item["channel"],
                        db=db,
                        resume_from_step=item.get("resume_from_step", 0),
                        abort_event=abort_event,
                    )
            except Exception:
                log.exception("Unhandled error running template item_id=%s source_id=%s",
                              item.get("id"), item.get("source_id"))
                # Ensure item is marked FAILED so it shows in the UI
                try:
                    await _update_item(
                        item["id"], "FAILED", "UNKNOWN", 0,
                        error_step="UNKNOWN",
                        error_message="Unexpected runner error — check backend logs",
                    )
                except Exception:
                    log.exception("Failed to mark item %s as FAILED", item.get("id"))


async def run_template_migration(run_id: str, items: list[dict], placeholder_map: dict) -> None:
    """Orchestrate template migration in batches (§9): push BATCH_SIZE concurrently, pause,
    repeat. A 403/406 on any template aborts the run — remaining items are marked HALTED."""
    sem = asyncio.Semaphore(5)
    abort_event = asyncio.Event()

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        if abort_event.is_set():
            await _mark_halted(items[start:])
            break

        tasks = [asyncio.create_task(_run_one(it, placeholder_map, sem, abort_event)) for it in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                log.error("Task %d for run %s raised: %s", start + i, run_id, r)

        # Throttle between groups, unless aborting or this was the last group.
        if not abort_event.is_set() and start + BATCH_SIZE < len(items):
            await asyncio.sleep(BATCH_PAUSE_SECONDS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id)
        )
        run = result.scalar_one()
        run.status = "HALTED" if abort_event.is_set() else "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    log.info("Template migration run %s finished (%s)", run_id, run.status)
