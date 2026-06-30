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
CATALOG_BASE = f"{PLATFORM_HOST}/data/foundation/catalog"
# Identity Service is region-scoped — this org's region is va7 (spec §2).
IDENTITY_BASE = "https://platform-va7.adobe.io/data/core/idnamespace"
OC_MODELER_BASE = f"{PLATFORM_HOST}/ajo/relational/modeler"

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


async def delete_tenant_descriptor(client: httpx.AsyncClient, headers: dict, descriptor_id: str) -> None:
    """DELETE /tenant/descriptors/{id} — removes a descriptor by its @id."""
    resp = await client.delete(
        f"{SCHEMA_REGISTRY_BASE}/tenant/descriptors/{_encode_id(descriptor_id)}", headers=headers
    )
    _raise_for(resp, "Delete descriptor")


# ── Datasets (Catalog Service) ───────────────────────────────────────────────────
async def list_datasets_for_schema(client: httpx.AsyncClient, headers: dict, schema_id: str) -> list[dict]:
    """GET /dataSets filtered by schemaRef.id — uses server-side filtering so pagination
    and large sandbox dataset counts don't cause false misses."""
    resp = await client.get(
        f"{CATALOG_BASE}/dataSets",
        headers=headers,
        params={"limit": 10, "property": f"schemaRef.id=={schema_id}"},
    )
    _raise_for(resp, "List datasets")
    payload = resp.json()
    results = []
    if isinstance(payload, dict):
        for ds_id, ds in payload.items():
            ref = (ds.get("schemaRef") or {}).get("id", "")
            if ref == schema_id:
                results.append({"id": ds_id, **ds})
    return results


async def create_dataset(client: httpx.AsyncClient, headers: dict, name: str, schema_id: str) -> str:
    """POST /dataSets — creates a dataset backed by an existing XDM schema.
    Returns the dataset ID (the bare ID string, not the @/dataSets/... path)."""
    body = {
        "name": name,
        "schemaRef": {
            "id": schema_id,
            "contentType": "application/vnd.adobe.xed+json;version=1",
        },
    }
    resp = await client.post(f"{CATALOG_BASE}/dataSets", headers=headers, json=body)
    _raise_for(resp, "Create dataset")
    result = resp.json()
    # Response is ["@/dataSets/{id}"]
    if isinstance(result, list) and result:
        path = result[0]
        return path.split("/")[-1]
    raise RuntimeError(f"Unexpected create dataset response: {result}")


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


# ── Orchestrated Campaigns (OC) Modeler ─────────────────────────────────────
async def validate_oc_extension(client: httpx.AsyncClient, headers: dict, dataset_id: str) -> dict:
    """GET /modeler/datasets/{id}/extensions/validation — check OC eligibility."""
    resp = await client.get(
        f"{OC_MODELER_BASE}/datasets/{dataset_id}/extensions/validation",
        headers=headers,
    )
    _raise_for(resp, "Validate OC extension")
    return resp.json()


async def enable_oc_extension(client: httpx.AsyncClient, headers: dict, dataset_id: str) -> dict:
    """POST /modeler/datasets/extensions/enablement — fire async OC enablement job."""
    resp = await client.post(
        f"{OC_MODELER_BASE}/datasets/extensions/enablement",
        headers=headers,
        json={"datasetIds": [dataset_id]},
    )
    _raise_for(resp, "Enable OC extension")
    return resp.json()


async def get_oc_enablement_job_status(client: httpx.AsyncClient, headers: dict, job_id: str) -> dict:
    """GET /modeler/datasets/extensions/enablement/jobs/{jobId} — poll job status."""
    resp = await client.get(
        f"{OC_MODELER_BASE}/datasets/extensions/enablement/jobs/{_encode_id(job_id)}",
        headers=headers,
    )
    _raise_for(resp, "Get OC job status")
    return resp.json()
