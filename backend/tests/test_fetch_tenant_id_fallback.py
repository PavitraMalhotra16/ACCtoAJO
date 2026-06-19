import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.exc import ProgrammingError


@pytest.mark.asyncio
async def test_fetch_tenant_id_retries_after_column_missing():
    """On ProgrammingError with 'column', ensure_schema_columns is called and step retries."""
    import pipeline.handlers as handlers_module

    ctx = {"org_id": "TESTORG@AdobeOrg"}
    data = {}
    call_count = 0

    async def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            orig = MagicMock()
            orig.args = ["column tenant_id does not exist"]
            raise ProgrammingError("column tenant_id does not exist", orig, orig)
        mock_result = MagicMock()
        mock_dest = MagicMock()
        mock_dest.tenant_id = "_testorg"
        mock_result.scalar_one_or_none.return_value = mock_dest
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch.object(handlers_module, "AsyncSessionLocal", return_value=mock_session), \
         patch.object(handlers_module, "ensure_schema_columns", new_callable=AsyncMock) as mock_ensure:

        result = await handlers_module.fetch_tenant_id(ctx, data)

    mock_ensure.assert_called_once()
    assert result["tenantId"] == "_testorg"
