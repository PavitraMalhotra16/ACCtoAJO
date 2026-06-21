import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession


def make_mock_db():
    """Return an async mock that satisfies FastAPI's Depends(get_db) override."""
    db = AsyncMock(spec=AsyncSession)
    # scalar_one_or_none / scalars().all() / fetchall() return empty by default
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalars.return_value.all.return_value = []
    result_mock.fetchall.return_value = []
    db.execute = AsyncMock(return_value=result_mock)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def app():
    from main import app
    return app


@pytest.mark.asyncio
async def test_migrate_start_requires_auth(app):
    from db import get_db

    async def override_get_db():
        yield make_mock_db()

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/migrate/start")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_migrate_status_not_found(app):
    from db import get_db

    db = make_mock_db()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("routes.migrate.get_login_from_cookie", new=AsyncMock(return_value="user1")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/migrate/status/nonexistent-job-id")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_migrate_start_fresh_path_returns_started(app):
    """extract_job_id path (explicit re-migrate) must not 500 — regression for an
    undefined done_names in the fresh branch."""
    from db import get_db

    dest = MagicMock()
    dest.org_id = "O@AdobeOrg"
    conv = MagicMock()
    conv.schema_name = "cus:x"
    conv.id = "cid"

    dest_result = MagicMock()
    dest_result.scalar_one_or_none.return_value = dest
    conv_result = MagicMock()
    conv_result.scalars.return_value.all.return_value = [conv]

    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=[dest_result, conv_result])
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("routes.migrate.get_login_from_cookie", new=AsyncMock(return_value="user1")), \
             patch("routes.migrate.run_migration_job", new=AsyncMock()):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/api/migrate/start", json={"extract_job_id": "job-123"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["message"] == "started"
        assert body["queued"] == 1
        assert body["skipped"] == 0
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_migrate_schema_item_not_found(app):
    from db import get_db

    db = make_mock_db()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("routes.migrate.get_login_from_cookie", new=AsyncMock(return_value="user1")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/migrate/schema/nonexistent-item-id")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
