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

_PHASE1_STEPS = [s for s in PIPELINE_STEPS if s.phase == 1]
_PHASE2_STEPS = [s for s in PIPELINE_STEPS if s.phase == 2]
_TOTAL_STEPS = len(PIPELINE_STEPS)


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


async def _run_steps(
    item_id: str,
    ctx: dict,
    steps: list,
    data: dict,
    resume_from_step: int,
) -> tuple[bool, dict]:
    """Run a contiguous set of pipeline steps. Returns (ok, data); on failure the
    item is marked FAILED and ok=False."""
    # Steps that are skipped when the schema already exists in AEP
    _SKIP_IF_EXISTS = {"CREATE_SCHEMA", "PRIMARY_KEY_DESCRIPTOR", "VERSION_DESCRIPTOR",
                       "TIMESTAMP_DESCRIPTOR", "IDENTITY_DESCRIPTOR"}

    for step in steps:
        if step.order <= resume_from_step:
            continue

        if data.get("skipToVerify") and step.name in _SKIP_IF_EXISTS:
            log.info("Schema %s — %s skipped (schema already in AEP)", ctx.get("schema_name"), step.name)
            continue

        await _update_item(item_id, "RUNNING", step.name, step.order)
        try:
            handler = await _load_handler(step.handler)
            data = await handler(ctx, data)
        except Exception as exc:
            log.exception("Schema %s failed at %s: %s", ctx.get("schema_name"), step.name, exc)
            error_msg = str(exc) or f"{type(exc).__name__} (no message)"
            await _update_item(item_id, "FAILED", step.name, step.order, error=error_msg)
            return False, data

        await _update_item(
            item_id, "RUNNING", step.name, step.order,
            current_snapshot=json.dumps(data, default=str),
        )

        if step.name == "RESOLVE_IDENTITY":
            identity = data.get("identityDecision", {})
            await _update_item(
                item_id, "RUNNING", step.name, step.order,
                identity_is_primary=identity.get("isPrimary"),
            )

        # Persist the enriched JSON as soon as it's built, so it's the durable
        # push input for the steps that follow (and survives a failed push).
        if step.name == "BUILD_PAYLOAD":
            await _write_enriched_json(ctx["converted_schema_id"], data.get("ajoPayload", data))

    return True, data


async def run_schema(
    item_id: str,
    login_id: str,
    schema_name: str,
    converted_schema_id: str,
    org_id: str,
    job_sem: asyncio.Semaphore,
    resume_from_step: int = 0,
    resume_data: dict | None = None,
) -> tuple[bool, dict, dict]:
    """PASS 1 — build the enriched JSON, create the schema and its descriptors.
    Returns (ok, ctx, data); the schema is NOT marked COMPLETED until PASS 2."""
    async with _GLOBAL_SEM:
        async with job_sem:
            ctx = {
                "login_id": login_id,
                "schema_name": schema_name,
                "converted_schema_id": converted_schema_id,
                "org_id": org_id,
            }
            data: dict = resume_data or {}
            ok, data = await _run_steps(item_id, ctx, _PHASE1_STEPS, data, resume_from_step)
            return ok, ctx, data


async def run_schema_phase2(
    item_id: str,
    ctx: dict,
    data: dict,
    resume_from_step: int = 0,
) -> None:
    """PASS 2 — wire relationships, verify, then mark the schema's final state."""
    if data.get("skipToVerify"):
        # Schema already existed and all steps were skipped — mark immediately.
        await _update_item(item_id, "COMPLETED", "ALREADY_EXISTS", _TOTAL_STEPS)
        log.info("Schema %s push complete (ALREADY_EXISTS — fast path)", ctx.get("schema_name"))
        return

    ok, data = await _run_steps(item_id, ctx, _PHASE2_STEPS, data, resume_from_step)
    if not ok:
        return

    any_changes = data.get("changesMade", 0) + data.get("relationshipsCreated", 0)
    final_step = "ALREADY_EXISTS" if (data.get("schemaExisted") and any_changes == 0) else "COMPLETED"
    await _update_item(item_id, "COMPLETED", final_step, _TOTAL_STEPS)
    log.info("Schema %s push complete (%s)", ctx.get("schema_name"), final_step)


async def run_migration_job(
    job_id: str,
    login_id: str,
    schema_items: list[dict],
    org_id: str,
) -> None:
    job_sem = asyncio.Semaphore(3)

    # PASS 1 — per-schema, concurrent: create schemas + their own descriptors.
    pass1_tasks = [
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
    pass1_results = await asyncio.gather(*pass1_tasks, return_exceptions=True)

    # PASS 2 — relationships + verify. Run sequentially so concurrent schemas
    # don't race to create the same relationship descriptor.
    for item, result in zip(schema_items, pass1_results):
        if isinstance(result, BaseException):
            log.error("Schema %s crashed in PASS 1: %s", item["schema_name"], result)
            continue
        ok, ctx, data = result
        if not ok:
            continue
        await run_schema_phase2(item["id"], ctx, data, item.get("resume_from_step", 0))
