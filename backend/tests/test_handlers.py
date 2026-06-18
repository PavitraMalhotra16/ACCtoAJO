import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── LOAD_JSON ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_json_reads_file(tmp_path):
    from pipeline.handlers import load_json
    schema_file = tmp_path / "cus_recipient.json"
    data = {"source": {"fullName": "cus:recipient"}, "attributes": []}
    schema_file.write_text(json.dumps(data))
    ctx = {"schema_storage_path": str(schema_file), "login_id": "u1", "schema_name": "cus:recipient", "org_id": "x"}
    result = await load_json(ctx, {})
    assert result == data


@pytest.mark.asyncio
async def test_load_json_missing_file(tmp_path):
    from pipeline.handlers import load_json
    ctx = {"schema_storage_path": str(tmp_path / "missing.json"), "login_id": "u1", "schema_name": "cus:x", "org_id": "x"}
    with pytest.raises(FileNotFoundError):
        await load_json(ctx, {})


# ── MAP_TYPES ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_map_types_standard():
    from pipeline.handlers import map_types
    data = {
        "attributes": [
            {"name": "id", "type": "int32"},
            {"name": "email", "type": "string"},
            {"name": "createdAt", "type": "datetime"},
            {"name": "active", "type": "boolean"},
            {"name": "score", "type": "double"},
        ]
    }
    result = await map_types({}, data)
    assert result["xdmTypes"]["id"] == {"type": "integer"}
    assert result["xdmTypes"]["email"] == {"type": "string"}
    assert result["xdmTypes"]["createdAt"] == {"type": "string", "format": "date-time"}
    assert result["xdmTypes"]["active"] == {"type": "boolean"}
    assert result["xdmTypes"]["score"] == {"type": "number"}


@pytest.mark.asyncio
async def test_map_types_unknown_defaults_to_string():
    from pipeline.handlers import map_types
    data = {"attributes": [{"name": "blob_col", "type": "blob"}]}
    result = await map_types({}, data)
    assert result["xdmTypes"]["blob_col"] == {"type": "string"}


@pytest.mark.asyncio
async def test_map_types_empty_attributes():
    from pipeline.handlers import map_types
    result = await map_types({}, {"attributes": []})
    assert result["xdmTypes"] == {}


# ── RESOLVE_IDENTITY ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_identity_autopk_true():
    from pipeline.handlers import resolve_identity
    data = {
        "keys": {
            "autoPk": {"enabled": True, "field": "iRecipientId"},
            "primaryKeys": [],
            "uniqueKeys": [],
        }
    }
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["status"] == "resolved"
    assert result["identityDecision"]["isPrimary"] is False
    assert result["identityDecision"]["fieldPath"] == "/iRecipientId"


@pytest.mark.asyncio
async def test_resolve_identity_explicit_pk():
    from pipeline.handlers import resolve_identity
    data = {
        "keys": {
            "autoPk": {"enabled": False, "field": None},
            "primaryKeys": [{"name": "pk", "fields": ["customerId"]}],
            "uniqueKeys": [],
        }
    }
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["isPrimary"] is True
    assert result["identityDecision"]["fieldPath"] == "/customerId"


@pytest.mark.asyncio
async def test_resolve_identity_fallback_to_unique_key():
    from pipeline.handlers import resolve_identity
    data = {
        "keys": {
            "autoPk": {"enabled": False, "field": None},
            "primaryKeys": [],
            "uniqueKeys": [{"name": "uq_email", "fields": ["email"]}],
        }
    }
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["isPrimary"] is True
    assert result["identityDecision"]["fieldPath"] == "/email"


@pytest.mark.asyncio
async def test_resolve_identity_no_keys_defaults_to_surrogate():
    from pipeline.handlers import resolve_identity
    data = {"keys": {"autoPk": {"enabled": False, "field": None}, "primaryKeys": [], "uniqueKeys": []}}
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["status"] == "resolved"
    assert result["identityDecision"]["isPrimary"] is False


# ── FETCH_TENANT_ID ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_tenant_id_uses_cache():
    from pipeline.handlers import fetch_tenant_id
    from datetime import datetime, timezone

    mock_cached = MagicMock()
    mock_cached.tenant_id = "_acmecorp"
    mock_cached.fetched_at = datetime.now(timezone.utc)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_cached
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=mock_session):
        result = await fetch_tenant_id({"org_id": "ABCD@AdobeOrg"}, {})

    assert result["tenantId"] == "_acmecorp"


# ── STUBS ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stubs_pass_data_through():
    from pipeline.handlers import (
        build_payload_stub,
        call_schema_api_stub,
        call_identity_descriptor_stub,
        verify_stub,
    )
    original = {"tenantId": "_test", "identityDecision": {"isPrimary": True}}
    for stub in [build_payload_stub, call_schema_api_stub, call_identity_descriptor_stub, verify_stub]:
        result = await stub({}, dict(original))
        assert result["tenantId"] == "_test"
