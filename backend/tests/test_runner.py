import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from pipeline_steps import PipelineStep


# ── _run_steps ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_steps_success_and_snapshot():
    from pipeline import runner
    updates = []

    async def fake_update(item_id, status, step_name, step_order, **kw):
        updates.append((status, step_name, kw.get("current_snapshot") is not None))

    async def fake_load(path):
        async def handler(ctx, data):
            data["ran"] = data.get("ran", 0) + 1
            return data
        return handler

    steps = [PipelineStep("A", "A", "h.a", 1), PipelineStep("B", "B", "h.b", 2)]
    with patch.object(runner, "_update_item", side_effect=fake_update), \
         patch.object(runner, "_load_handler", side_effect=fake_load):
        ok, data = await runner._run_steps("item", {"schema_name": "s"}, steps, {}, 0)

    assert ok is True
    assert data["ran"] == 2
    assert ("RUNNING", "A", False) in updates  # step start
    assert ("RUNNING", "A", True) in updates   # post-step snapshot


@pytest.mark.asyncio
async def test_run_steps_failure_marks_failed():
    from pipeline import runner
    statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None, **kw):
        statuses.append((status, step_name, error))

    async def fake_load(path):
        async def boom(ctx, data):
            raise ValueError("kaboom")
        return boom

    steps = [PipelineStep("X", "X", "h.x", 1)]
    with patch.object(runner, "_update_item", side_effect=fake_update), \
         patch.object(runner, "_load_handler", side_effect=fake_load):
        ok, data = await runner._run_steps("item", {"schema_name": "s"}, steps, {}, 0)

    assert ok is False
    failed = [s for s in statuses if s[0] == "FAILED"]
    assert failed and failed[0][1] == "X" and "kaboom" in failed[0][2]


@pytest.mark.asyncio
async def test_run_steps_resume_skips_completed():
    from pipeline import runner

    async def fake_load(path):
        async def handler(ctx, data):
            data.setdefault("ran", []).append(path)
            return data
        return handler

    steps = [
        PipelineStep("A", "A", "h.a", 1),
        PipelineStep("B", "B", "h.b", 2),
        PipelineStep("C", "C", "h.c", 3),
    ]
    with patch.object(runner, "_update_item", new=AsyncMock()), \
         patch.object(runner, "_load_handler", side_effect=fake_load):
        ok, data = await runner._run_steps("item", {}, steps, {}, resume_from_step=2)

    assert ok is True
    assert data["ran"] == ["h.c"]  # steps with order <= 2 are skipped


@pytest.mark.asyncio
async def test_build_payload_triggers_enriched_write():
    from pipeline import runner
    writes = []

    async def fake_write(cid, payload):
        writes.append((cid, payload))

    async def fake_load(path):
        async def handler(ctx, data):
            data["ajoPayload"] = {"title": "t"}
            return data
        return handler

    steps = [PipelineStep("BUILD_PAYLOAD", "b", "h.bp", 5)]
    with patch.object(runner, "_update_item", new=AsyncMock()), \
         patch.object(runner, "_load_handler", side_effect=fake_load), \
         patch.object(runner, "_write_enriched_json", side_effect=fake_write):
        await runner._run_steps("item", {"converted_schema_id": "cid"}, steps, {}, 0)

    assert writes == [("cid", {"title": "t"})]


# ── run_schema (PASS 1) ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_schema_returns_ctx_and_data():
    from pipeline import runner

    async def fake_run_steps(item_id, ctx, steps, data, resume):
        return True, {"done": True}

    sem = asyncio.Semaphore(1)
    with patch.object(runner, "_run_steps", side_effect=fake_run_steps):
        ok, ctx, data = await runner.run_schema("i", "u", "cus:x", "cid", "O@AdobeOrg", sem)

    assert ok is True
    assert ctx["schema_name"] == "cus:x"
    assert ctx["converted_schema_id"] == "cid"
    assert data["done"] is True


# ── run_schema_phase2 (PASS 2 — final state) ─────────────────────────────────

async def _run_phase2(monkey_data, *, ok=True):
    from pipeline import runner
    captured = {}

    async def fake_update(item_id, status, step_name, step_order, **kw):
        captured["status"] = status
        captured["step"] = step_name

    async def fake_run_steps(item_id, ctx, steps, data, resume):
        return ok, monkey_data

    update_mock = AsyncMock(side_effect=fake_update)
    with patch.object(runner, "_update_item", new=update_mock), \
         patch.object(runner, "_run_steps", side_effect=fake_run_steps):
        await runner.run_schema_phase2("item", {"schema_name": "s"}, {})
    return captured, update_mock


@pytest.mark.asyncio
async def test_phase2_already_exists():
    captured, _ = await _run_phase2({"schemaExisted": True, "changesMade": 0, "relationshipsCreated": 0})
    assert captured["status"] == "COMPLETED"
    assert captured["step"] == "ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_phase2_pushed_when_relationship_added():
    captured, _ = await _run_phase2({"schemaExisted": True, "changesMade": 0, "relationshipsCreated": 1})
    assert captured["status"] == "COMPLETED"
    assert captured["step"] == "COMPLETED"


@pytest.mark.asyncio
async def test_phase2_new_schema_completed():
    captured, _ = await _run_phase2({"schemaExisted": False, "changesMade": 1, "relationshipsCreated": 0})
    assert captured["step"] == "COMPLETED"


@pytest.mark.asyncio
async def test_phase2_skips_when_pass2_failed():
    _, update_mock = await _run_phase2({}, ok=False)
    update_mock.assert_not_called()  # FAILED was already set inside _run_steps (mocked away)
