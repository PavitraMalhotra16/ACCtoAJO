import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

FAKE_AUTH = {"access_token": "tok", "api_key": "key", "org_id": "O@AdobeOrg", "sandbox": "prod", "tenant_id": "_o"}


def _payload(**over):
    p = {
        "title": "cus:recipient",
        "behavior": "record",
        "fields": [
            {"name": "crmId", "label": "CRM ID", "type": "string", "required": True},
            {"name": "email", "label": "Email", "type": "string", "required": False},
            {"name": "lastModified", "label": "LM", "type": "string", "format": "date-time", "required": True},
        ],
        "primaryKey": ["crmId"],
        "versionField": "lastModified",
        "timestampField": None,
        "identityField": "email",
        "relationships": [],
    }
    p.update(over)
    return p


def _session_with_enriched(enriched):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    row = MagicMock()
    row.enriched_json = enriched
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)
    return session


def _auth_patch():
    return patch("pipeline.handlers._resolve_aep_auth", new=AsyncMock(return_value=FAKE_AUTH))


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_normalize_cardinality():
    from pipeline.handlers import _normalize_cardinality
    assert _normalize_cardinality("N:1") == "M:1"
    assert _normalize_cardinality("many-to-one") == "M:1"
    assert _normalize_cardinality("1:1") == "1:1"
    assert _normalize_cardinality(None) == "M:1"


def test_rel_source_property_root_level_only():
    from pipeline.handlers import _rel_source_property
    assert _rel_source_property("customerId") == "/customerId"
    assert _rel_source_property(["customerId"]) == "/customerId"
    assert _rel_source_property("billing/customerId") is None  # not root-level
    assert _rel_source_property(None) is None


def test_resolve_person_namespace():
    from pipeline.handlers import _resolve_person_namespace
    assert _resolve_person_namespace("email") == "Email"
    assert _resolve_person_namespace("crmId") == "CRMID"
    assert _resolve_person_namespace("orderId") is None  # not a person key


def test_refresh_scopes_carry_region_context():
    # additional_info.projectedProductContext carries the user's region; without it
    # AEP returns 403027 "User region is missing" on Schema Registry calls.
    from pipeline.handlers import IMS_SCOPES
    assert "additional_info.projectedProductContext" in IMS_SCOPES


def test_build_create_body_adhoc():
    from pipeline.handlers import _build_create_body
    body = _build_create_body(_payload(), "cus:recipient")
    assert body["meta:extends"] == ["https://ns.adobe.com/xdm/data/adhoc-v2"]
    assert body["title"] == "cus:recipient"
    assert body["description"] == "This table is about cus:recipient"
    props = body["definitions"]["customFields"]["properties"]
    assert set(props) == {"crmId", "email", "lastModified"}
    assert props["crmId"]["minLength"] == 1  # primary-key string
    assert props["lastModified"]["format"] == "date-time"
    assert set(body["definitions"]["customFields"]["required"]) == {"crmId", "lastModified"}
    assert "meta:behaviorType" not in body


def test_build_create_body_time_series():
    from pipeline.handlers import _build_create_body
    body = _build_create_body(_payload(behavior="time-series"), "cus:log")
    assert body["meta:behaviorType"] == "time-series"


# ── NORMALIZE_INPUT ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normalize_input_reads_enriched():
    from pipeline.handlers import normalize_input
    session = _session_with_enriched(json.dumps(_payload()))
    with patch("pipeline.handlers.AsyncSessionLocal", return_value=session):
        data = await normalize_input({"converted_schema_id": "x", "schema_name": "cus:recipient"}, {})
    assert data["ajoPayload"]["title"] == "cus:recipient"
    assert data["changesMade"] == 0


@pytest.mark.asyncio
async def test_normalize_input_fallback_to_memory():
    from pipeline.handlers import normalize_input
    session = _session_with_enriched(None)
    with patch("pipeline.handlers.AsyncSessionLocal", return_value=session):
        data = await normalize_input({"converted_schema_id": "x", "schema_name": "s"}, {"ajoPayload": _payload()})
    assert data["ajoPayload"]["primaryKey"] == ["crmId"]


# ── DUPLICATE_CHECK ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_check_found():
    from pipeline.handlers import duplicate_check
    schemas = [{"title": "cus:recipient", "$id": "https://ns.adobe.com/_o/schemas/abc"}]
    with _auth_patch(), patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=schemas)):
        data = await duplicate_check({"schema_name": "cus:recipient", "org_id": "O"}, {"ajoPayload": _payload()})
    assert data["schemaExisted"] is True
    assert data["aepSchemaId"].endswith("/abc")


@pytest.mark.asyncio
async def test_duplicate_check_not_found():
    from pipeline.handlers import duplicate_check
    with _auth_patch(), patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=[])):
        data = await duplicate_check({"schema_name": "cus:recipient", "org_id": "O"}, {"ajoPayload": _payload()})
    assert data["schemaExisted"] is False
    assert data["aepSchemaId"] is None


# ── CREATE_SCHEMA ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_schema_new():
    from pipeline.handlers import create_schema
    create_mock = AsyncMock(return_value={"$id": "https://ns.adobe.com/_o/schemas/new"})
    with _auth_patch(), patch("pipeline.handlers.aep_client.create_tenant_schema", new=create_mock):
        data = await create_schema(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": None, "pushTitle": "cus:recipient", "changesMade": 0},
        )
    assert data["aepSchemaId"].endswith("/new")
    assert data["changesMade"] == 1
    body = create_mock.call_args.args[2]
    assert body["title"] == "cus:recipient"
    assert body["meta:extends"] == ["https://ns.adobe.com/xdm/data/adhoc-v2"]


@pytest.mark.asyncio
async def test_create_schema_patches_missing_field():
    from pipeline.handlers import create_schema
    existing = {"definitions": {"customFields": {"properties": {"crmId": {}, "lastModified": {}}}}}
    patch_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.get_tenant_schema", new=AsyncMock(return_value=existing)), \
         patch("pipeline.handlers.aep_client.patch_tenant_schema", new=patch_mock):
        data = await create_schema(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "https://x/abc", "pushTitle": "cus:recipient", "changesMade": 0},
        )
    assert data["changesMade"] == 1  # only 'email' was missing
    ops = patch_mock.call_args.args[3]
    assert any(o["path"] == "/definitions/customFields/properties/email" for o in ops)


@pytest.mark.asyncio
async def test_create_schema_existing_no_changes():
    from pipeline.handlers import create_schema
    existing = {"definitions": {"customFields": {"properties": {"crmId": {}, "email": {}, "lastModified": {}}}}}
    patch_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.get_tenant_schema", new=AsyncMock(return_value=existing)), \
         patch("pipeline.handlers.aep_client.patch_tenant_schema", new=patch_mock):
        data = await create_schema(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "https://x/abc", "pushTitle": "cus:recipient", "changesMade": 0},
        )
    assert data["changesMade"] == 0
    patch_mock.assert_not_called()


# ── DESCRIPTORS ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_primary_key_descriptor_creates():
    from pipeline.handlers import primary_key_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await primary_key_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "SID", "changesMade": 0},
        )
    body = create_mock.call_args.args[2]
    assert body["@type"] == "xdm:descriptorPrimaryKey"
    assert body["xdm:sourceVersion"] == 1
    assert body["xdm:sourceProperty"] == ["/crmId"]
    assert data["changesMade"] == 1


@pytest.mark.asyncio
async def test_primary_key_descriptor_idempotent_on_already_exists():
    from pipeline.handlers import primary_key_descriptor
    # Re-run: the descriptor already exists; AEP returns a 400. It must be treated
    # as a no-op (not a failure, not a duplicate-count).
    create_mock = AsyncMock(side_effect=RuntimeError(
        'Create descriptor failed (HTTP 400): {"detail":"A xdm:descriptorPrimaryKey descriptor already exists, Only one is allowed"}'
    ))
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await primary_key_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "SID", "changesMade": 0},
        )
    create_mock.assert_called_once()
    assert data["changesMade"] == 0


@pytest.mark.asyncio
async def test_version_descriptor_creates():
    from pipeline.handlers import version_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await version_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "SID", "changesMade": 0},
        )
    body = create_mock.call_args.args[2]
    assert body["@type"] == "xdm:descriptorVersion"
    assert body["xdm:sourceVersion"] == 1
    assert body["xdm:sourceProperty"] == "/lastModified"
    assert data["changesMade"] == 1


@pytest.mark.asyncio
async def test_timestamp_descriptor_skips_record():
    from pipeline.handlers import timestamp_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await timestamp_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(behavior="record"), "aepSchemaId": "SID", "changesMade": 0},
        )
    create_mock.assert_not_called()
    assert data["changesMade"] == 0


@pytest.mark.asyncio
async def test_timestamp_descriptor_creates_for_time_series():
    from pipeline.handlers import timestamp_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await timestamp_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(behavior="time-series", timestampField="tsEvent"), "aepSchemaId": "SID", "changesMade": 0},
        )
    body = create_mock.call_args.args[2]
    assert body["@type"] == "xdm:descriptorTimestamp"
    assert body["xdm:sourceVersion"] == 1
    assert body["xdm:sourceProperty"] == "/tsEvent"
    assert data["changesMade"] == 1


# ── IDENTITY_DESCRIPTOR ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_identity_descriptor_person_key():
    from pipeline.handlers import identity_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_identity_namespaces", new=AsyncMock(return_value=[{"code": "Email"}])), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await identity_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(identityField="email"), "aepSchemaId": "SID", "changesMade": 0},
        )
    body = create_mock.call_args.args[2]
    assert body["@type"] == "xdm:descriptorIdentity"
    assert body["xdm:namespace"] == "Email"
    assert body["xdm:property"] == "xdm:code"
    assert data["changesMade"] == 1


@pytest.mark.asyncio
async def test_identity_descriptor_skips_non_string_field():
    from pipeline.handlers import identity_descriptor
    create_mock = AsyncMock(return_value={})
    # customerId maps to a person namespace (CRMID) but is typed integer here —
    # AEP only allows identity descriptors on string fields, so it must be skipped.
    payload = _payload(
        identityField="customerId",
        fields=[{"name": "customerId", "label": "Cust", "type": "integer", "required": True}],
    )
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_identity_namespaces", new=AsyncMock(return_value=[{"code": "CRMID"}])), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await identity_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": payload, "aepSchemaId": "SID", "changesMade": 0},
        )
    create_mock.assert_not_called()
    assert data["changesMade"] == 0


@pytest.mark.asyncio
async def test_identity_descriptor_skips_non_person_key():
    from pipeline.handlers import identity_descriptor
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await identity_descriptor(
            {"schema_name": "s", "org_id": "O"},
            {"ajoPayload": _payload(identityField="orderId"), "aepSchemaId": "SID", "changesMade": 0},
        )
    create_mock.assert_not_called()
    assert data["changesMade"] == 0


# ── RELATIONSHIP_DESCRIPTORS (PASS 2) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_relationship_descriptors_creates_and_defers():
    from pipeline.handlers import relationship_descriptors
    schemas = [{"title": "cus:order", "$id": "OID"}, {"title": "cus:recipient", "$id": "RID"}]
    links = [
        {"source_schema": "cus:order", "foreign_key": "iRecipientId", "target_schema": "cus:recipient", "target_key": "iRecipientId", "cardinality": "N:1"},
        {"source_schema": "cus:order", "foreign_key": "iCompanyId", "target_schema": "cus:company", "target_key": "id", "cardinality": "N:1"},  # target missing → defer
    ]
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=schemas)), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers._desired_links_touching", new=AsyncMock(return_value=links)), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await relationship_descriptors({"schema_name": "cus:order", "login_id": "u", "org_id": "O"}, {})
    assert data["relationshipsCreated"] == 1
    assert create_mock.call_count == 1
    body = create_mock.call_args.args[2]
    assert body["@type"] == "xdm:descriptorRelationship"
    assert body["xdm:sourceSchema"] == "OID"
    assert body["xdm:destinationSchema"] == "RID"
    assert body["xdm:sourceProperty"] == "/iRecipientId"
    assert body["xdm:sourceVersion"] == 1
    assert body["xdm:destinationProperty"] == "/iRecipientId"
    assert body["xdm:destinationVersion"] == 1
    assert body["xdm:cardinality"] == "M:1"


@pytest.mark.asyncio
async def test_relationship_descriptors_skips_existing():
    from pipeline.handlers import relationship_descriptors
    schemas = [{"title": "cus:order", "$id": "OID"}, {"title": "cus:recipient", "$id": "RID"}]
    links = [{"source_schema": "cus:order", "foreign_key": "iRecipientId", "target_schema": "cus:recipient", "target_key": None, "cardinality": "N:1"}]
    existing = [{"@type": "xdm:descriptorRelationship", "xdm:sourceSchema": "OID", "xdm:sourceProperty": "/iRecipientId", "xdm:destinationSchema": "RID"}]
    create_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=schemas)), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=existing)), \
         patch("pipeline.handlers._desired_links_touching", new=AsyncMock(return_value=links)), \
         patch("pipeline.handlers.aep_client.create_tenant_descriptor", new=create_mock):
        data = await relationship_descriptors({"schema_name": "cus:order", "login_id": "u", "org_id": "O"}, {})
    create_mock.assert_not_called()
    assert data["relationshipsCreated"] == 0


# ── VERIFY ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_ok():
    from pipeline.handlers import verify
    schemas = [{"title": "cus:recipient", "$id": "RID"}]
    descs = [
        {"@type": "xdm:descriptorPrimaryKey", "xdm:sourceSchema": "RID"},
        {"@type": "xdm:descriptorVersion", "xdm:sourceSchema": "RID"},
        {"@type": "xdm:descriptorRelationship", "xdm:sourceSchema": "RID"},
    ]
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=schemas)), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=descs)):
        data = await verify({"schema_name": "cus:recipient", "org_id": "O"}, {"ajoPayload": _payload(), "pushTitle": "cus:recipient"})
    v = data["verification"]
    assert v["schema"] and v["primaryKey"]
    assert v["relationships"] == 1


@pytest.mark.asyncio
async def test_verify_fails_when_schema_missing():
    from pipeline.handlers import verify
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=[])), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])):
        with pytest.raises(ValueError):
            await verify({"schema_name": "cus:recipient", "org_id": "O"}, {"ajoPayload": _payload(), "pushTitle": "cus:recipient"})


# ── WARNINGS (field-type / behavior mismatch on an existing schema) ──────────

def test_existing_field_types():
    from pipeline.handlers import _existing_field_types
    schema = {"definitions": {"customFields": {"properties": {
        "a": {"type": "string", "format": "date-time"},
        "b": {"type": "integer"},
    }}}}
    t = _existing_field_types(schema)
    assert t["a"] == ("string", "date-time")
    assert t["b"] == ("integer", None)


@pytest.mark.asyncio
async def test_create_schema_warns_on_type_mismatch():
    from pipeline.handlers import create_schema
    existing = {"definitions": {"customFields": {"properties": {
        "crmId": {"type": "integer"},                              # enriched wants string
        "email": {"type": "string"},
        "lastModified": {"type": "string", "format": "date-time"},
    }}}}
    patch_mock = AsyncMock(return_value={})
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.get_tenant_schema", new=AsyncMock(return_value=existing)), \
         patch("pipeline.handlers.aep_client.patch_tenant_schema", new=patch_mock):
        data = await create_schema(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(), "aepSchemaId": "https://x/abc", "pushTitle": "cus:recipient", "changesMade": 0, "warnings": []},
        )
    patch_mock.assert_not_called()
    assert data["changesMade"] == 0
    assert any("crmId" in w and "type mismatch" in w for w in data["warnings"])


@pytest.mark.asyncio
async def test_create_schema_warns_on_behavior_mismatch():
    from pipeline.handlers import create_schema
    existing = {"meta:behaviorType": "time-series", "definitions": {"customFields": {"properties": {
        "crmId": {"type": "string"},
        "email": {"type": "string"},
        "lastModified": {"type": "string", "format": "date-time"},
    }}}}
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.get_tenant_schema", new=AsyncMock(return_value=existing)), \
         patch("pipeline.handlers.aep_client.patch_tenant_schema", new=AsyncMock(return_value={})):
        data = await create_schema(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(behavior="record"), "aepSchemaId": "https://x/abc", "pushTitle": "cus:recipient", "changesMade": 0, "warnings": []},
        )
    assert any("Behavior mismatch" in w for w in data["warnings"])


@pytest.mark.asyncio
async def test_verify_includes_warning_count():
    from pipeline.handlers import verify
    schemas = [{"title": "cus:recipient", "$id": "RID"}]
    with _auth_patch(), \
         patch("pipeline.handlers.aep_client.list_tenant_schemas", new=AsyncMock(return_value=schemas)), \
         patch("pipeline.handlers.aep_client.list_tenant_descriptors", new=AsyncMock(return_value=[])):
        data = await verify(
            {"schema_name": "cus:recipient", "org_id": "O"},
            {"ajoPayload": _payload(), "pushTitle": "cus:recipient", "warnings": ["w1", "w2"]},
        )
    assert data["verification"]["warnings"] == 2
