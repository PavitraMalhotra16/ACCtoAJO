import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_ensure_schema_columns_adds_missing_column():
    """ensure_schema_columns issues ALTER TABLE only for columns in ORM but not in DB."""
    # Existing columns in the DB — client_id is there, tenant_id is not
    existing_cols = {"id", "org_id", "client_id"}
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
    mock_conn.dialect = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_conn.commit = AsyncMock()

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    # Build mock mappers that mimic destination_connections ORM table
    col_id = MagicMock(); col_id.name = "id"; col_id.primary_key = True
    col_org = MagicMock(); col_org.name = "org_id"; col_org.primary_key = False
    col_org.type.compile.return_value = "VARCHAR(255)"
    col_tenant = MagicMock(); col_tenant.name = "tenant_id"; col_tenant.primary_key = False
    col_tenant.type.compile.return_value = "VARCHAR(255)"
    col_client = MagicMock(); col_client.name = "client_id"; col_client.primary_key = False
    col_client.type.compile.return_value = "VARCHAR(255)"

    mock_table = MagicMock()
    mock_table.name = "destination_connections"
    mock_table.columns = [col_id, col_org, col_tenant, col_client]

    mock_class = MagicMock()
    mock_class.__table__ = mock_table

    mock_mapper = MagicMock()
    mock_mapper.class_ = mock_class

    mock_base = MagicMock()
    mock_base.registry.mappers = [mock_mapper]

    import db as db_module

    with patch.object(db_module, "engine", mock_engine), \
         patch.object(db_module, "Base", mock_base):

        from db import ensure_schema_columns
        await ensure_schema_columns()

    alter_stmts = [s for s in executed_stmts if "ALTER TABLE" in s.upper()]
    assert len(alter_stmts) == 1, f"Expected exactly 1 ALTER TABLE, got: {alter_stmts}"
    assert any("tenant_id" in s for s in alter_stmts), "Expected ALTER TABLE for tenant_id"
    assert not any("client_id" in s for s in alter_stmts), "client_id is already in DB, should not be altered"
    assert not any("org_id" in s for s in alter_stmts), "org_id is already in DB, should not be altered"
