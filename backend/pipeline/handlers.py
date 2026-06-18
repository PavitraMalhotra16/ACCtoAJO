import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from db import AsyncSessionLocal, DestinationConnection, TenantConfig
from core.security import decrypt

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


async def load_json(ctx: dict, data: dict) -> dict:
    with open(ctx["schema_storage_path"], "r", encoding="utf-8") as f:
        return json.load(f)


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

    data["identityDecision"] = {
        "status": "resolved",
        "fieldPath": "/id",
        "isPrimary": False,
        "reason": "No primary or unique keys found — defaulted to surrogate identity",
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

        access_token = decrypt(dest.encrypted_access_token)
        client_id = dest.client_id or ""
        if not client_id:
            raise ValueError(f"No client_id found for org {org_id}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://platform.adobe.io/data/foundation/schemaregistry/tenant",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "x-api-key": client_id,
                    "x-gw-ims-org-id": org_id,
                    "x-sandbox-name": dest.sandbox_name or "prod",
                    "Accept": "application/vnd.adobe.xed-id+json",
                },
            )

        if resp.status_code != 200:
            raise ValueError(f"AEP tenant API returned {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        tenant_id = payload.get("tenantId") or payload.get("imsOrg", "").split("@")[0]
        if not tenant_id:
            raise ValueError("Could not extract tenantId from AEP response")

        if cached:
            cached.tenant_id = tenant_id
            cached.fetched_at = datetime.now(timezone.utc)
        else:
            db.add(TenantConfig(
                org_id=org_id,
                tenant_id=tenant_id,
                sandbox_id=dest.sandbox_name,
                sandbox_type="production",
            ))
        await db.commit()

    data["tenantId"] = tenant_id
    log.info("Fetched tenant ID %r for org %s", tenant_id, org_id)
    return data


async def build_payload_stub(ctx: dict, data: dict) -> dict:
    return data


async def call_schema_api_stub(ctx: dict, data: dict) -> dict:
    return data


async def call_identity_descriptor_stub(ctx: dict, data: dict) -> dict:
    return data


async def verify_stub(ctx: dict, data: dict) -> dict:
    return data
