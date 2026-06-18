import asyncio
import contextlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# Steps 4 + 6–12 talk to AEP. The runner tests only exercise orchestration /
# resume logic, so stub these to pass-throughs (their behaviour is covered in
# test_handlers.py). FETCH_TENANT_ID injects a tenant id the later steps expect.
_PUSH_HANDLERS = [
    "call_schema_api",
    "call_fieldgroup_api",
    "attach_fieldgroup",
    "ensure_namespace",
    "call_identity_descriptor",
    "enable_profile_union",
    "verify",
]


@contextlib.contextmanager
def _patch_push_handlers():
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch(
            "pipeline.handlers.fetch_tenant_id",
            new=AsyncMock(side_effect=lambda ctx, data: {**data, "tenantId": "_test"}),
        ))
        for name in _PUSH_HANDLERS:
            stack.enter_context(patch(
                f"pipeline.handlers.{name}",
                new=AsyncMock(side_effect=lambda ctx, data: data),
            ))
        yield


@pytest.mark.asyncio
async def test_run_schema_success():
    completed_statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None,
                          identity_is_primary=None, current_snapshot=None):
        completed_statuses.append((status, step_name))

    async def fake_write_enriched(converted_schema_id, payload):
        pass

    with patch("pipeline.runner._update_item", side_effect=fake_update), \
         patch("pipeline.runner._write_enriched_json", side_effect=fake_write_enriched), \
         patch("pipeline.handlers.AsyncSessionLocal") as mock_session_cls:

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        raw_data = {
            "source": {"fullName": "cus:test", "name": "test"},
            "schema": {"label": "Test", "description": ""},
            "rootElement": {"name": "test"},
            "attributes": [{"name": "id", "type": "int32"}],
            "keys": {"autoPk": {"enabled": True, "field": "id"}, "primaryKeys": [], "uniqueKeys": []},
            "linksAndJoins": [],
        }
        mock_schema = MagicMock()
        mock_schema.raw_json = json.dumps(raw_data)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_schema
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cls.return_value = mock_session

        from pipeline.runner import run_schema
        job_sem = asyncio.Semaphore(3)

        with _patch_push_handlers():
            await run_schema(
                item_id="item-1",
                login_id="user1",
                schema_name="cus:test",
                converted_schema_id="schema-id-1",
                org_id="ORG@AdobeOrg",
                job_sem=job_sem,
            )

    assert any(s == "COMPLETED" for s, _ in completed_statuses)


@pytest.mark.asyncio
async def test_run_schema_failure_at_step():
    statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None,
                          identity_is_primary=None, current_snapshot=None):
        statuses.append((status, step_name, error))

    async def bad_map_types(ctx, data):
        raise ValueError("type mapping exploded")

    with patch("pipeline.runner._update_item", side_effect=fake_update), \
         patch("pipeline.handlers.map_types", side_effect=bad_map_types), \
         patch("pipeline.handlers.AsyncSessionLocal") as mock_session_cls:

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        raw_data = {"source": {"fullName": "cus:test"}, "attributes": []}
        mock_schema = MagicMock()
        mock_schema.raw_json = json.dumps(raw_data)
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = mock_schema
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cls.return_value = mock_session

        from pipeline.runner import run_schema
        job_sem = asyncio.Semaphore(3)
        await run_schema(
            item_id="item-2",
            login_id="user1",
            schema_name="cus:test",
            converted_schema_id="schema-id-2",
            org_id="ORG@AdobeOrg",
            job_sem=job_sem,
        )

    failed = [(s, n, e) for s, n, e in statuses if s == "FAILED"]
    assert len(failed) == 1
    assert failed[0][1] == "MAP_TYPES"
    assert "type mapping exploded" in failed[0][2]


@pytest.mark.asyncio
async def test_run_schema_resumes_from_snapshot():
    completed_statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None,
                          identity_is_primary=None, current_snapshot=None):
        completed_statuses.append((status, step_name))

    async def fake_write_enriched(converted_schema_id, payload):
        pass

    resume_data = {
        "source": {"fullName": "cus:test", "name": "test"},
        "schema": {"label": "Test", "description": ""},
        "rootElement": {"name": "test"},
        "attributes": [{"name": "id", "type": "int32"}],
        "keys": {"autoPk": {"enabled": True, "field": "id"}, "primaryKeys": [], "uniqueKeys": []},
        "linksAndJoins": [],
        "xdmTypes": {"id": {"type": "integer"}},
        "identityDecision": {"fieldPath": "/id", "isPrimary": False, "status": "resolved"},
    }

    with patch("pipeline.runner._update_item", side_effect=fake_update), \
         patch("pipeline.runner._write_enriched_json", side_effect=fake_write_enriched), \
         patch("pipeline.handlers.AsyncSessionLocal") as mock_session_cls:

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cls.return_value = mock_session

        from pipeline.runner import run_schema
        job_sem = asyncio.Semaphore(3)

        with _patch_push_handlers():
            await run_schema(
                item_id="item-3",
                login_id="user1",
                schema_name="cus:test",
                converted_schema_id="schema-id-3",
                org_id="ORG@AdobeOrg",
                job_sem=job_sem,
                resume_from_step=3,
                resume_data=resume_data,
            )

    # LOAD_JSON (step 1), MAP_TYPES (step 2), RESOLVE_IDENTITY (step 3) must be skipped
    step_names_run = [name for _, name in completed_statuses]
    assert "LOAD_JSON" not in step_names_run
    assert "MAP_TYPES" not in step_names_run
    assert "RESOLVE_IDENTITY" not in step_names_run
    assert any(s == "COMPLETED" for s, _ in completed_statuses)
