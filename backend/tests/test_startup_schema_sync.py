import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_lifespan_calls_ensure_schema_columns():
    """ensure_schema_columns must be called during app startup."""
    import main as main_module
    from fastapi import FastAPI

    app = FastAPI()

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    with patch.object(main_module, "init_db", new_callable=AsyncMock) as mock_init, \
         patch.object(main_module, "ensure_schema_columns", new_callable=AsyncMock) as mock_ensure, \
         patch.object(main_module, "AsyncSessionLocal", return_value=mock_session):

        async with main_module.lifespan(app):
            pass

        mock_ensure.assert_called_once()
