import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── LOAD_JSON ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_json_reads_from_db():
    from pipeline.handlers import load_json

    raw = {"source": {"fullName": "cus:recipient"}, "attributes": []}
    mock_schema = MagicMock()
    mock_schema.raw_json = json.dumps(raw)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_schema
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=mock_session):
        result = await load_json({"converted_schema_id": "abc-123"}, {})

    assert result == raw


@pytest.mark.asyncio
async def test_load_json_invalid_json_raises():
    from pipeline.handlers import load_json

    mock_schema = MagicMock()
    mock_schema.raw_json = "not valid json{"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = mock_schema
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=mock_session):
        with pytest.raises(json.JSONDecodeError):
            await load_json({"converted_schema_id": "abc-123"}, {})


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


# ── BUILD_PAYLOAD ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_payload_record_behavior():
    from pipeline.handlers import build_payload
    data = {
        "source": {"fullName": "cus:recipient", "name": "recipient"},
        "schema": {"label": "Recipients", "description": "All recipients"},
        "rootElement": {"name": "recipient"},
        "attributes": [
            {"name": "crmId", "label": "CRM ID", "type": "string"},
            {"name": "email", "label": "Email", "type": "string"},
            {"name": "lastModified", "label": "Last Modified", "type": "datetime"},
        ],
        "xdmTypes": {
            "crmId": {"type": "string"},
            "email": {"type": "string"},
            "lastModified": {"type": "string", "format": "date-time"},
        },
        "identityDecision": {"fieldPath": "/crmId", "isPrimary": True},
        "linksAndJoins": [],
    }
    result = await build_payload({}, data)
    payload = result["ajoPayload"]
    assert payload["title"] == "Recipients"
    assert payload["description"] == "All recipients"
    assert payload["behavior"] == "record"
    assert payload["primaryKey"] == "crmId"
    assert payload["identityNamespace"] == "CrmId"
    assert payload["versionField"] == "lastModified"
    assert "timestampField" not in payload
    assert len(payload["fields"]) == 3


@pytest.mark.asyncio
async def test_build_payload_time_series_behavior():
    from pipeline.handlers import build_payload
    data = {
        "source": {"fullName": "cus:trackingLog", "name": "trackingLog"},
        "schema": {"label": "Tracking Log", "description": ""},
        "rootElement": {"name": "trackingLog"},
        "attributes": [
            {"name": "id", "label": "ID", "type": "int32"},
            {"name": "tsEvent", "label": "Event Time", "type": "datetime"},
        ],
        "xdmTypes": {
            "id": {"type": "integer"},
            "tsEvent": {"type": "string", "format": "date-time"},
        },
        "identityDecision": {"fieldPath": "/id", "isPrimary": False},
        "linksAndJoins": [],
    }
    result = await build_payload({}, data)
    payload = result["ajoPayload"]
    assert payload["behavior"] == "time-series"
    assert payload["timestampField"] == "tsEvent"


@pytest.mark.asyncio
async def test_build_payload_relationships():
    from pipeline.handlers import build_payload
    data = {
        "source": {"fullName": "cus:order"},
        "schema": {"label": "Orders", "description": ""},
        "rootElement": {"name": "order"},
        "attributes": [],
        "xdmTypes": {},
        "identityDecision": {"fieldPath": "/id"},
        "linksAndJoins": [
            {
                "name": "recipient",
                "targetSchema": "cus:recipient",
                "join": {"sourceField": "iRecipientId", "destinationField": "iRecipientId"},
                "cardinality": "many-to-one",
            }
        ],
    }
    result = await build_payload({}, data)
    rels = result["ajoPayload"]["relationships"]
    assert len(rels) == 1
    assert rels[0]["targetSchema"] == "cus:recipient"
    assert rels[0]["cardinality"] == "many-to-one"


# ── STUBS ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stubs_pass_data_through():
    from pipeline.handlers import (
        call_schema_api_stub,
        call_identity_descriptor_stub,
        verify_stub,
    )
    original = {"tenantId": "_test", "ajoPayload": {"title": "Test"}}
    for stub in [call_schema_api_stub, call_identity_descriptor_stub, verify_stub]:
        result = await stub({}, dict(original))
        assert result["tenantId"] == "_test"
