import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def schema_file(tmp_path):
    data = {
        "source": {"fullName": "cus:test"},
        "attributes": [{"name": "id", "type": "int32"}],
        "keys": {"autoPk": {"enabled": True, "field": "id"}, "primaryKeys": [], "uniqueKeys": []},
    }
    p = tmp_path / "cus_test.json"
    p.write_text(json.dumps(data))
    return p


@pytest.mark.asyncio
async def test_run_schema_success(tmp_path, schema_file, monkeypatch):
    monkeypatch.setenv("SCHEMA_STORAGE_DIR", str(tmp_path))

    import importlib
    import pipeline.file_manager as fm
    importlib.reload(fm)

    completed_statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None,
                          identity_is_primary=None, final_file_path=None):
        completed_statuses.append((status, step_name))

    with patch("pipeline.runner._update_item", side_effect=fake_update), \
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

        with patch("pipeline.handlers.fetch_tenant_id", new=AsyncMock(
            side_effect=lambda ctx, data: {**data, "tenantId": "_test"}
        )):
            await run_schema(
                item_id="item-1",
                login_id="user1",
                schema_name="cus:test",
                schema_storage_path=str(schema_file),
                org_id="ORG@AdobeOrg",
                job_sem=job_sem,
            )

    final = list(filter(lambda x: x[0] == "COMPLETED", completed_statuses))
    assert len(final) == 1


@pytest.mark.asyncio
async def test_run_schema_failure_at_step(tmp_path, schema_file, monkeypatch):
    monkeypatch.setenv("SCHEMA_STORAGE_DIR", str(tmp_path))
    import importlib
    import pipeline.file_manager as fm
    importlib.reload(fm)

    statuses = []

    async def fake_update(item_id, status, step_name, step_order, error=None,
                          identity_is_primary=None, final_file_path=None):
        statuses.append((status, step_name, error))

    async def bad_map_types(ctx, data):
        raise ValueError("type mapping exploded")

    with patch("pipeline.runner._update_item", side_effect=fake_update), \
         patch("pipeline.handlers.map_types", side_effect=bad_map_types):
        from pipeline.runner import run_schema
        job_sem = asyncio.Semaphore(3)
        await run_schema(
            item_id="item-2",
            login_id="user1",
            schema_name="cus:test",
            schema_storage_path=str(schema_file),
            org_id="ORG@AdobeOrg",
            job_sem=job_sem,
        )

    failed = [(s, n, e) for s, n, e in statuses if s == "FAILED"]
    assert len(failed) == 1
    assert failed[0][1] == "MAP_TYPES"
    assert "type mapping exploded" in failed[0][2]
