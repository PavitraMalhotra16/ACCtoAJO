import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError

from db import AsyncSessionLocal, ConvertedSchema, DestinationConnection, ensure_schema_columns
from core.security import decrypt, encrypt

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "AdobeID,openid,read_organizations,adobeio_api,additional_details.projectedProductContext"


async def get_valid_access_token(dest: DestinationConnection, db) -> str:
    """Return a valid access token, refreshing via OAuth S2S if expired or close to expiry."""
    now = datetime.now(timezone.utc)
    buffer = timedelta(minutes=5)

    if dest.token_expires_at and dest.token_expires_at > now + buffer:
        return decrypt(dest.encrypted_access_token)

    # Token expired or missing — refresh using stored client_id:client_secret
    if not dest.encrypted_credentials:
        raise ValueError("No OAuth credentials stored — reconnect AJO")

    raw = decrypt(dest.encrypted_credentials)
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
    auto_pk = keys.get("autoPk", {})
    primary_keys = keys.get("primaryKeys", [])
    composite_keys = keys.get("compositeKeys", [])

    if auto_pk.get("enabled"):
        return "record"

    if composite_keys:
        return "time-series"

    if primary_keys:
        fields = primary_keys[0].get("fields", [])
        if len(fields) > 1:
            return "time-series"

    has_any_pk = bool(primary_keys) or bool(composite_keys) or auto_pk.get("enabled")
    if not has_any_pk:
        return "time-series"

    return _infer_behavior(source_name, root_name)


def _compute_version_field(attributes: list[dict], primary_key: list[str], xdm_types: dict) -> str | None:
    """Version field must be datetime or numeric, and must not be in primaryKey."""
    _NUMERIC = {"integer", "long", "number"}
    _DATETIME = {"datetime", "date"}
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

    # A. title — always prefixed with namespace so nms:auditHistory ≠ hdbk:auditHistory
    base_title = (
        schema_meta.get("label")
        or root.get("label")
        or root.get("sqlTable")
        or source.get("fullName")
        or source_name
        or schema_name
    )
    title = f"{namespace}:{base_title}" if namespace else base_title

    # B. description
    description = (
        schema_meta.get("description")
        or schema_meta.get("labelSingular")
        or root.get("label")
        or f"Schema for {title}"
    )

    # C. behavior (key-structure first, keyword fallback)
    behavior = _compute_behavior(keys, source_name, root_name)

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


