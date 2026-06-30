import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import InvalidToken as FernetInvalidToken
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from db import AsyncSessionLocal, ConvertedSchema, DestinationConnection, ensure_schema_columns
from core.security import decrypt, encrypt
from pipeline import aep_client

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"


async def get_valid_access_token(dest: DestinationConnection, db) -> str:
    """Return a valid access token, refreshing via OAuth S2S if expired or close to expiry."""
    now = datetime.now(timezone.utc)
    buffer = timedelta(minutes=5)

    if dest.token_expires_at and dest.token_expires_at > now + buffer:
        try:
            return decrypt(dest.encrypted_access_token)
        except FernetInvalidToken:
            raise ValueError("AJO access token could not be decrypted — the encryption key may have changed. Please reconnect AJO.")

    # Token expired or missing — refresh using stored client_id:client_secret
    if not dest.encrypted_credentials:
        raise ValueError("No OAuth credentials stored — reconnect AJO")

    try:
        raw = decrypt(dest.encrypted_credentials)
    except FernetInvalidToken:
        raise ValueError("AJO credentials could not be decrypted — the encryption key may have changed. Please reconnect AJO.")
    parts = raw.split(":", 1)
    if len(parts) != 2:
        raise ValueError("Stored credentials malformed — reconnect AJO")
    client_id, client_secret = parts

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            IMS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": IMS_SCOPES,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise ValueError(f"Token refresh failed ({resp.status_code}): {resp.text[:200]}")

    payload = resp.json()
    new_token = payload.get("access_token")
    if not new_token:
        raise ValueError("IMS did not return access_token during refresh")

    expires_in = int(payload.get("expires_in", 3600))
    if expires_in > 86_400:
        expires_in //= 1000

    dest.encrypted_access_token = encrypt(new_token)
    dest.token_expires_at = now + timedelta(seconds=expires_in)
    await db.commit()

    log.info("Access token refreshed for org %s (expires in %ds)", dest.org_id, expires_in)
    return new_token

log = logging.getLogger("acc_backend.pipeline.handlers")

ACC_TO_XDM: dict[str, str] = {
    "string":   "string",
    "memo":     "string",
    "uuid":     "string",
    "int":      "integer",
    "int32":    "integer",
    "integer":  "integer",
    "short":    "integer",
    "byte":     "integer",
    "int64":    "integer",
    "long":     "integer",
    "double":   "number",
    "float":    "number",
    "number":   "number",
    "boolean":  "boolean",
    "datetime": "datetime",
    "date":     "date",
}

# CDC ingestion control column — never part of the schema
_EXCLUDED_FIELDS = {"_change_request_type"}

_TIME_SERIES_KEYWORDS = {"log", "tracking", "history", "broadlog", "event", "histo", "delivery", "statistics"}

_VERSION_FIELD_NAMES = [
    "lastmodified", "tslastmodified", "lastmodifieddate", "modified",
    "updated", "updatedate", "updatedat", "dtmodified", "tsmodification",
    "tschanged", "version", "versionnumber",
]
_TIMESTAMP_FIELD_NAMES = [
    "eventdate", "eventtime", "timestamp", "logdate", "tsevent",
    "eventts", "eventtime", "tscreated", "created", "contactdate",
]
_IDENTITY_PRECEDENCE = [
    "email", "customerid", "personid", "recipientid", "crmid", "phone", "mobilephone",
]

# Well-known field → AEP standard namespace (used only for identityDescriptor in Phase 3)
_NAME_TO_NAMESPACE: dict[str, str] = {
    "email":        "Email",
    "emailaddress": "Email",
    "externid":     "ECID",
    "externalid":   "ECID",
    "ecid":         "ECID",
    "customerid":   "CustomerID",
    "userid":       "UserID",
    "phonenumber":  "Phone",
    "phone":        "Phone",
    "mobilenumber": "Phone",
}
_RULE3_PRIMARY = {"customerid", "userid"}
_RULE3_SECONDARY = {"email", "emailaddress", "externid", "externalid", "ecid", "phonenumber", "phone", "mobilenumber"}
_RULE3_NAMES = _RULE3_PRIMARY | _RULE3_SECONDARY


def _auto_map_namespace(field_name: str) -> str | None:
    return _NAME_TO_NAMESPACE.get((field_name or "").lower())


def _derive_namespace(field_name: str) -> str:
    mapped = _auto_map_namespace(field_name)
    if mapped:
        return mapped
    if not field_name:
        return "CustomID"
    return field_name[0].upper() + field_name[1:]


def _match_org_namespace(field_name: str, org_namespaces: list[dict]) -> str | None:
    import re
    normalized = re.sub(r"[^a-z0-9]", "", field_name.lower())
    for ns in org_namespaces:
        code = re.sub(r"[^a-z0-9]", "", (ns.get("code") or "").lower())
        name = re.sub(r"[^a-z0-9]", "", (ns.get("name") or "").lower())
        if normalized == code or normalized == name:
            return ns.get("code")
    return None


def _infer_behavior(source_name: str, root_name: str) -> str:
    combined = (source_name + root_name).lower()
    return "time-series" if any(kw in combined for kw in _TIME_SERIES_KEYWORDS) else "record"


def _compute_primary_key(keys: dict) -> list[str]:
    """Returns the primary key as a list. Empty list = unresolved."""
    pk = keys.get("primaryKeys", [])
    if pk:
        fields = pk[0].get("fields", [])
        if fields:
            return list(fields)

    composite = keys.get("compositeKeys", [])
    if composite:
        fields = composite[0].get("fields", [])
        if fields:
            return list(fields)

    auto_pk = keys.get("autoPk", {})
    if auto_pk.get("enabled"):
        return [auto_pk.get("field") or "id"]

    return []


def _compute_behavior(keys: dict, source_name: str, root_name: str) -> str:
    """Determine AEP behavior type.

    Priority order:
    1. autoPk → always record
    2. Composite key containing a datetime-named field → time-series
    3. Multi-field primary key containing a datetime-named field → time-series
    4. Single primary key that is itself datetime-named → time-series
    5. Any primary key structure without datetime hints → record
    6. No key structure at all → fall back to schema-name keyword inference
       (e.g. deliveryStatus, orderHistory, broadlog → time-series)
    """
    _TIMESTAMP_HINTS = {"date", "time", "ts", "timestamp", "created", "updated", "event"}

    def has_ts_field(fields: list[str]) -> bool:
        return any(any(h in f.lower() for h in _TIMESTAMP_HINTS) for f in fields)

    auto_pk = keys.get("autoPk", {})
    if auto_pk.get("enabled"):
        return "record"

    composite_keys = keys.get("compositeKeys", [])
    if composite_keys:
        fields = composite_keys[0].get("fields", [])
        return "time-series" if has_ts_field(fields) else "record"

    primary_keys = keys.get("primaryKeys", [])
    if primary_keys:
        fields = primary_keys[0].get("fields", [])
        if len(fields) > 1:
            return "time-series" if has_ts_field(fields) else "record"
        if len(fields) == 1 and has_ts_field(fields):
            return "time-series"
        return "record"

    # No key structure — fall back to schema name keywords
    return _infer_behavior(source_name, root_name)


def _compute_version_field(attributes: list[dict], primary_key: list[str], xdm_types: dict) -> str | None:
    """Version field must be datetime or numeric, and must not be in primaryKey.

    AEP xdm:descriptorVersion requires number, integer, or string with format date-time.
    Plain 'date' fields (format: date) are NOT accepted — only 'datetime' qualifies.
    """
    _NUMERIC = {"integer", "long", "number"}
    _DATETIME = {"datetime"}  # 'date' excluded — AEP rejects format:date for version descriptor
    pk_set = set(primary_key)

    def is_eligible(attr: dict) -> bool:
        name = attr.get("name") or ""
        t = xdm_types.get(name, "string")
        return t in (_NUMERIC | _DATETIME) and name not in pk_set

    for attr in attributes:
        name = (attr.get("name") or "").lower()
        if any(p == name or p in name for p in _VERSION_FIELD_NAMES) and is_eligible(attr):
            return attr["name"]

    # Fallback: any eligible datetime field
    for attr in attributes:
        if is_eligible(attr) and xdm_types.get(attr.get("name") or "", "string") in _DATETIME:
            return attr["name"]

    return None


def _compute_timestamp_field(attributes: list[dict], primary_key: list[str], xdm_types: dict) -> str | None:
    """Timestamp field must be datetime and must be (or will be added to) primaryKey."""
    datetime_attrs = [
        a for a in attributes
        if xdm_types.get(a.get("name") or "", "string") in ("datetime", "date")
    ]

    for attr in datetime_attrs:
        name = (attr.get("name") or "").lower()
        if any(p == name or p in name for p in _TIMESTAMP_FIELD_NAMES):
            return attr["name"]

    # Fallback: first datetime field
    return datetime_attrs[0]["name"] if datetime_attrs else None


def _compute_identity_field(attributes: list[dict], primary_key: list[str], xdm_types: dict) -> str | None:
    attr_lower = {(a.get("name") or "").lower(): a.get("name") for a in attributes}

    for pattern in _IDENTITY_PRECEDENCE:
        if pattern in attr_lower:
            return attr_lower[pattern]

    # Fallback: first string primary key field
    for pk_field in primary_key:
        if xdm_types.get(pk_field, "string") == "string":
            return pk_field

    return None


def _xdm_field_type(xdm_type: str) -> dict:
    """Convert internal type token to the final JSON field type shape."""
    if xdm_type == "datetime":
        return {"type": "string", "format": "date-time"}
    if xdm_type == "date":
        return {"type": "string", "format": "date"}
    return {"type": xdm_type}


def _build_fields(
    attributes: list[dict],
    xdm_types: dict,
    required_overrides: set[str],
) -> list[dict]:
    fields = []
    for attr in attributes:
        name = attr.get("name")
        if not name or name in _EXCLUDED_FIELDS:
            continue
        xdm_type = xdm_types.get(name, "string")
        type_shape = _xdm_field_type(xdm_type)
        is_required = bool(
            attr.get("required")
            or attr.get("notNull")
            or attr.get("nullable") is False
            or name in required_overrides
        )
        field: dict = {
            "name": name,
            "required": is_required,
            "label": attr.get("label") or name,
            "description": attr.get("description") or "",
            "sourcePath": attr.get("xpath") or f"/{name}",
        }
        field.update(type_shape)  # adds "type" and optionally "format"
        fields.append(field)
    return fields


def _build_relationships(links_and_joins: list[dict]) -> list[dict]:
    result = []
    for link in links_and_joins:
        if not link.get("targetSchema"):
            continue
        join = link.get("join") or {}
        is_composite = bool(join.get("composite", False))
        source_field = join.get("sourceField")
        dest_field = join.get("destinationField")

        foreign_key = (
            ([source_field] if source_field else []) if is_composite else source_field
        )
        target_key = (
            ([dest_field] if dest_field else None) if is_composite else dest_field
        )

        result.append({
            "foreignKey": foreign_key,
            "targetSchema": link["targetSchema"],
            "targetKey": target_key,
            "cardinality": link.get("cardinality") or "M:1",
            "composite": is_composite,
            "sourceLabel": link.get("sourceLabel"),
            "destinationLabel": link.get("destinationLabel"),
            "integrity": link.get("integrity"),
            "reverseIntegrity": link.get("reverseIntegrity"),
        })
    return result


async def load_json(ctx: dict, data: dict) -> dict:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConvertedSchema).where(ConvertedSchema.id == ctx["converted_schema_id"])
        )
        schema = result.scalar_one()
        return json.loads(schema.raw_json)


async def map_types(ctx: dict, data: dict) -> dict:
    xdm_types: dict[str, str] = {}
    for attr in data.get("attributes", []):
        name = attr.get("name")
        if not name:
            continue
        acc_type = (attr.get("type") or "string").lower()
        xdm_types[name] = ACC_TO_XDM.get(acc_type, "string")
        if acc_type not in ACC_TO_XDM:
            log.warning("Unknown ACC type %r for field %r — defaulting to string", acc_type, name)
    data["xdmTypes"] = xdm_types
    return data


async def resolve_identity(ctx: dict, data: dict) -> dict:
    keys = data.get("keys", {})
    auto_pk = keys.get("autoPk", {})

    if auto_pk.get("enabled"):
        field = auto_pk.get("field") or "id"
        data["identityDecision"] = {
            "status": "resolved",
            "fieldPath": f"/{field}",
            "isPrimary": False,
            "reason": "Auto-generated surrogate key — identity but not primary identity",
        }
        return data

    primary_keys = keys.get("primaryKeys", [])
    if primary_keys:
        fields = primary_keys[0].get("fields", [])
        if fields:
            field = fields[0]
            namespace = _auto_map_namespace(field)
            data["identityDecision"] = {
                "status": "resolved",
                "fieldPath": f"/{field}",
                "isPrimary": True,
                "namespace": namespace or _derive_namespace(field),
                "reason": "Explicit primary key field — treated as primary identity",
            }
            return data

    unique_keys = keys.get("uniqueKeys", [])
    if unique_keys:
        fields = unique_keys[0].get("fields", [])
        field = fields[0] if fields else "id"
        namespace = _auto_map_namespace(field)
        data["identityDecision"] = {
            "status": "resolved",
            "fieldPath": f"/{field}",
            "isPrimary": True,
            "namespace": namespace or _derive_namespace(field),
            "reason": "No explicit PK — first unique key used as primary identity",
        }
        return data

    # Rule 3: well-known field name pattern matching
    attributes = data.get("attributes", [])
    for attr in attributes:
        name = (attr.get("name") or "").lower()
        if name in _RULE3_NAMES:
            original_name = attr["name"]
            namespace = _auto_map_namespace(original_name)
            is_primary = name in _RULE3_PRIMARY
            data["identityDecision"] = {
                "status": "resolved",
                "fieldPath": f"/{original_name}",
                "isPrimary": is_primary,
                "namespace": namespace,
                "reason": (
                    f"Field name {original_name!r} matched known identity pattern — "
                    f"auto-mapped to {namespace} ({'primary anchor' if is_primary else 'secondary/stitching identity'})"
                ),
            }
            log.info("Rule 3 identity match: %s → namespace %s, isPrimary=%s", original_name, namespace, is_primary)
            return data

    # No identity found — warn, do not silently default
    log.warning("No identity field found for schema %s", ctx.get("schema_name", "unknown"))
    data["identityDecision"] = {
        "status": "unresolved",
        "fieldPath": None,
        "isPrimary": None,
        "reason": "No primary key, unique key, or known identity field name found — manual mapping required",
    }
    return data


def _derive_tenant_id(org_id: str) -> str:
    """Adobe tenant ID = underscore + lowercase of the org ID before @AdobeOrg."""
    base = org_id.split("@")[0].lower()
    return f"_{base}"


async def fetch_tenant_id(ctx: dict, data: dict) -> dict:
    """Read tenant ID from DestinationConnection. Auto-repairs missing column once if needed."""
    org_id = ctx["org_id"]

    async def _query_tenant_id() -> str | None:
        async with AsyncSessionLocal() as db:
            dest_result = await db.execute(
                select(DestinationConnection).where(DestinationConnection.org_id == org_id)
            )
            dest = dest_result.scalar_one_or_none()
        return dest.tenant_id if dest and dest.tenant_id else None

    try:
        tenant_id = await _query_tenant_id()
    except ProgrammingError as exc:
        if "column" in str(exc).lower():
            log.warning("Missing DB column detected in fetch_tenant_id — running ensure_schema_columns")
            await ensure_schema_columns()
            tenant_id = await _query_tenant_id()
        else:
            raise

    if not tenant_id:
        tenant_id = _derive_tenant_id(org_id)
        log.warning("tenant_id not on DestinationConnection for %s — derived as %s", org_id, tenant_id)

    data["tenantId"] = tenant_id
    log.info("Tenant ID %r for org %s", tenant_id, org_id)
    return data


async def build_payload(ctx: dict, data: dict) -> dict:
    source = data.get("source", {})
    schema_meta = data.get("schema", {})
    root = data.get("rootElement", {})
    attributes = data.get("attributes", [])
    xdm_types = data.get("xdmTypes", {})
    keys = data.get("keys", {})
    links_and_joins = data.get("linksAndJoins", [])

    source_name = source.get("name") or source.get("fullName", "")
    root_name = root.get("name") or ""

    # Namespace prefix — keeps schemas with identical names but different namespaces distinct
    schema_name = ctx.get("schema_name", "")
    namespace = schema_name.split(":")[0] if ":" in schema_name else ""

    # A. title — the ACC namespace:name (unique dedup key + relationship-resolution
    #    key; spec §4). Fallbacks keep a sensible value if schema_name is absent.
    base_title = (
        schema_meta.get("label")
        or root.get("label")
        or root.get("sqlTable")
        or source.get("fullName")
        or source_name
    )
    title = schema_name or (f"{namespace}:{base_title}" if namespace else base_title)

    # B. description
    description = (
        schema_meta.get("description")
        or schema_meta.get("labelSingular")
        or root.get("label")
        or f"Schema for {title}"
    )

    # C. behavior (key-structure first, keyword fallback on schema name + source name)
    behavior = _compute_behavior(keys, source_name + schema_name, root_name)

    # E. primaryKey — always a list
    primary_key = _compute_primary_key(keys)

    # G. timestampField — only for time-series; must be in primaryKey
    timestamp_field: str | None = None
    if behavior == "time-series":
        timestamp_field = _compute_timestamp_field(attributes, primary_key, xdm_types)
        if timestamp_field and timestamp_field not in primary_key:
            primary_key.append(timestamp_field)

    # F. versionField — datetime/numeric, not in primaryKey
    version_field = _compute_version_field(attributes, primary_key, xdm_types)

    # For time-series schemas where the only datetime field is the PK (e.g. deliveryStatus),
    # AEP requires xdm:descriptorVersion on a DIFFERENT field from xdm:descriptorPrimaryKey
    # (XDM-1855). Inject a synthetic integer field "_recordVersion" so both descriptors can coexist.
    if version_field is None and behavior == "time-series":
        _SYNTHETIC_VERSION = "_recordVersion"
        attributes = list(attributes) + [{"name": _SYNTHETIC_VERSION, "label": "Record Version", "xdmType": "integer"}]
        xdm_types = {**xdm_types, _SYNTHETIC_VERSION: "integer"}
        version_field = _SYNTHETIC_VERSION
        log.info("Schema %s: injected synthetic '%s' field for version descriptor", schema_name, _SYNTHETIC_VERSION)

    # H. identityField — single field name, simple precedence
    identity_field = _compute_identity_field(attributes, primary_key, xdm_types)

    # Required overrides: PK fields + versionField + timestampField must be required in fields[]
    required_overrides: set[str] = set(primary_key)
    if version_field:
        required_overrides.add(version_field)
    if timestamp_field:
        required_overrides.add(timestamp_field)

    # D. fields
    fields = _build_fields(attributes, xdm_types, required_overrides)

    # I. relationships
    relationships = _build_relationships(links_and_joins)

    payload: dict = {
        "title": title,
        "description": description,
        "behavior": behavior,
        "tenantId": data.get("tenantId"),
        "fields": fields,
        "primaryKey": primary_key,
        "versionField": version_field,
        "timestampField": timestamp_field,
        "identityField": identity_field,
        "relationships": relationships,
    }

    data["ajoPayload"] = payload
    log.info(
        "Built payload for %s: behavior=%s primaryKey=%s identityField=%s",
        source_name, behavior, primary_key, identity_field,
    )
    return data


# ════════════════════════════════════════════════════════════════════════════
# Phase 3 — push the relational schema into AEP / AJO (spec §4–§11)
#
# Every push handler reconciles desired state (the enriched JSON) against the
# live Schema Registry: it creates only what is missing, so reruns/resumes are
# idempotent and no extra state is persisted. The AEP schema *title* is the ACC
# `namespace:name`, which is unique and is also how relationship targets are
# resolved back to their $id.
# ════════════════════════════════════════════════════════════════════════════

_NAMESPACE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "namespace_config.json")


def _load_namespace_config() -> dict:
    try:
        with open(_NAMESPACE_CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        log.warning("namespace_config.json missing/invalid — identity descriptors disabled")
        return {"namespaceMapping": {}, "personNamespaces": [], "idTypeByNamespace": {}, "defaultIdType": "CROSS_DEVICE"}


_NAMESPACE_CONFIG = _load_namespace_config()


# ── auth / headers ───────────────────────────────────────────────────────────
async def _resolve_aep_auth(ctx: dict) -> dict:
    """Load AJO destination creds + a valid (decrypted, refreshed) access token."""
    org_id = ctx["org_id"]
    async with AsyncSessionLocal() as db:
        dest = (
            await db.execute(
                select(DestinationConnection).where(DestinationConnection.org_id == org_id)
            )
        ).scalar_one_or_none()
        if not dest or not dest.authenticated:
            raise ValueError("AJO is not connected — connect AJO before pushing schemas")
        token = await get_valid_access_token(dest, db)

        # client_id column may be NULL on rows created before that column existed.
        # The authoritative value is always the first segment of encrypted_credentials.
        api_key = dest.client_id
        if not api_key and dest.encrypted_credentials:
            try:
                raw = decrypt(dest.encrypted_credentials)
                api_key = raw.split(":", 1)[0]
                # Backfill the column so future calls don't need to decrypt again.
                dest.client_id = api_key
                await db.commit()
            except Exception:
                pass

        log.info("AEP auth resolved — org=%s api_key_present=%s api_key_value=%r sandbox=%s",
                 dest.org_id, bool(api_key), api_key, dest.sandbox_name)
        return {
            "access_token": token,
            "api_key": api_key,
            "org_id": dest.org_id,
            "sandbox": dest.sandbox_name.strip(),
            "tenant_id": dest.tenant_id,
        }


def _headers(auth: dict, content_type: bool = True) -> dict:
    h = {
        "Authorization": f"Bearer {auth['access_token']}",
        "x-api-key": auth.get("api_key") or "",
        "x-gw-ims-org-id": auth["org_id"],
        "x-sandbox-name": auth.get("sandbox") or "prod",
    }
    if content_type:
        h["Content-Type"] = "application/json"
    return h


# ── small builders / matchers ────────────────────────────────────────────────
def _push_title(ctx: dict, payload: dict) -> str:
    # Schema title in AJO uses the same PascalCase notation as the dataset name:
    # hdbk:deliveryStatus → HdbkDeliveryStatus (no colon, namespace + schema both capitalized).
    schema_name = ctx.get("schema_name") or payload.get("title") or ""
    return _dataset_name(schema_name) if schema_name else ""


def _field_to_property(field: dict, is_primary: bool) -> dict:
    prop: dict = {"title": field.get("label") or field.get("name")}
    if field.get("description"):
        prop["description"] = field["description"]
    prop["type"] = field.get("type", "string")
    if field.get("format"):
        prop["format"] = field["format"]
    # Enforce non-empty primary-key strings (spec §4 example uses minLength: 1).
    if is_primary and prop["type"] == "string":
        prop["minLength"] = 1
    return prop


def _build_create_body(payload: dict, title: str) -> dict:
    """Relational create body: meta:extends adhoc-v2 + direct customFields + allOf (spec §4)."""
    primary_key = set(payload.get("primaryKey") or [])
    properties: dict = {}
    required: list[str] = []
    for field in payload.get("fields", []):
        name = field.get("name")
        if not name:
            continue
        properties[name] = _field_to_property(field, name in primary_key)
        if field.get("required"):
            required.append(name)
    custom_fields: dict = {"type": "object", "properties": properties}
    if required:
        custom_fields["required"] = required
    body: dict = {
        "title": title,
        "type": "object",
        "description": f"This table is about {title}",
        "meta:extends": [aep_client.ADHOC_EXTENDS],
        "definitions": {"customFields": custom_fields},
        "allOf": [{"$ref": "#/definitions/customFields"}],
    }
    body["meta:behaviorType"] = "time-series" if payload.get("behavior") == "time-series" else "record"
    return body


def _existing_property_names(schema_full: dict) -> set[str]:
    names: set[str] = set()
    for key in (schema_full.get("properties") or {}):
        names.add(key)
    defs = schema_full.get("definitions") or {}
    custom = (defs.get("customFields") or {}).get("properties") or {}
    for key in custom:
        names.add(key)
    return names


def _existing_field_types(schema_full: dict) -> dict[str, tuple]:
    """Map field name → (type, format) from a fetched schema, for type-diff warnings."""
    out: dict[str, tuple] = {}

    def ingest(props):
        for name, spec in (props or {}).items():
            if isinstance(spec, dict):
                out[name] = (spec.get("type"), spec.get("format"))

    ingest(schema_full.get("properties"))
    defs = schema_full.get("definitions") or {}
    ingest((defs.get("customFields") or {}).get("properties"))  # adhoc fields win
    return out


def _descriptors_for(descriptors: list[dict], schema_id: str) -> list[dict]:
    return [d for d in descriptors if d.get("xdm:sourceSchema") == schema_id]


def _has_descriptor(descriptors: list[dict], schema_id: str, dtype: str, source_property=None) -> bool:
    for d in descriptors:
        if d.get("xdm:sourceSchema") != schema_id or d.get("@type") != dtype:
            continue
        if source_property is None or d.get("xdm:sourceProperty") == source_property:
            return True
    return False


def _has_relationship(descriptors: list[dict], source_id: str, source_property: str, dest_id: str) -> bool:
    for d in descriptors:
        if (
            d.get("@type") == "xdm:descriptorRelationship"
            and d.get("xdm:sourceSchema") == source_id
            and d.get("xdm:sourceProperty") == source_property
            and d.get("xdm:destinationSchema") == dest_id
        ):
            return True
    return False


async def _fetch_descriptors(client: httpx.AsyncClient, headers: dict, schema_id: str) -> list[dict]:
    return _descriptors_for(await aep_client.list_tenant_descriptors(client, headers), schema_id)


async def _create_descriptor(client: httpx.AsyncClient, headers: dict, body: dict) -> bool:
    """Create a descriptor idempotently. GET /tenant/descriptors does not list
    version/timestamp descriptors, so they can't be reliably pre-checked — instead
    attempt the create and treat an 'already exists / only one allowed' 400 as a
    no-op. Returns True if newly created, False if it already existed."""
    try:
        await aep_client.create_tenant_descriptor(client, headers, body)
        return True
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "already exists" in msg or "only one" in msg:
            log.info("Descriptor %s already present on %s — skipping",
                     body.get("@type"), body.get("xdm:sourceSchema"))
            return False
        # XDM-1855: version/timestamp descriptor attempted on a field that is already
        # a primary key in AEP (common when behavior was created as time-series but
        # enriched JSON targets record — behavior is immutable so we skip gracefully).
        if "xdm-1855" in msg or "cannot be defined on xdm:descriptorprimarykey" in msg:
            log.warning("Descriptor %s skipped on %s — field '%s' is already a primary key in AEP",
                        body.get("@type"), body.get("xdm:sourceSchema"), body.get("xdm:sourceProperty"))
            return False
        raise


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _resolve_person_namespace(field_name: str) -> str | None:
    """Return the namespace code only if the field maps to a genuine person key (spec §8)."""
    mapping = _NAMESPACE_CONFIG.get("namespaceMapping", {})
    person = set(_NAMESPACE_CONFIG.get("personNamespaces", []))
    ns = mapping.get(_normalize_name(field_name))
    return ns if ns and ns in person else None


def _normalize_cardinality(card: str | None) -> str:
    """Map ACC cardinality forms to the accepted set: 1:1, 1:0, M:1, M:0 (spec §9)."""
    c = (card or "").strip().lower()
    if c in ("1:1", "one-to-one", "onetoone"):
        return "1:1"
    if c == "1:0":
        return "1:0"
    if c in ("m:0", "n:0"):
        return "M:0"
    return "M:1"  # foreign-key links (many source → one target) — the common case


def _rel_source_property(foreign_key) -> str | None:
    """Foreign keys must be root-level — a single path segment (spec §9)."""
    if isinstance(foreign_key, list):
        foreign_key = foreign_key[0] if foreign_key else None
    if not foreign_key:
        return None
    fk = str(foreign_key).lstrip("/")
    if "/" in fk:
        return None
    return f"/{fk}"


# ── Step 6: NORMALIZE_INPUT ──────────────────────────────────────────────────
async def normalize_input(ctx: dict, data: dict) -> dict:
    """Read the enriched JSON from the DB, ensure it parses, use it as push input."""
    payload = None
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(ConvertedSchema).where(ConvertedSchema.id == ctx["converted_schema_id"])
            )
        ).scalar_one_or_none()
        enriched = row.enriched_json if row else None

    if isinstance(enriched, dict):
        payload = enriched
    elif enriched:
        try:
            payload = json.loads(enriched)
        except (json.JSONDecodeError, TypeError):
            log.warning("enriched_json for %s was not valid JSON — falling back to in-memory payload",
                        ctx.get("schema_name"))
            payload = None

    if payload is None:
        payload = data.get("ajoPayload")
    if not isinstance(payload, dict):
        raise ValueError("No enriched JSON payload available to push")

    data["ajoPayload"] = payload
    data.setdefault("changesMade", 0)
    data.setdefault("warnings", [])
    return data


# ── Step 7: DUPLICATE_CHECK (per-component reconcile starts here) ─────────────
async def duplicate_check(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    title = _push_title(ctx, payload)
    auth = await _resolve_aep_auth(ctx)
    async with httpx.AsyncClient(timeout=60.0) as client:
        schemas = await aep_client.list_tenant_schemas(client, _headers(auth, content_type=False))

    match = next((s for s in schemas if s.get("title") == title), None)
    data["pushTitle"] = title
    data.setdefault("changesMade", 0)
    if match:
        data["aepSchemaId"] = match.get("$id") or match.get("meta:altId")
        data["schemaExisted"] = True
        data["skipToVerify"] = True  # schema exists — skip create/descriptor steps
        log.info("Schema %r already exists in registry (%s) — skipping to verify", title, data["aepSchemaId"])
    else:
        data["aepSchemaId"] = None
        data["schemaExisted"] = False
        data["skipToVerify"] = False
    return data


# ── Step 8: CREATE_SCHEMA (create, or PATCH missing fields if it exists) ──────
async def create_schema(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    title = data.get("pushTitle") or _push_title(ctx, payload)
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        if not data.get("aepSchemaId"):
            body = _build_create_body(payload, title)
            try:
                created = await aep_client.create_tenant_schema(client, headers, body)
                schema_id = created.get("$id") or created.get("meta:altId")
                if not schema_id:
                    raise ValueError(f"Create schema returned no $id: {created}")
                data["aepSchemaId"] = schema_id
                data["changesMade"] = data.get("changesMade", 0) + 1
                log.info("Created schema %r → %s", title, schema_id)
            except RuntimeError as exc:
                # XDM-1521: concurrent run already created this schema between our
                # DUPLICATE_CHECK and CREATE_SCHEMA — treat it as already existing.
                if "XDM-1521" in str(exc) or "title not unique" in str(exc).lower():
                    log.info("Schema %r created concurrently — fetching existing schema", title)
                    schemas = await aep_client.list_tenant_schemas(
                        client, _headers(auth, content_type=False)
                    )
                    match = next((s for s in schemas if s.get("title") == title), None)
                    if not match:
                        raise ValueError(f"Schema {title!r} reported as duplicate but not found in registry") from exc
                    data["aepSchemaId"] = match.get("$id") or match.get("meta:altId")
                    data["schemaExisted"] = True
                    data["skipToVerify"] = True
                    log.info("Resolved concurrent schema %r → %s", title, data["aepSchemaId"])
                else:
                    raise
        else:
            # Schema exists — add any columns present in the enriched JSON but
            # missing from the live schema (spec: final state == enriched JSON).
            schema_id = data["aepSchemaId"]
            existing = await aep_client.get_tenant_schema(client, headers, schema_id)
            existing_names = _existing_property_names(existing)
            existing_types = _existing_field_types(existing)
            warnings = data.setdefault("warnings", [])

            # Behavior is fixed at creation and cannot be changed — flag a mismatch
            # rather than silently diverging from the enriched JSON.
            existing_behavior = "time-series" if existing.get("meta:behaviorType") == "time-series" else "record"
            desired_behavior = payload.get("behavior", "record")
            if existing_behavior != desired_behavior:
                warnings.append(
                    f"Behavior mismatch: AEP schema is '{existing_behavior}' but enriched JSON wants "
                    f"'{desired_behavior}'. Behavior is fixed at creation and was left unchanged."
                )

            primary_key = set(payload.get("primaryKey") or [])
            desired_names = {f["name"] for f in payload.get("fields", []) if f.get("name")}
            log.info("Schema %s sync — existing fields: %s", schema_id, sorted(existing_names))
            log.info("Schema %s sync — desired fields:  %s", schema_id, sorted(desired_names))
            log.info("Schema %s sync — to remove: %s", schema_id,
                     sorted(existing_names - desired_names - primary_key))
            prop_ops: list[dict] = []   # add new fields
            req_ops: list[dict] = []    # add fields to required (separate call — idempotent)
            seen_req: set[str] = set()  # dedup within this batch
            for field in payload.get("fields", []):
                name = field.get("name")
                if not name:
                    continue
                if name not in existing_names:
                    prop_ops.append({
                        "op": "add",
                        "path": f"/definitions/customFields/properties/{name}",
                        "value": _field_to_property(field, name in primary_key),
                    })
                    if field.get("required") and name not in seen_req:
                        req_ops.append({"op": "add", "path": "/definitions/customFields/required/-", "value": name})
                        seen_req.add(name)
                else:
                    # Existing field: ensure PK/required fields are in required[].
                    if (field.get("required") or name in primary_key) and name not in seen_req:
                        req_ops.append({"op": "add", "path": "/definitions/customFields/required/-", "value": name})
                        seen_req.add(name)
                    # Type changed — remove the old field and re-add with the new type.
                    # PK fields are protected: removing them would break the schema.
                    desired_tf = (field.get("type"), field.get("format"))
                    existing_tf = existing_types.get(name)
                    if existing_tf and existing_tf[0] is not None and existing_tf != desired_tf:
                        if name in primary_key:
                            warnings.append(
                                f"Field '{name}' type mismatch (AEP: {existing_tf[0]!r}, desired: {desired_tf[0]!r}) "
                                f"— skipped because it is a primary key field."
                            )
                        else:
                            # Remove then re-add: only works on customFields properties.
                            cf_props = (
                                (existing.get("definitions", {}).get("customFields") or {})
                                .get("properties", {})
                            )
                            if name in cf_props:
                                prop_ops.append({
                                    "op": "remove",
                                    "path": f"/definitions/customFields/properties/{name}",
                                })
                                prop_ops.append({
                                    "op": "add",
                                    "path": f"/definitions/customFields/properties/{name}",
                                    "value": _field_to_property(field, False),
                                })
                                log.info("Schema %s field '%s': retyping %r → %r (remove + add)",
                                         schema_id, name, existing_tf, desired_tf)
                            else:
                                warnings.append(
                                    f"Field '{name}' type mismatch but not in customFields — left unchanged."
                                )

            # Remove fields that exist in AEP but are absent from the enriched JSON,
            # unless they are primary-key fields (AEP forbids removing those).
            # Note: xed-full+json flattens customFields into top-level properties,
            # so we cannot reliably distinguish customFields from inherited fields
            # via the GET response. We attempt removal for all non-PK removable
            # fields and ignore 422/400 errors for fields we don't own.
            removable = existing_names - desired_names - primary_key
            remove_ops: list[dict] = [
                {"op": "remove", "path": f"/definitions/customFields/properties/{name}"}
                for name in removable
            ]

            if prop_ops:
                await aep_client.patch_tenant_schema(client, headers, schema_id, prop_ops)
                data["changesMade"] = data.get("changesMade", 0) + len(prop_ops)
                data["fieldsChanged"] = data.get("fieldsChanged", 0) + len(prop_ops)
                log.info("Patched schema %s — added %d field(s)", schema_id, len(prop_ops))

            removed_count = 0
            deprecated_count = 0
            for op in remove_ops:
                field_name = op["path"].split("/")[-1]
                try:
                    await aep_client.patch_tenant_schema(client, headers, schema_id, [op])
                    removed_count += 1
                    log.info("Patched schema %s — removed field %s", schema_id, field_name)
                except RuntimeError as e:
                    msg = str(e)
                    if "400" in msg or "422" in msg or "not found" in msg.lower():
                        # Field removal is a breaking change — AEP blocks it once a schema
                        # has a linked dataset. Mark as deprecated instead so consumers
                        # can treat it as soft-deleted without breaking ingestion.
                        try:
                            dep_created = await _create_descriptor(client, headers, {
                                "@type": "xdm:descriptorDeprecated",
                                "xdm:sourceSchema": schema_id,
                                "xdm:sourceVersion": 1,
                                "xdm:sourceProperty": f"/{field_name}",
                            })
                            if dep_created:
                                deprecated_count += 1
                                log.info("Schema %s field %r deprecated (removal blocked by AEP — schema has linked data)", schema_id, field_name)
                                data.setdefault("warnings", []).append(
                                    f"Field '{field_name}' could not be removed (AEP blocks breaking changes on in-use schemas) — marked as deprecated instead."
                                )
                            else:
                                log.info("Schema %s field %r already deprecated", schema_id, field_name)
                        except RuntimeError:
                            log.info("Schema %s field %r could not be removed or deprecated — skipped", schema_id, field_name)
                    else:
                        raise
            if removed_count or deprecated_count:
                data["changesMade"] = data.get("changesMade", 0) + removed_count + deprecated_count
                data["fieldsChanged"] = data.get("fieldsChanged", 0) + removed_count + deprecated_count

            if not prop_ops and not removed_count:
                log.info("Schema %s fields already match enriched JSON", schema_id)

            for req_op in req_ops:
                field_name = req_op["value"]
                try:
                    await aep_client.patch_tenant_schema(client, headers, schema_id, [req_op])
                    log.info("Patched schema %s — added '%s' to required[]", schema_id, field_name)
                except RuntimeError as e:
                    msg = str(e)
                    if "uniqueItems" in msg or "is not changed" in msg or "XDM-1600" in msg:
                        log.info("Schema %s field '%s' already in required[] — skipped", schema_id, field_name)
                    else:
                        raise

            if warnings:
                log.warning("Schema %s reconcile warnings: %s", schema_id, "; ".join(warnings))
    return data


# ── Step 9: PRIMARY_KEY_DESCRIPTOR ───────────────────────────────────────────
async def primary_key_descriptor(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    primary_key = payload.get("primaryKey") or []
    if not primary_key:
        log.warning("No primary key for %s — skipping primary-key descriptor", ctx.get("schema_name"))
        return data
    schema_id = data["aepSchemaId"]
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        created = await _create_descriptor(client, headers, {
            "@type": "xdm:descriptorPrimaryKey",
            "xdm:sourceSchema": schema_id,
            "xdm:sourceVersion": 1,
            "xdm:sourceProperty": [f"/{k}" for k in primary_key],
        })
    if created:
        data["changesMade"] = data.get("changesMade", 0) + 1
    return data


# ── Step 10: VERSION_DESCRIPTOR ──────────────────────────────────────────────
async def version_descriptor(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    version_field = payload.get("versionField")
    if not version_field:
        log.warning("No version field for %s — skipping version descriptor", ctx.get("schema_name"))
        return data
    schema_id = data["aepSchemaId"]
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        created = await _create_descriptor(client, headers, {
            "@type": "xdm:descriptorVersion",
            "xdm:sourceSchema": schema_id,
            "xdm:sourceVersion": 1,
            "xdm:sourceProperty": f"/{version_field}",
        })
    if created:
        data["changesMade"] = data.get("changesMade", 0) + 1
    return data


# ── Step 11: TIMESTAMP_DESCRIPTOR (time-series only) ─────────────────────────
async def timestamp_descriptor(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    if payload.get("behavior") != "time-series":
        return data  # spec §7: record schemas skip this
    timestamp_field = payload.get("timestampField")
    if not timestamp_field:
        log.warning("Time-series schema %s has no timestamp field — skipping", ctx.get("schema_name"))
        return data
    schema_id = data["aepSchemaId"]
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        created = await _create_descriptor(client, headers, {
            "@type": "xdm:descriptorTimestamp",
            "xdm:sourceSchema": schema_id,
            "xdm:sourceVersion": 1,
            "xdm:sourceProperty": f"/{timestamp_field}",
        })
    if created:
        data["changesMade"] = data.get("changesMade", 0) + 1
    return data


# ── Step 12: IDENTITY_DESCRIPTOR (optional — true person keys only) ──────────
async def identity_descriptor(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    identity_field = payload.get("identityField")
    if not identity_field:
        return data
    namespace = _resolve_person_namespace(identity_field)
    if not namespace:
        log.info("Identity field %r is not a person key — skipping identity descriptor", identity_field)
        return data
    # AEP only allows an identity descriptor to point at a string field.
    field_type = next((f.get("type") for f in payload.get("fields", []) if f.get("name") == identity_field), None)
    if field_type != "string":
        log.info("Identity field %r is type %r (not string) — skipping identity descriptor", identity_field, field_type)
        return data
    schema_id = data["aepSchemaId"]
    source_property = f"/{identity_field}"
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Ensure the namespace exists on the Identity Service (region host).
        namespaces = await aep_client.list_identity_namespaces(client, _headers(auth, content_type=False))
        if not any((ns.get("code") or "").lower() == namespace.lower() for ns in namespaces):
            id_type = _NAMESPACE_CONFIG.get("idTypeByNamespace", {}).get(
                namespace, _NAMESPACE_CONFIG.get("defaultIdType", "CROSS_DEVICE")
            )
            await aep_client.create_identity_namespace(client, headers, {
                "name": namespace,
                "code": namespace,
                "description": f"Namespace migrated from Adobe Campaign for {namespace}.",
                "idType": id_type,
            })
            log.info("Created identity namespace %s (idType=%s)", namespace, id_type)

        created = await _create_descriptor(client, headers, {
            "@type": "xdm:descriptorIdentity",
            "xdm:sourceSchema": schema_id,
            "xdm:sourceVersion": 1,
            "xdm:sourceProperty": source_property,
            "xdm:namespace": namespace,
            "xdm:property": "xdm:code",
        })
        if created:
            data["changesMade"] = data.get("changesMade", 0) + 1
    return data


# ── Step 13: RELATIONSHIP_DESCRIPTORS (PASS 2 — global reconcile) ────────────
async def _desired_links_touching(ctx: dict, schema_name: str) -> list[dict]:
    """
    Every desired relationship (from converted_schemas.enriched_json) where this
    schema is the source OR the target — so a deferred link A→B is created on
    whichever run is the first where both A and B exist. Reads existing rows
    only; no new persistence.
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ConvertedSchema)
                .where(ConvertedSchema.login_id == ctx["login_id"])
                .order_by(ConvertedSchema.created_at.desc())
            )
        ).scalars().all()

    links: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not row.enriched_json or row.schema_name in seen:
            continue
        seen.add(row.schema_name)  # keep only the latest enriched row per schema_name
        try:
            payload = json.loads(row.enriched_json)
        except (json.JSONDecodeError, TypeError):
            continue
        for rel in payload.get("relationships", []) or []:
            target = rel.get("targetSchema")
            if not target or not rel.get("foreignKey"):
                continue
            if row.schema_name != schema_name and target != schema_name:
                continue  # link doesn't touch this schema
            links.append({
                "source_schema": row.schema_name,
                "foreign_key": rel.get("foreignKey"),
                "target_schema": target,
                "target_key": rel.get("targetKey"),
                "cardinality": rel.get("cardinality"),
            })
    return links


async def relationship_descriptors(ctx: dict, data: dict) -> dict:
    schema_name = ctx.get("schema_name")
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    headers_get = _headers(auth, content_type=False)
    created = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        schemas = await aep_client.list_tenant_schemas(client, headers_get)
        title_to_id = {
            s.get("title"): (s.get("$id") or s.get("meta:altId")) for s in schemas if s.get("title")
        }
        existing = await aep_client.list_tenant_descriptors(client, headers_get)

        for link in await _desired_links_touching(ctx, schema_name):
            source_id = title_to_id.get(link["source_schema"])
            dest_id = title_to_id.get(link["target_schema"])
            source_property = _rel_source_property(link["foreign_key"])
            if not source_id or not dest_id:
                log.info("Deferring relationship %s → %s (target not in registry yet)",
                         link["source_schema"], link["target_schema"])
                continue
            if not source_property:
                log.warning("Skipping relationship %s → %s: foreign key %r is not root-level",
                            link["source_schema"], link["target_schema"], link["foreign_key"])
                continue
            if _has_relationship(existing, source_id, source_property, dest_id):
                continue
            body = {
                "@type": "xdm:descriptorRelationship",
                "xdm:sourceSchema": source_id,
                "xdm:sourceVersion": 1,
                "xdm:sourceProperty": source_property,
                "xdm:destinationSchema": dest_id,
                "xdm:destinationVersion": 1,
                "xdm:cardinality": _normalize_cardinality(link.get("cardinality")),
            }
            if link.get("target_key"):
                body["xdm:destinationProperty"] = f"/{str(link['target_key']).lstrip('/')}"
            if await _create_descriptor(client, headers, body):
                existing.append(body)  # prevent a duplicate within this same pass
                created += 1
                log.info("Created relationship %s %s → %s", link["source_schema"], source_property, link["target_schema"])

    data["relationshipsCreated"] = data.get("relationshipsCreated", 0) + created
    return data


def _dataset_name(schema_name: str) -> str:
    """hdbk:orderHistory → HdbkOrderHistory (PascalCase, no colon)."""
    parts = schema_name.split(":", 1)
    if len(parts) == 2:
        ns, name = parts
        return (ns[0].upper() + ns[1:]) + (name[0].upper() + name[1:])
    return schema_name[0].upper() + schema_name[1:]


def _pick_version_field_fallback(payload: dict) -> str | None:
    """Find any field eligible for a version descriptor.

    Tries the normal logic first (non-PK datetime/numeric), then falls back to
    PK datetime fields — needed for time-series schemas where the only datetime
    field is also the primary key. AEP rejects dataset creation without one.
    """
    fields = payload.get("fields", [])
    xdm_types = {f["name"]: f.get("type") for f in fields if f.get("name")}
    primary_key = set(payload.get("primaryKey") or [])

    # Prefer normal (non-PK) version field
    normal = _compute_version_field(
        [{"name": n} for n in xdm_types], list(primary_key), xdm_types
    )
    if normal:
        return normal

    # Last resort: use a PK datetime field (common on time-series schemas)
    _NUMERIC = {"integer", "number"}
    for field in fields:
        name = field.get("name")
        t = field.get("type")
        fmt = field.get("format", "")
        if not name:
            continue
        if t in _NUMERIC or (t == "string" and fmt == "date-time"):
            return name

    return None


# ── Step 14: CREATE_DATASET ──────────────────────────────────────────────────
async def create_dataset(ctx: dict, data: dict) -> dict:
    """Create an AEP Catalog dataset backed by the just-pushed schema.
    Idempotent: if data already carries aepDatasetId (from a resume snapshot), skip."""
    if data.get("aepDatasetId"):
        log.info("Dataset already created for %s (%s) — skipping", ctx.get("schema_name"), data["aepDatasetId"])
        return data

    schema_id = data.get("aepSchemaId")
    if not schema_id:
        raise ValueError("aepSchemaId not set — cannot create dataset without a schema $id")

    payload = data.get("ajoPayload", {})
    schema_name = ctx.get("schema_name", "")
    dataset_name = _dataset_name(schema_name) if schema_name else (data.get("pushTitle") or _push_title(ctx, payload))
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    headers_get = _headers(auth, content_type=False)
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Check if a dataset already exists for this schema.
        existing_datasets = await aep_client.list_datasets_for_schema(client, headers_get, schema_id)
        if existing_datasets:
            existing_id = existing_datasets[0].get("id") or existing_datasets[0].get("@/dataSets")
            data["aepDatasetId"] = existing_id
            data["datasetCreated"] = False
            log.info("Dataset already exists for schema %s (%s) — skipping creation", schema_id, existing_id)
            return data

        # AEP requires an adhoc-v2 schema to have a version descriptor before a
        # dataset can be created. Ensure one exists; create it if missing.
        existing_descriptors = await _fetch_descriptors(client, headers_get, schema_id)
        has_version = _has_descriptor(existing_descriptors, schema_id, "xdm:descriptorVersion")
        if not has_version:
            version_field = _pick_version_field_fallback(payload)
            if version_field:
                created = await _create_descriptor(client, headers, {
                    "@type": "xdm:descriptorVersion",
                    "xdm:sourceSchema": schema_id,
                    "xdm:sourceVersion": 1,
                    "xdm:sourceProperty": f"/{version_field}",
                })
                if created:
                    has_version = True
                    data["changesMade"] = data.get("changesMade", 0) + 1
                    log.info("Added missing version descriptor on %r (field=%s) before dataset create", dataset_name, version_field)
                else:
                    # Descriptor already exists (returned False = already present)
                    has_version = True
            else:
                log.warning("No eligible version field for %r — skipping dataset creation", dataset_name)

        if not has_version:
            data["datasetCreated"] = False
            data["warnings"] = data.get("warnings", []) + [
                f"Dataset not created: schema requires a version descriptor but no eligible field exists "
                f"(all datetime/numeric fields are primary keys)."
            ]
            return data

        dataset_id = await aep_client.create_dataset(client, headers, dataset_name, schema_id)

    data["aepDatasetId"] = dataset_id
    data["datasetCreated"] = True
    data["changesMade"] = data.get("changesMade", 0) + 1
    log.info("Created dataset %s (%s) for schema %s", dataset_name, dataset_id, schema_id)
    return data


# ── Step 15: VERIFY ──────────────────────────────────────────────────────────
async def verify(ctx: dict, data: dict) -> dict:
    payload = data["ajoPayload"]
    title = data.get("pushTitle") or _push_title(ctx, payload)
    auth = await _resolve_aep_auth(ctx)
    headers_get = _headers(auth, content_type=False)
    async with httpx.AsyncClient(timeout=60.0) as client:
        schemas = await aep_client.list_tenant_schemas(client, headers_get)
        match = next((s for s in schemas if s.get("title") == title), None)
        if not match:
            raise ValueError(f"Verification failed — schema {title!r} not found in registry")
        schema_id = match.get("$id") or match.get("meta:altId")
        data["aepSchemaId"] = schema_id
        mine = _descriptors_for(await aep_client.list_tenant_descriptors(client, headers_get), schema_id)

    types = {d.get("@type") for d in mine}
    warnings = data.get("warnings", [])
    # Note: GET /tenant/descriptors does not list version/timestamp descriptors, so
    # we don't assert them here — their create step is authoritative.
    data["verification"] = {
        "schema": True,
        "primaryKey": "xdm:descriptorPrimaryKey" in types,
        "relationships": sum(1 for d in mine if d.get("@type") == "xdm:descriptorRelationship"),
        "datasetId": data.get("aepDatasetId"),
        "warnings": len(warnings),
    }
    if warnings:
        log.warning("Schema %s completed with %d warning(s): %s", title, len(warnings), "; ".join(warnings))
    log.info("Verified %s: %s", title, data["verification"])
    return data


# ── OC background poller ─────────────────────────────────────────────────────
async def _poll_oc_job(job_id: str, item_id: str, ctx: dict) -> None:
    """Detached asyncio task: poll OC job until terminal state, then write to DB."""
    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth, content_type=False)
    max_attempts = 24
    for attempt in range(max_attempts):
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                result = await aep_client.get_oc_enablement_job_status(client, headers, job_id)
            status = (result.get("status") or "PENDING").upper()
            if status not in ("PENDING", "IN_PROGRESS"):
                final = "ENABLED" if status in ("COMPLETED", "SUCCESS", "ENABLED") else "FAILED"
                from pipeline.runner import _update_item  # local import to avoid circular
                await _update_item(item_id, "COMPLETED", "ENABLE_OC", 17, oc_status=final)
                log.info("OC job %s for item %s finished: %s", job_id, item_id, final)
                return
        except Exception as exc:
            log.warning("OC job poll attempt %d failed for %s: %s", attempt + 1, job_id, exc)
    log.warning("OC job %s for item %s timed out after %ds — leaving status PENDING", job_id, item_id, max_attempts * 5)


# ── Step 16: VALIDATE_OC ─────────────────────────────────────────────────────
async def validate_oc(ctx: dict, data: dict) -> dict:
    """Call OC Modeler to check whether this schema's dataset is OC-eligible."""
    dataset_id = data.get("aepDatasetId")
    if not dataset_id:
        log.warning("VALIDATE_OC: no dataset ID available for %s — skipping", ctx.get("schema_name"))
        data["ocSupported"] = False
        data["ocNotSupportedReason"] = "No dataset associated with this schema"
        return data

    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth, content_type=False)
    async with httpx.AsyncClient(timeout=60.0) as client:
        result = await aep_client.validate_oc_extension(client, headers, dataset_id)

    supported = bool(result.get("supported", False))
    reason = result.get("reason") or result.get("message") or ""
    data["ocSupported"] = supported
    data["ocNotSupportedReason"] = reason if not supported else None
    log.info("OC validation for %s: supported=%s reason=%r", ctx.get("schema_name"), supported, reason)
    return data


# ── Step 17: ENABLE_OC ───────────────────────────────────────────────────────
async def enable_oc(ctx: dict, data: dict) -> dict:
    """Fire OC enablement job; spawn background poller to track result."""
    if not data.get("ocSupported"):
        log.info("OC enablement skipped for %s (not eligible)", ctx.get("schema_name"))
        return data

    dataset_id = data.get("aepDatasetId")
    if not dataset_id:
        log.warning("ENABLE_OC: no dataset ID for %s — skipping", ctx.get("schema_name"))
        return data

    auth = await _resolve_aep_auth(ctx)
    headers = _headers(auth)
    async with httpx.AsyncClient(timeout=60.0) as client:
        result = await aep_client.enable_oc_extension(client, headers, dataset_id)

    job_id = result.get("jobId") or result.get("id") or ""
    data["ocJobId"] = job_id
    log.info("OC enablement job %s fired for %s", job_id, ctx.get("schema_name"))
    return data


