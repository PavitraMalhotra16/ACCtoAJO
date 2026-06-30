import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_create_batch_success():
    from pipeline.batch_client import create_batch
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"id": "batch-abc", "status": "active"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await create_batch(mock_client, {"Authorization": "Bearer tok"}, "ds-123", "json")
    assert result["id"] == "batch-abc"
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_create_batch_raises_on_error():
    from pipeline.batch_client import create_batch
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "bad request"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Create batch failed"):
        await create_batch(mock_client, {}, "ds-123", "json")


@pytest.mark.asyncio
async def test_upload_file_success():
    from pipeline.batch_client import upload_file
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.put.return_value = mock_resp

    await upload_file(mock_client, {}, "batch-abc", "ds-123", "data.json", b'{"a":1}')
    mock_client.put.assert_called_once()


@pytest.mark.asyncio
async def test_upload_file_raises_on_error():
    from pipeline.batch_client import upload_file
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "batch not found"

    mock_client = AsyncMock()
    mock_client.put.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Upload file failed"):
        await upload_file(mock_client, {}, "batch-abc", "ds-123", "data.json", b"bytes")


@pytest.mark.asyncio
async def test_complete_batch_success():
    from pipeline.batch_client import complete_batch
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "batch-abc", "status": "staging"}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    result = await complete_batch(mock_client, {}, "batch-abc")
    assert result["id"] == "batch-abc"


@pytest.mark.asyncio
async def test_complete_batch_raises_on_error():
    from pipeline.batch_client import complete_batch
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "internal error"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Complete batch failed"):
        await complete_batch(mock_client, {}, "batch-abc")
