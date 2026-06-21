import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _mock_session(scalar_one=None, scalar_one_or_none=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = MagicMock()
    if scalar_one is not None:
        result.scalar_one.return_value = scalar_one
    if scalar_one_or_none is not None:
        result.scalar_one_or_none.return_value = scalar_one_or_none
    session.execute = AsyncMock(return_value=result)
    return session


# ── LOAD_JSON ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_json_reads_from_db():
    from pipeline.handlers import load_json

    raw = {"source": {"fullName": "cus:recipient"}, "attributes": []}
    mock_schema = MagicMock()
    mock_schema.raw_json = json.dumps(raw)
    session = _mock_session(scalar_one=mock_schema)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=session):
        result = await load_json({"converted_schema_id": "abc-123"}, {})

    assert result == raw


@pytest.mark.asyncio
async def test_load_json_invalid_json_raises():
    from pipeline.handlers import load_json

    mock_schema = MagicMock()
    mock_schema.raw_json = "not valid json{"
    session = _mock_session(scalar_one=mock_schema)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=session):
        with pytest.raises(json.JSONDecodeError):
            await load_json({"converted_schema_id": "abc-123"}, {})


# ── MAP_TYPES (current code stores XDM type tokens as strings) ───────────────

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
    assert result["xdmTypes"]["id"] == "integer"
    assert result["xdmTypes"]["email"] == "string"
    assert result["xdmTypes"]["createdAt"] == "datetime"
    assert result["xdmTypes"]["active"] == "boolean"
    assert result["xdmTypes"]["score"] == "number"


@pytest.mark.asyncio
async def test_map_types_unknown_defaults_to_string():
    from pipeline.handlers import map_types
    result = await map_types({}, {"attributes": [{"name": "blob_col", "type": "blob"}]})
    assert result["xdmTypes"]["blob_col"] == "string"


# ── RESOLVE_IDENTITY ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_identity_autopk_true():
    from pipeline.handlers import resolve_identity
    data = {"keys": {"autoPk": {"enabled": True, "field": "iRecipientId"}, "primaryKeys": [], "uniqueKeys": []}}
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["status"] == "resolved"
    assert result["identityDecision"]["isPrimary"] is False
    assert result["identityDecision"]["fieldPath"] == "/iRecipientId"


@pytest.mark.asyncio
async def test_resolve_identity_explicit_pk():
    from pipeline.handlers import resolve_identity
    data = {"keys": {"autoPk": {"enabled": False}, "primaryKeys": [{"fields": ["customerId"]}], "uniqueKeys": []}}
    result = await resolve_identity({}, data)
    assert result["identityDecision"]["isPrimary"] is True
    assert result["identityDecision"]["fieldPath"] == "/customerId"


@pytest.mark.asyncio
async def test_resolve_identity_no_keys_is_unresolved():
    from pipeline.handlers import resolve_identity
    data = {"keys": {"autoPk": {"enabled": False}, "primaryKeys": [], "uniqueKeys": []}, "attributes": []}
    result = await resolve_identity({"schema_name": "cus:x"}, data)
    assert result["identityDecision"]["status"] == "unresolved"
    assert result["identityDecision"]["isPrimary"] is None


# ── FETCH_TENANT_ID ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_tenant_id_reads_from_destination():
    from pipeline.handlers import fetch_tenant_id

    mock_dest = MagicMock()
    mock_dest.tenant_id = "_acmecorp"
    session = _mock_session(scalar_one_or_none=mock_dest)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=session):
        result = await fetch_tenant_id({"org_id": "ABCD@AdobeOrg"}, {})

    assert result["tenantId"] == "_acmecorp"


# ── BUILD_PAYLOAD (current shape: list primaryKey, namespace:name title) ─────

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
        "xdmTypes": {"crmId": "string", "email": "string", "lastModified": "datetime"},
        "keys": {"autoPk": {"enabled": False}, "primaryKeys": [{"fields": ["crmId"]}], "uniqueKeys": [], "compositeKeys": []},
        "linksAndJoins": [],
    }
    result = await build_payload({"schema_name": "cus:recipient"}, data)
    payload = result["ajoPayload"]
    assert payload["title"] == "cus:recipient"          # ACC namespace:name (spec §4)
    assert payload["description"] == "All recipients"
    assert payload["behavior"] == "record"
    assert payload["primaryKey"] == ["crmId"]           # always a list
    assert payload["versionField"] == "lastModified"
    assert payload["timestampField"] is None
    assert payload["identityField"] == "email"
    fields = {f["name"]: f for f in payload["fields"]}
    assert fields["lastModified"]["type"] == "string"
    assert fields["lastModified"]["format"] == "date-time"
    assert fields["crmId"]["required"] is True          # PK forced required


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
        "xdmTypes": {"id": "integer", "tsEvent": "datetime"},
        "keys": {"autoPk": {"enabled": False}, "primaryKeys": [], "uniqueKeys": [], "compositeKeys": []},
        "linksAndJoins": [],
    }
    result = await build_payload({"schema_name": "cus:trackingLog"}, data)
    payload = result["ajoPayload"]
    assert payload["behavior"] == "time-series"
    assert payload["timestampField"] == "tsEvent"
    assert "tsEvent" in payload["primaryKey"]


@pytest.mark.asyncio
async def test_build_payload_relationships():
    from pipeline.handlers import build_payload
    data = {
        "source": {"fullName": "cus:order", "name": "order"},
        "schema": {"label": "Orders", "description": ""},
        "rootElement": {"name": "order"},
        "attributes": [],
        "xdmTypes": {},
        "keys": {"autoPk": {"enabled": True, "field": "id"}, "primaryKeys": [], "uniqueKeys": [], "compositeKeys": []},
        "linksAndJoins": [
            {
                "name": "recipient",
                "targetSchema": "cus:recipient",
                "join": {"sourceField": "iRecipientId", "destinationField": "iRecipientId"},
                "cardinality": "N:1",
            }
        ],
    }
    result = await build_payload({"schema_name": "cus:order"}, data)
    rels = result["ajoPayload"]["relationships"]
    assert len(rels) == 1
    assert rels[0]["targetSchema"] == "cus:recipient"
    assert rels[0]["foreignKey"] == "iRecipientId"
    assert rels[0]["cardinality"] == "N:1"
