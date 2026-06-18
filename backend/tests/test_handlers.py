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


# ── MAKE_ENRICHED_JSON ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_make_enriched_json_record_behavior():
    from pipeline.handlers import make_enriched_json as build_payload
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
async def test_make_enriched_json_time_series_behavior():
    from pipeline.handlers import make_enriched_json as build_payload
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
async def test_make_enriched_json_relationships():
    from pipeline.handlers import make_enriched_json as build_payload
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


# ── AEP PUSH STEPS (6–12) ─────────────────────────────────────────────────────

AUTH = {"token": "tok", "client_id": "key", "org_id": "O@AdobeOrg", "sandbox": "prod"}


def _resp(status, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    r.text = json.dumps(body if body is not None else {})
    return r


def _fake_client(get=None, post=None, patch_resp=None):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    if get is not None:
        client.get = AsyncMock(return_value=get)
    if post is not None:
        client.post = AsyncMock(return_value=post)
    if patch_resp is not None:
        client.patch = AsyncMock(return_value=patch_resp)
    return client


# ── Helpers ──

def test_class_ref_mapping():
    from pipeline.handlers import _class_ref
    assert _class_ref("record").endswith("/context/profile")
    assert _class_ref("time-series").endswith("/context/experienceevent")


def test_tenant_key_normalizes_underscore():
    from pipeline.handlers import _tenant_key, _source_property_path
    assert _tenant_key("acmecorp") == "_acmecorp"
    assert _tenant_key("_acmecorp") == "_acmecorp"          # no double underscore
    assert _source_property_path("_acmecorp", "crmId") == "/_acmecorp/crmId"


def test_description_synthesized_when_blank():
    from pipeline.handlers import _description
    assert _description({"description": ""}, "cus:members") == "this table is about cus:members"
    assert _description({"description": "Real desc"}, "cus:members") == "Real desc"


# ── Step 6: CALL_SCHEMA_API ──

@pytest.mark.asyncio
async def test_call_schema_api_reuses_existing_by_title():
    from pipeline.handlers import call_schema_api
    data = {"ajoPayload": {"title": "Members", "behavior": "record", "fields": []}}
    client = _fake_client(get=_resp(200, {"results": [{"title": "Members", "$id": "https://ns.adobe.com/_t/schemas/abc"}]}))
    with patch("pipeline.handlers._aep_auth", AsyncMock(return_value=AUTH)), \
         patch("pipeline.handlers.httpx.AsyncClient", return_value=client):
        out = await call_schema_api({"org_id": "O", "schema_name": "Members"}, data)
    assert out["schemaId"] == "https://ns.adobe.com/_t/schemas/abc"
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_call_schema_api_creates_when_absent():
    from pipeline.handlers import call_schema_api
    data = {"ajoPayload": {"title": "Members", "behavior": "record", "fields": []}}
    client = _fake_client(
        get=_resp(200, {"results": []}),
        post=_resp(201, {"$id": "https://ns.adobe.com/_t/schemas/new"}),
    )
    with patch("pipeline.handlers._aep_auth", AsyncMock(return_value=AUTH)), \
         patch("pipeline.handlers.httpx.AsyncClient", return_value=client):
        out = await call_schema_api({"org_id": "O", "schema_name": "Members"}, data)
    assert out["schemaId"].endswith("/new")
    assert out["schemaClassRef"].endswith("/context/profile")


# ── Step 8: ATTACH_FIELDGROUP — schema $id must be URL-encoded in the path ──

@pytest.mark.asyncio
async def test_attach_fieldgroup_url_encodes_schema_id():
    from pipeline.handlers import attach_fieldgroup
    data = {
        "schemaId": "https://ns.adobe.com/_t/schemas/abc",
        "fieldGroupId": "https://ns.adobe.com/_t/mixins/fg",
    }
    client = _fake_client(get=_resp(200, {"allOf": []}), patch_resp=_resp(200, {}))
    with patch("pipeline.handlers._aep_auth", AsyncMock(return_value=AUTH)), \
         patch("pipeline.handlers.httpx.AsyncClient", return_value=client):
        await attach_fieldgroup({"org_id": "O"}, data)
    patch_url = client.patch.call_args.args[0]
    assert "%3A" in patch_url and "%2F" in patch_url   # ':' and '/' encoded


@pytest.mark.asyncio
async def test_attach_fieldgroup_skips_if_already_attached():
    from pipeline.handlers import attach_fieldgroup
    fg = "https://ns.adobe.com/_t/mixins/fg"
    data = {"schemaId": "https://ns.adobe.com/_t/schemas/abc", "fieldGroupId": fg}
    client = _fake_client(get=_resp(200, {"allOf": [{"$ref": fg}]}))
    with patch("pipeline.handlers._aep_auth", AsyncMock(return_value=AUTH)), \
         patch("pipeline.handlers.httpx.AsyncClient", return_value=client):
        await attach_fieldgroup({"org_id": "O"}, data)
    client.patch.assert_not_called()


# ── Step 9: ENSURE_NAMESPACE ──

@pytest.mark.asyncio
async def test_ensure_namespace_skips_when_no_identity():
    from pipeline.handlers import ensure_namespace
    data = {"ajoPayload": {"identityNamespace": "CrmId"}, "identityDecision": {"isPrimary": None}}
    out = await ensure_namespace({"org_id": "O", "schema_name": "X"}, data)
    assert out["namespaceSkipped"] is True


@pytest.mark.asyncio
async def test_ensure_namespace_reuses_existing_code():
    from pipeline.handlers import ensure_namespace
    data = {"ajoPayload": {"identityNamespace": "CrmId"}, "identityDecision": {"isPrimary": True}}
    client = _fake_client(get=_resp(200, [{"code": "CrmId"}, {"code": "Email"}]))
    with patch("pipeline.handlers._aep_auth", AsyncMock(return_value=AUTH)), \
         patch("pipeline.handlers.httpx.AsyncClient", return_value=client):
        out = await ensure_namespace({"org_id": "O", "schema_name": "X"}, data)
    assert out["namespaceCode"] == "CrmId"
    client.post.assert_not_called()


# ── Step 11: ENABLE_PROFILE_UNION ──

@pytest.mark.asyncio
async def test_enable_union_skipped_when_not_primary():
    from pipeline.handlers import enable_profile_union
    data = {"identityDecision": {"isPrimary": False}, "schemaId": "x"}
    out = await enable_profile_union({"org_id": "O", "schema_name": "X"}, data)
    assert out == data  # returned unchanged, no API call


@pytest.mark.asyncio
async def test_descriptor_skipped_when_namespace_skipped():
    from pipeline.handlers import call_identity_descriptor
    data = {"namespaceSkipped": True}
    out = await call_identity_descriptor({"org_id": "O", "schema_name": "X"}, data)
    assert out == data
