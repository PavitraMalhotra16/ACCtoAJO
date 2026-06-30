import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch
import io


@pytest.fixture
def mock_dest():
    dest = MagicMock()
    dest.org_id = "TESTORG@AdobeOrg"
    dest.tenant_id = "_testorg"
    dest.sandbox_name = "prod"
    dest.token_expires_at = None
    dest.encrypted_credentials = None
    dest.encrypted_access_token = None
    dest.authenticated = True
    dest.last_authenticated_at = None
    return dest


@pytest.fixture
def mock_schema_item():
    item = MagicMock()
    item.schema_name = "hdbk:orderHistory"
    item.aep_dataset_id = "ds-abc123"
    item.status = "COMPLETED"
    return item


@pytest.mark.asyncio
async def test_list_schemas_returns_migrated(mock_dest, mock_schema_item):
    from main import app
    from db import get_db

    async def mock_get_db():
        db = AsyncMock()
        # First call: DestinationConnection; second call: schema list
        dest_result = MagicMock()
        dest_result.scalar_one_or_none.return_value = mock_dest
        schema_result = MagicMock()
        schema_result.all.return_value = [mock_schema_item]
        db.execute = AsyncMock(side_effect=[dest_result, schema_result])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = mock_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"acc_session": "test-session"},
    ) as ac:
        resp = await ac.get("/api/datasets/schemas")

    app.dependency_overrides = {}
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["schema_name"] == "hdbk:orderHistory"
    assert data[0]["aep_dataset_id"] == "ds-abc123"


@pytest.mark.asyncio
async def test_ingest_success(mock_dest, mock_schema_item):
    from main import app
    from db import get_db

    async def mock_get_db():
        db = AsyncMock()
        dest_result = MagicMock()
        dest_result.scalar_one_or_none.return_value = mock_dest
        schema_result = MagicMock()
        schema_result.scalar_one_or_none.return_value = mock_schema_item
        db.execute = AsyncMock(side_effect=[dest_result, schema_result])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = mock_get_db

    with (
        patch("routes.datasets.get_valid_access_token", new=AsyncMock(return_value="tok123")),
        patch("routes.datasets.batch_client.create_batch", new=AsyncMock(return_value={"id": "batch-xyz"})),
        patch("routes.datasets.batch_client.upload_file", new=AsyncMock()),
        patch("routes.datasets.batch_client.complete_batch", new=AsyncMock(return_value={"id": "batch-xyz"})),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            cookies={"acc_session": "test-session"},
        ) as ac:
            resp = await ac.post(
                "/api/datasets/ingest",
                files={"file": ("data.json", io.BytesIO(b'{"a":1}'), "application/json")},
                data={"schema_name": "hdbk:orderHistory"},
            )

    app.dependency_overrides = {}
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SUCCESS"
    assert body["batch_id"] == "batch-xyz"
    assert len(body["steps"]) == 3
    assert all(s["status"] == "COMPLETED" for s in body["steps"])


@pytest.mark.asyncio
async def test_ingest_unsupported_format(mock_dest, mock_schema_item):
    from main import app
    from db import get_db

    async def mock_get_db():
        db = AsyncMock()
        dest_result = MagicMock()
        dest_result.scalar_one_or_none.return_value = mock_dest
        schema_result = MagicMock()
        schema_result.scalar_one_or_none.return_value = mock_schema_item
        db.execute = AsyncMock(side_effect=[dest_result, schema_result])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = mock_get_db

    with patch("routes.datasets.get_valid_access_token", new=AsyncMock(return_value="tok123")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            cookies={"acc_session": "test-session"},
        ) as ac:
            resp = await ac.post(
                "/api/datasets/ingest",
                files={"file": ("data.xlsx", io.BytesIO(b"binary"), "application/octet-stream")},
                data={"schema_name": "hdbk:orderHistory"},
            )

    app.dependency_overrides = {}
    assert resp.status_code == 400
    assert "unsupported" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ingest_schema_not_found(mock_dest):
    from main import app
    from db import get_db

    async def mock_get_db():
        db = AsyncMock()
        dest_result = MagicMock()
        dest_result.scalar_one_or_none.return_value = mock_dest
        schema_result = MagicMock()
        schema_result.scalar_one_or_none.return_value = None  # schema not in DB
        db.execute = AsyncMock(side_effect=[dest_result, schema_result])
        db.commit = AsyncMock()
        yield db

    app.dependency_overrides[get_db] = mock_get_db

    with patch("routes.datasets.get_valid_access_token", new=AsyncMock(return_value="tok123")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            cookies={"acc_session": "test-session"},
        ) as ac:
            resp = await ac.post(
                "/api/datasets/ingest",
                files={"file": ("data.json", io.BytesIO(b"{}"), "application/json")},
                data={"schema_name": "hdbk:unknown"},
            )

    app.dependency_overrides = {}
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ingest_no_ajo_connection():
    from main import app
    from db import get_db

    async def mock_get_db():
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result)
        yield db

    app.dependency_overrides[get_db] = mock_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
        cookies={"acc_session": "test-session"},
    ) as ac:
        resp = await ac.post(
            "/api/datasets/ingest",
            files={"file": ("data.json", io.BytesIO(b"{}"), "application/json")},
            data={"schema_name": "hdbk:orderHistory"},
        )

    app.dependency_overrides = {}
    assert resp.status_code == 401
