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

    async def override_get_db():
        yield make_mock_db()

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/migrate/status/nonexistent-job-id")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_migrate_schema_item_not_found(app):
    from db import get_db

    async def override_get_db():
        yield make_mock_db()

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/migrate/schema/nonexistent-item-id")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
