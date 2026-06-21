"""
Thin async wrappers around the Adobe Experience Platform Schema Registry +
Identity Service APIs used to push relational schemas into AJO (Phase 3).

These functions are intentionally pure HTTP: they take an ``httpx.AsyncClient``
and a base headers dict, make one call, and return parsed JSON (or raise on a
non-2xx response). Auth/header assembly lives in ``pipeline.handlers`` so this
module has no DB dependency and is trivial to mock in tests.

Spec: relational-schema-to-ajo-workflow.md
"""

import logging
import urllib.parse

import httpx

log = logging.getLogger("acc_backend.pipeline.aep")

# ── Endpoints (spec §2 / §13) ────────────────────────────────────────────────
PLATFORM_HOST = "https://platform.adobe.io"
SCHEMA_REGISTRY_BASE = f"{PLATFORM_HOST}/data/foundation/schemaregistry"
# Identity Service is region-scoped — this org's region is va7 (spec §2).
IDENTITY_BASE = "https://platform-va7.adobe.io/data/core/idnamespace"

# Fixed literal that marks a schema as relational/model-based (spec §4).
ADHOC_EXTENDS = "https://ns.adobe.com/xdm/data/adhoc-v2"

# Accept headers differ between the schema list (xed-*) and descriptor list (xdm-*).
ACCEPT_SCHEMA_ID = "application/vnd.adobe.xed-id+json"
ACCEPT_SCHEMA_FULL = "application/vnd.adobe.xed-full+json; version=1"
ACCEPT_DESCRIPTOR_FULL = "application/vnd.adobe.xdm+json"

_TIMEOUT = 60.0


def _raise_for(resp: httpx.Response, action: str) -> None:
    if resp.status_code >= 400:
        raise RuntimeError(f"{action} failed (HTTP {resp.status_code}): {resp.text[:400]}")


def _encode_id(schema_id: str) -> str:
    """URL-encode a schema $id for use as a path parameter (spec §4 note)."""
    return urllib.parse.quote(schema_id, safe="")


def _normalize_list(payload) -> list[dict]:
    """
    Schema Registry list endpoints return either {"results": [...]} or, for
    descriptors, a dict grouped by descriptor @type. Flatten any of these to a
    plain list of objects.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "results" in payload and isinstance(payload["results"], list):
            return payload["results"]
        # Grouped-by-type dict (e.g. {"xdm:descriptorPrimaryKey": [...], ...})
        flattened: list[dict] = []
        for value in payload.values():
            if isinstance(value, list):
                flattened.extend(v for v in value if isinstance(v, dict))
        return flattened
    return []


# ── Schemas ──────────────────────────────────────────────────────────────────
async def list_tenant_schemas(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    """
    GET /tenant/schemas (Accept xed-id+json) — every custom schema's title/$id.
    Follows pagination via _links.next.
    """
    h = {**headers, "Accept": ACCEPT_SCHEMA_ID}
    url = f"{SCHEMA_REGISTRY_BASE}/tenant/schemas?limit=300"
    results: list[dict] = []
    seen_urls: set[str] = set()
    while url and url not in seen_urls:
        seen_urls.add(url)
        resp = await client.get(url, headers=h)
        _raise_for(resp, "List schemas")
        payload = resp.json()
        results.extend(_normalize_list(payload))
        nxt = (payload.get("_links", {}) or {}).get("next", {}) if isinstance(payload, dict) else {}
        href = nxt.get("href") if isinstance(nxt, dict) else None
        if not href:
            url = None
        elif href.startswith("http"):
            url = href
        else:
            # Root-relative path (e.g. /data/foundation/schemaregistry/tenant/schemas?...)
            url = f"{PLATFORM_HOST}{href}" if href.startswith("/") else f"{SCHEMA_REGISTRY_BASE}/{href}"
    return results


async def get_tenant_schema(client: httpx.AsyncClient, headers: dict, schema_id: str) -> dict:
    """GET one schema, fully resolved (Accept xed-full+json) — used for field diffing."""
    h = {**headers, "Accept": ACCEPT_SCHEMA_FULL}
    resp = await client.get(
        f"{SCHEMA_REGISTRY_BASE}/tenant/schemas/{_encode_id(schema_id)}", headers=h
    )
    _raise_for(resp, "Get schema")
    return resp.json()


async def create_tenant_schema(client: httpx.AsyncClient, headers: dict, body: dict) -> dict:
    """POST /tenant/schemas — returns the created schema (incl. $id)."""
    resp = await client.post(f"{SCHEMA_REGISTRY_BASE}/tenant/schemas", headers=headers, json=body)
    _raise_for(resp, "Create schema")
    return resp.json()


async def patch_tenant_schema(
    client: httpx.AsyncClient, headers: dict, schema_id: str, ops: list[dict]
) -> dict:
    """PATCH /tenant/schemas/{id} with a JSON-Patch op list (add missing fields)."""
    h = {**headers, "Accept": "application/vnd.adobe.xed+json"}
    resp = await client.patch(
        f"{SCHEMA_REGISTRY_BASE}/tenant/schemas/{_encode_id(schema_id)}", headers=h, json=ops
    )
    _raise_for(resp, "Patch schema")
    return resp.json()


# ── Descriptors ────────────────────────────────────────────────────────────────
async def list_tenant_descriptors(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    """GET /tenant/descriptors (Accept xdm+json) — full descriptor objects."""
    h = {**headers, "Accept": ACCEPT_DESCRIPTOR_FULL}
    resp = await client.get(f"{SCHEMA_REGISTRY_BASE}/tenant/descriptors", headers=h)
    _raise_for(resp, "List descriptors")
    return _normalize_list(resp.json())


async def create_tenant_descriptor(client: httpx.AsyncClient, headers: dict, body: dict) -> dict:
    """POST /tenant/descriptors — primary-key / version / timestamp / identity / relationship."""
    resp = await client.post(
        f"{SCHEMA_REGISTRY_BASE}/tenant/descriptors", headers=headers, json=body
    )
    _raise_for(resp, "Create descriptor")
    return resp.json()


# ── Identity namespaces (region host) ───────────────────────────────────────────
async def list_identity_namespaces(client: httpx.AsyncClient, headers: dict) -> list[dict]:
    """GET /idnamespace/identities — scan for a matching `code`."""
    h = {k: v for k, v in headers.items() if k != "Content-Type"}
    resp = await client.get(f"{IDENTITY_BASE}/identities", headers=h)
    _raise_for(resp, "List identity namespaces")
    return _normalize_list(resp.json())


async def create_identity_namespace(client: httpx.AsyncClient, headers: dict, body: dict) -> dict:
    """POST /idnamespace/identities — create a namespace (idType is locked once set)."""
    resp = await client.post(f"{IDENTITY_BASE}/identities", headers=headers, json=body)
    _raise_for(resp, "Create identity namespace")
    return resp.json()
