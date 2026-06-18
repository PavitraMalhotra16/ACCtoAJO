import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import settings
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
    "email":       "Email",
    "emailaddress": "Email",
    "externid":    "ECID",
    "externalid":  "ECID",
    "ecid":        "ECID",
    "customerid":  "CustomerID",
    "userid":      "UserID",
    "phonenumber": "Phone",
    "phone":       "Phone",
    "mobilenumber": "Phone",
}

_RULE3_NAMES = {"email", "emailaddress", "externalid", "externid", "ecid", "customerid", "userid", "phonenumber", "phone", "mobilenumber"}


def _auto_map_namespace(field_name: str) -> str | None:
    """Return a standard AEP namespace if field_name is a known identity field, else None."""
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
    attributes = data.get("attributes", [])
    auto_pk = keys.get("autoPk", {})

    # Rule 1a: auto-generated surrogate key
    if auto_pk.get("enabled"):
        field = auto_pk.get("field") or "id"
        data["identityDecision"] = {
            "status": "resolved",
            "fieldPath": f"/{field}",
            "isPrimary": False,
            "reason": "Auto-generated surrogate key — identity but not primary identity",
        }
        return data

    # Rule 1b: explicit primary key
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

    # Rule 2: first unique key (string or int64)
    unique_keys = keys.get("uniqueKeys", [])
    if unique_keys:
        fields = unique_keys[0].get("fields", [])
        field = fields[0] if fields else None
        if field:
            data["identityDecision"] = {
                "status": "resolved",
                "fieldPath": f"/{field}",
                "isPrimary": True,
                "reason": "No explicit PK — first unique key used as primary identity",
            }
            return data

    # Rule 3: well-known field name pattern matching
    for attr in attributes:
        name = (attr.get("name") or "").lower()
        if name in _RULE3_NAMES:
            original_name = attr["name"]
            namespace = _auto_map_namespace(original_name)
            data["identityDecision"] = {
                "status": "resolved",
                "fieldPath": f"/{original_name}",
                "isPrimary": True,
                "namespace": namespace,
                "reason": f"Field name {original_name!r} matched known identity pattern — auto-mapped to {namespace}",
            }
            log.info("Rule 3 identity match: %s → namespace %s", original_name, namespace)
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


async def make_enriched_json(ctx: dict, data: dict) -> dict:
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
    # Use the namespace already resolved by Rule 3 if present, else derive from field name
    identity_namespace = identity.get("namespace") or (_derive_namespace(primary_key) if primary_key else None)

    version_field = _find_version_field(attributes)
    timestamp_field = _find_timestamp_field(attributes) if behavior == "time-series" else None

    payload: dict = {
        "title": schema_meta.get("label") or root.get("label") or source_name,
        "description": schema_meta.get("description") or "",
        "behavior": behavior,
        "primaryKey": primary_key,
        "identityNamespace": identity_namespace,
        "identityUnresolved": identity.get("status") == "unresolved",
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


# ──────────────────────────────────────────────────────────────────────────────
# AEP push helpers (steps 6–12)
# ──────────────────────────────────────────────────────────────────────────────

def _schema_registry_base() -> str:
    return f"{settings.aep_schema_registry_host}/data/foundation/schemaregistry"


async def _aep_auth(org_id: str) -> dict:
    """Resolve a valid access token + the header values for AEP API calls."""
    async with AsyncSessionLocal() as db:
        dest_result = await db.execute(
            select(DestinationConnection).where(DestinationConnection.org_id == org_id)
        )
        dest = dest_result.scalar_one_or_none()
        if not dest or not dest.encrypted_access_token:
            raise ValueError(f"No AJO credentials found for org {org_id}")
        if not dest.client_id:
            raise ValueError(f"No client_id (API key) found for org {org_id}")
        token = await get_valid_access_token(dest, db)
        return {
            "token": token,
            "client_id": dest.client_id,
            "org_id": org_id,
            "sandbox": (dest.sandbox_name or "prod").strip(),
        }


def _sr_headers(auth: dict, *, content_type: bool = False, accept: str | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {auth['token']}",
        "x-api-key": auth["client_id"],
        "x-gw-ims-org-id": auth["org_id"],
        "x-sandbox-name": auth["sandbox"],
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    if accept:
        headers["Accept"] = accept
    return headers


def _class_ref(behavior: str) -> str:
    if behavior == "time-series":
        return "https://ns.adobe.com/xdm/context/experienceevent"
    return "https://ns.adobe.com/xdm/context/profile"


def _coerce_input_json(value) -> dict:
    """Defensive parse — input is normally JSON but may arrive as a plain string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Input JSON is not valid JSON: {exc}") from exc
    raise ValueError("Input JSON is missing or not an object")


async def _get_input_json(ctx: dict, data: dict) -> dict:
    """Read the enriched input JSON — from in-memory payload, else the DB column."""
    payload = data.get("ajoPayload")
    if isinstance(payload, dict):
        return payload
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ConvertedSchema).where(ConvertedSchema.id == ctx["converted_schema_id"])
        )
        cs = result.scalar_one()
    if not cs.enriched_json:
        raise ValueError("No enriched input JSON available — MAKE_ENRICHED_JSON must run first")
    return _coerce_input_json(cs.enriched_json)


def _description(input_json: dict, schema_name: str) -> str:
    desc = (input_json.get("description") or "").strip()
    return desc or f"this table is about {schema_name}"


def _tenant_key(tenant_id: str) -> str:
    """Custom-fields namespace key — always exactly one leading underscore,
    whether or not the stored tenant ID already includes it."""
    return "_" + tenant_id.lstrip("_")


def _source_property_path(tenant_id: str, primary_key: str) -> str:
    return f"/{_tenant_key(tenant_id)}/{primary_key}"


def _xdm_field(field: dict) -> dict:
    name = field.get("name")
    title = field.get("title") or name
    prop: dict = {"title": title, "type": field.get("type", "string")}
    if field.get("format"):
        prop["format"] = field["format"]
    prop["description"] = field.get("description") or f"{title} field migrated from Adobe Campaign."
    return prop


def _listing_results(body) -> list:
    if isinstance(body, dict):
        return body.get("results", [])
    return body if isinstance(body, list) else []


# ──────────────────────────────────────────────────────────────────────────────
# Step 6: create the schema (class only) → schema $id
# ──────────────────────────────────────────────────────────────────────────────

async def call_schema_api(ctx: dict, data: dict) -> dict:
    input_json = await _get_input_json(ctx, data)
    title = input_json.get("title") or ctx["schema_name"]
    description = _description(input_json, ctx["schema_name"])
    behavior = input_json.get("behavior", "record")
    class_ref = _class_ref(behavior)
    data["schemaClassRef"] = class_ref

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Idempotency: reuse an existing schema with the same title
        existing = await client.get(
            f"{base}/tenant/schemas",
            headers=_sr_headers(auth, accept="application/vnd.adobe.xed-id+json"),
        )
        if existing.status_code == 200:
            for item in _listing_results(existing.json()):
                if item.get("title") == title:
                    data["schemaId"] = item["$id"]
                    data["schemaTitle"] = title
                    log.info("Schema %r already exists — reusing %s", title, item["$id"])
                    return data

        resp = await client.post(
            f"{base}/tenant/schemas",
            headers=_sr_headers(auth, content_type=True),
            json={
                "type": "object",
                "title": title,
                "description": description,
                "allOf": [{"$ref": class_ref}],
            },
        )

    if resp.status_code not in (200, 201):
        raise ValueError(f"Create schema failed ({resp.status_code}): {resp.text[:300]}")
    schema_id = resp.json().get("$id")
    if not schema_id:
        raise ValueError("Schema create response missing $id")
    data["schemaId"] = schema_id
    data["schemaTitle"] = title
    log.info("Created schema %r → %s", title, schema_id)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 7: create the custom field group (fields under _{TENANT_ID}) → fieldgroup $id
# ──────────────────────────────────────────────────────────────────────────────

async def call_fieldgroup_api(ctx: dict, data: dict) -> dict:
    input_json = await _get_input_json(ctx, data)
    tenant_id = data.get("tenantId")
    if not tenant_id:
        raise ValueError("tenantId missing — FETCH_TENANT_ID must run first")

    class_ref = data.get("schemaClassRef") or _class_ref(input_json.get("behavior", "record"))
    title = f"{input_json.get('title') or ctx['schema_name']} Fields"
    fields = input_json.get("fields", [])
    tenant_key = _tenant_key(tenant_id)
    primary_key = input_json.get("primaryKey")

    # AEP requires identity descriptor fields to be type string.
    # Force the primary key field to string so the descriptor call succeeds.
    def _xdm_field_for(f: dict) -> dict:
        built = _xdm_field(f)
        if f.get("name") == primary_key and built.get("type") != "string":
            built["type"] = "string"
            built.pop("format", None)
            log.info("Coerced primary key field %r to string for AEP identity descriptor", f["name"])
        return built

    properties = {f["name"]: _xdm_field_for(f) for f in fields if f.get("name")}

    payload = {
        "type": "object",
        "title": title,
        "description": _description(input_json, ctx["schema_name"]),
        "meta:intendedToExtend": [class_ref],
        "definitions": {
            "campaignFields": {
                "properties": {
                    tenant_key: {"type": "object", "properties": properties}
                }
            }
        },
        "allOf": [{"$ref": "#/definitions/campaignFields"}],
    }

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()

    async with httpx.AsyncClient(timeout=30.0) as client:
        existing = await client.get(
            f"{base}/tenant/fieldgroups",
            headers=_sr_headers(auth, accept="application/vnd.adobe.xed-id+json"),
        )
        if existing.status_code == 200:
            for item in _listing_results(existing.json()):
                if item.get("title") == title:
                    data["fieldGroupId"] = item["$id"]
                    log.info("Field group %r already exists — reusing %s", title, item["$id"])
                    return data

        resp = await client.post(
            f"{base}/tenant/fieldgroups",
            headers=_sr_headers(auth, content_type=True),
            json=payload,
        )

    if resp.status_code not in (200, 201):
        raise ValueError(f"Create field group failed ({resp.status_code}): {resp.text[:300]}")
    fg_id = resp.json().get("$id")
    if not fg_id:
        raise ValueError("Field group create response missing $id")
    data["fieldGroupId"] = fg_id
    log.info("Created field group %r → %s", title, fg_id)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 8: attach the field group to the schema (schema $id is URL-encoded in path)
# ──────────────────────────────────────────────────────────────────────────────

async def attach_fieldgroup(ctx: dict, data: dict) -> dict:
    schema_id = data.get("schemaId")
    fg_id = data.get("fieldGroupId")
    if not schema_id or not fg_id:
        raise ValueError("schemaId or fieldGroupId missing — steps 6 and 7 must run first")

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()
    encoded = quote(schema_id, safe="")

    async with httpx.AsyncClient(timeout=30.0) as client:
        current = await client.get(
            f"{base}/tenant/schemas/{encoded}",
            headers=_sr_headers(auth, accept="application/vnd.adobe.xed+json; version=1"),
        )
        if current.status_code == 200:
            allof = current.json().get("allOf", [])
            if any(isinstance(r, dict) and r.get("$ref") == fg_id for r in allof):
                log.info("Field group already attached to %s", schema_id)
                return data

        resp = await client.patch(
            f"{base}/tenant/schemas/{encoded}",
            headers=_sr_headers(auth, content_type=True),
            json=[{"op": "add", "path": "/allOf/-", "value": {"$ref": fg_id}}],
        )

    if resp.status_code not in (200, 201):
        raise ValueError(f"Attach field group failed ({resp.status_code}): {resp.text[:300]}")
    log.info("Attached field group %s to schema %s", fg_id, schema_id)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 9: ensure the identity namespace exists (Identity Service, region host)
# ──────────────────────────────────────────────────────────────────────────────

async def ensure_namespace(ctx: dict, data: dict) -> dict:
    input_json = await _get_input_json(ctx, data)
    decision = data.get("identityDecision") or {}
    is_primary = decision.get("isPrimary")
    namespace = input_json.get("identityNamespace")

    # No business key at all → nothing to register
    if is_primary is None or not namespace:
        data["namespaceSkipped"] = True
        log.info("No identity for %s — skipping namespace", ctx["schema_name"])
        return data

    auth = await _aep_auth(ctx["org_id"])
    url = f"{settings.identity_host}/data/core/idnamespace/identities"

    async with httpx.AsyncClient(timeout=30.0) as client:
        listing = await client.get(url, headers=_sr_headers(auth))
        if listing.status_code == 200:
            for ns in (listing.json() or []):
                if ns.get("code") == namespace:
                    data["namespaceCode"] = namespace
                    log.info("Namespace %r already exists — reusing", namespace)
                    return data

        resp = await client.post(
            url,
            headers=_sr_headers(auth, content_type=True),
            json={
                "name": namespace,
                "code": namespace,
                "description": f"Identity namespace migrated from Adobe Campaign for {ctx['schema_name']}.",
                "idType": "CROSS_DEVICE",
            },
        )

    if resp.status_code not in (200, 201):
        # Namespace already exists (race, prior run, or standard namespace) → reuse it
        if resp.status_code == 409 or "already exist" in resp.text.lower():
            data["namespaceCode"] = namespace
            log.info("Namespace %r already exists (409) — reusing", namespace)
            return data
        raise ValueError(f"Create namespace failed ({resp.status_code}): {resp.text[:300]}")
    data["namespaceCode"] = namespace
    log.info("Created identity namespace %r", namespace)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 10: create the identity descriptor on the primary-key field
# ──────────────────────────────────────────────────────────────────────────────

async def call_identity_descriptor(ctx: dict, data: dict) -> dict:
    if data.get("namespaceSkipped"):
        log.info("No identity for %s — skipping descriptor", ctx["schema_name"])
        return data

    input_json = await _get_input_json(ctx, data)
    tenant_id = data.get("tenantId")
    schema_id = data.get("schemaId")
    decision = data.get("identityDecision") or {}
    is_primary = bool(decision.get("isPrimary"))
    namespace = data.get("namespaceCode") or input_json.get("identityNamespace")
    primary_key = input_json.get("primaryKey")

    if not (tenant_id and schema_id and namespace and primary_key):
        raise ValueError("Missing data for identity descriptor (tenantId/schemaId/namespace/primaryKey)")

    payload = {
        "@type": "xdm:descriptorIdentity",
        "xdm:sourceSchema": schema_id,
        "xdm:sourceVersion": 1,
        "xdm:sourceProperty": _source_property_path(tenant_id, primary_key),
        "xdm:namespace": namespace,
        "xdm:property": "xdm:code",
        "xdm:isPrimary": is_primary,
    }

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{base}/tenant/descriptors",
            headers=_sr_headers(auth, content_type=True),
            json=payload,
        )

    if resp.status_code not in (200, 201):
        if resp.status_code == 409 or "already" in resp.text.lower():
            log.info("Identity descriptor already exists for %s", schema_id)
            data["descriptorIsPrimary"] = is_primary
            return data
        raise ValueError(f"Create identity descriptor failed ({resp.status_code}): {resp.text[:300]}")
    data["descriptorIsPrimary"] = is_primary
    log.info("Created identity descriptor for %s (isPrimary=%s)", schema_id, is_primary)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 11: enable the schema for Profile (union) — only when identity is primary
# ──────────────────────────────────────────────────────────────────────────────

async def enable_profile_union(ctx: dict, data: dict) -> dict:
    decision = data.get("identityDecision") or {}
    if not decision.get("isPrimary"):
        log.info("Identity not primary for %s — skipping Profile/union enable", ctx["schema_name"])
        return data

    schema_id = data.get("schemaId")
    if not schema_id:
        raise ValueError("schemaId missing for union enable")

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()
    encoded = quote(schema_id, safe="")

    async with httpx.AsyncClient(timeout=30.0) as client:
        current = await client.get(
            f"{base}/tenant/schemas/{encoded}",
            headers=_sr_headers(auth, accept="application/vnd.adobe.xed+json; version=1"),
        )
        if current.status_code == 200 and "union" in (current.json().get("meta:immutableTags") or []):
            log.info("Schema %s already union-enabled", schema_id)
            return data

        resp = await client.patch(
            f"{base}/tenant/schemas/{encoded}",
            headers=_sr_headers(auth, content_type=True),
            json=[{"op": "add", "path": "/meta:immutableTags", "value": ["union"]}],
        )

    if resp.status_code not in (200, 201):
        raise ValueError(f"Enable Profile union failed ({resp.status_code}): {resp.text[:300]}")
    log.info("Enabled Profile (union) for %s", schema_id)
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Step 12: verify the schema exists in the registry
# ──────────────────────────────────────────────────────────────────────────────

async def verify(ctx: dict, data: dict) -> dict:
    schema_id = data.get("schemaId")
    if not schema_id:
        raise ValueError("schemaId missing for verify")

    auth = await _aep_auth(ctx["org_id"])
    base = _schema_registry_base()
    encoded = quote(schema_id, safe="")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{base}/tenant/schemas/{encoded}",
            headers=_sr_headers(auth, accept="application/vnd.adobe.xed-id+json"),
        )

    if resp.status_code != 200:
        raise ValueError(f"Verify failed — schema not found ({resp.status_code}): {resp.text[:200]}")
    data["verified"] = True
    log.info("Verified schema %s exists in AEP", schema_id)
    return data
