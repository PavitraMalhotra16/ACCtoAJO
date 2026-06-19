import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import AsyncSessionLocal, ConvertedSchema, DestinationConnection, TenantConfig
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

ACC_TO_XDM: dict[str, dict] = {
    "string":   {"type": "string"},
    "memo":     {"type": "string"},
    "uuid":     {"type": "string"},
    "int32":    {"type": "integer"},
    "int64":    {"type": "integer"},
    "short":    {"type": "integer"},
    "byte":     {"type": "integer"},
    "long":     {"type": "integer"},
    "double":   {"type": "number"},
    "float":    {"type": "number"},
    "boolean":  {"type": "boolean"},
    "datetime": {"type": "string", "format": "date-time"},
    "date":     {"type": "string", "format": "date"},
}

_TIME_SERIES_KEYWORDS = {"log", "tracking", "history", "broadlog", "event", "histo", "delivery", "statistics"}
_VERSION_FIELD_PATTERNS = {"lastmodified", "tslastmodified", "lastupdate", "modifieddate", "updatedat", "dtmodified", "tsmodification", "tschanged", "modified"}
_TIMESTAMP_FIELD_PATTERNS = {"tsevent", "timestamp", "eventdate", "logdate", "eventts", "eventtime", "tscreated"}


def _infer_behavior(source_name: str, root_name: str) -> str:
    combined = (source_name + root_name).lower()
    return "time-series" if any(kw in combined for kw in _TIME_SERIES_KEYWORDS) else "record"


# Rule 3: well-known field names → standard AEP identity namespaces
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

# Business anchor fields → isPrimary=true
_RULE3_PRIMARY = {"customerid", "userid"}

# Stitching/secondary fields → isPrimary=false
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


def _find_version_field(attributes: list[dict]) -> str | None:
    for attr in attributes:
        if any(p in (attr.get("name") or "").lower() for p in _VERSION_FIELD_PATTERNS):
            return attr["name"]
    for attr in attributes:
        if (attr.get("type") or "").lower() in ("datetime", "date"):
            return attr["name"]
    return None


def _find_timestamp_field(attributes: list[dict]) -> str | None:
    for attr in attributes:
        if any(p in (attr.get("name") or "").lower() for p in _TIMESTAMP_FIELD_PATTERNS):
            return attr["name"]
    return None


def _build_fields(attributes: list[dict], xdm_types: dict) -> list[dict]:
    fields = []
    for attr in attributes:
        name = attr.get("name")
        if not name:
            continue
        xdm = xdm_types.get(name, {"type": "string"})
        field: dict = {"name": name, "title": attr.get("label") or name, "type": xdm.get("type", "string")}
        if "format" in xdm:
            field["format"] = xdm["format"]
        fields.append(field)
    return fields


def _build_relationships(links_and_joins: list[dict]) -> list[dict]:
    result = []
    for link in links_and_joins:
        if not link.get("targetSchema"):
            continue
        join = link.get("join", {})
        result.append({
            "name": link.get("name"),
            "sourceField": join.get("sourceField"),
            "targetSchema": link["targetSchema"],
            "targetField": join.get("destinationField"),
            "cardinality": link.get("cardinality"),
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
    xdm_types: dict[str, dict] = {}
    for attr in data.get("attributes", []):
        name = attr.get("name")
        if not name:
            continue
        acc_type = (attr.get("type") or "string").lower()
        xdm_types[name] = ACC_TO_XDM.get(acc_type, {"type": "string"})
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
            data["identityDecision"] = {
                "status": "resolved",
                "fieldPath": f"/{fields[0]}",
                "isPrimary": True,
                "reason": "Explicit primary key field — treated as primary identity",
            }
            return data

    unique_keys = keys.get("uniqueKeys", [])
    if unique_keys:
        fields = unique_keys[0].get("fields", [])
        field = fields[0] if fields else "id"
        data["identityDecision"] = {
            "status": "resolved",
            "fieldPath": f"/{field}",
            "isPrimary": True,
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


async def fetch_tenant_id(ctx: dict, data: dict) -> dict:
    org_id = ctx["org_id"]

    async with AsyncSessionLocal() as db:
        cached_result = await db.execute(
            select(TenantConfig).where(TenantConfig.org_id == org_id)
        )
        cached = cached_result.scalar_one_or_none()

        if cached and (datetime.now(timezone.utc) - cached.fetched_at) < timedelta(hours=24):
            log.info("Tenant ID cache hit for org %s", org_id)
            data["tenantId"] = cached.tenant_id
            return data

        dest_result = await db.execute(
            select(DestinationConnection).where(DestinationConnection.org_id == org_id)
        )
        dest = dest_result.scalar_one_or_none()
        if not dest or not dest.encrypted_access_token:
            raise ValueError(f"No AJO credentials found for org {org_id}")

        access_token = await get_valid_access_token(dest, db)
        client_id = dest.client_id or ""
        if not client_id:
            raise ValueError(f"No client_id found for org {org_id}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://platform.adobe.io/data/foundation/schemaregistry/stats",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "x-api-key": client_id,
                    "x-gw-ims-org-id": org_id,
                    "x-sandbox-name": (dest.sandbox_name or "prod").strip(),
                },
            )

        if resp.status_code != 200:
            raise ValueError(f"AEP tenant API returned {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        tenant_id = payload.get("tenantId")
        if not tenant_id:
            raise ValueError(f"tenantId not found in AEP stats response: {str(payload)[:200]}")

        # Upsert — safe against concurrent schemas racing to insert the same org_id
        stmt = pg_insert(TenantConfig).values(
            org_id=org_id,
            tenant_id=tenant_id,
            sandbox_id=(dest.sandbox_name or "").strip(),
            sandbox_type="production",
            fetched_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["org_id"],
            set_={"tenant_id": tenant_id, "fetched_at": datetime.now(timezone.utc)},
        )
        await db.execute(stmt)
        await db.commit()

    data["tenantId"] = tenant_id
    log.info("Fetched tenant ID %r for org %s", tenant_id, org_id)
    return data


async def build_payload(ctx: dict, data: dict) -> dict:
    source = data.get("source", {})
    schema_meta = data.get("schema", {})
    root = data.get("rootElement", {})
    attributes = data.get("attributes", [])
    xdm_types = data.get("xdmTypes", {})
    identity = data.get("identityDecision", {})
    links_and_joins = data.get("linksAndJoins", [])

    source_name = source.get("name") or source.get("fullName", "")
    root_name = root.get("name") or ""
    behavior = _infer_behavior(source_name, root_name)

    field_path = identity.get("fieldPath")
    primary_key = field_path.lstrip("/") if field_path else None

    version_field = _find_version_field(attributes)
    timestamp_field = _find_timestamp_field(attributes) if behavior == "time-series" else None

    payload: dict = {
        "title": schema_meta.get("label") or root.get("label") or source_name,
        "description": schema_meta.get("description") or "",
        "behavior": behavior,
        "primaryKey": primary_key,
        "fields": _build_fields(attributes, xdm_types),
        "relationships": _build_relationships(links_and_joins),
    }
    if version_field:
        payload["versionField"] = version_field
    if timestamp_field:
        payload["timestampField"] = timestamp_field

    data["ajoPayload"] = payload
    log.info("Built payload for %s: behavior=%s primaryKey=%s", source_name, behavior, primary_key)
    return data


async def call_schema_api_stub(ctx: dict, data: dict) -> dict:
    return data


async def call_identity_descriptor_stub(ctx: dict, data: dict) -> dict:
    return data


async def verify_stub(ctx: dict, data: dict) -> dict:
    return data
