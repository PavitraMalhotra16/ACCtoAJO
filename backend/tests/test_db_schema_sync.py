import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_ensure_schema_columns_adds_missing_column():
    """ensure_schema_columns issues ALTER TABLE for a column in ORM but not in DB."""
    existing_cols = {"id", "org_id", "client_id"}  # tenant_id missing

    executed_stmts = []

    async def fake_execute(stmt, *args, **kwargs):
        sql = str(stmt)
        executed_stmts.append(sql)
        if "information_schema" in sql:
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(c,) for c in existing_cols]
            return mock_result
        return MagicMock()

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = fake_execute
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("db.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        with patch("db.Base") as mock_base:
            mock_table = MagicMock()
            mock_table.name = "destination_connections"
            col_id = MagicMock(); col_id.name = "id"; col_id.primary_key = True
            col_org = MagicMock(); col_org.name = "org_id"; col_org.primary_key = False
            col_tenant = MagicMock(); col_tenant.name = "tenant_id"; col_tenant.primary_key = False
            col_client = MagicMock(); col_client.name = "client_id"; col_client.primary_key = False
            mock_table.columns = [col_id, col_org, col_tenant, col_client]
            mock_class = MagicMock()
            mock_class.__table__ = mock_table
            mock_base.registry.mappers = [MagicMock(class_=mock_class)]

            from db import ensure_schema_columns
            await ensure_schema_columns()

    alter_stmts = [s for s in executed_stmts if "ALTER TABLE" in s.upper()]
    assert len(alter_stmts) >= 1
    assert any("tenant_id" in s for s in alter_stmts)
    assert not any("client_id" in s for s in alter_stmts)  # already exists
