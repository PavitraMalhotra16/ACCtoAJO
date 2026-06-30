"""
AEP Batch Ingestion API wrappers.
Base: https://platform.adobe.io/data/foundation/import

These functions are intentionally pure HTTP: they take an ``httpx.AsyncClient``
and a base headers dict, make one call, and return parsed JSON (or raise on a
non-2xx response). Auth/header assembly lives in ``pipeline.handlers`` so this
module has no DB dependency and is trivial to mock in tests.
"""

import urllib.parse

import httpx

BATCH_INGEST_BASE = "https://platform.adobe.io/data/foundation/import"


def _raise_for(resp: httpx.Response, label: str) -> None:
    """Raise RuntimeError on non-2xx status codes."""
    if resp.status_code >= 400:
        raise RuntimeError(f"{label} failed (HTTP {resp.status_code}): {resp.text[:300]}")


async def create_batch(
    client: httpx.AsyncClient,
    headers: dict,
    dataset_id: str,
    file_format: str,
) -> dict:
    """POST /batches — create a new ingestion batch.

    Returns a dict with at least 'id' and 'status' keys.
    """
    resp = await client.post(
        f"{BATCH_INGEST_BASE}/batches",
        headers={**headers, "Content-Type": "application/json"},
        json={"datasetId": dataset_id, "inputFormat": {"format": file_format}},
    )
    _raise_for(resp, "Create batch")
    return resp.json()


async def upload_file(
    client: httpx.AsyncClient,
    headers: dict,
    batch_id: str,
    dataset_id: str,
    filename: str,
    file_bytes: bytes,
) -> None:
    """PUT /batches/{batchId}/datasets/{datasetId}/files/{filePath} — upload file bytes.

    filename is URL-encoded to handle special characters.
    """
    encoded_name = urllib.parse.quote(filename, safe="")
    resp = await client.put(
        f"{BATCH_INGEST_BASE}/batches/{batch_id}/datasets/{dataset_id}/files/{encoded_name}",
        headers={**headers, "Content-Type": "application/octet-stream"},
        content=file_bytes,
    )
    _raise_for(resp, "Upload file")


async def complete_batch(
    client: httpx.AsyncClient,
    headers: dict,
    batch_id: str,
) -> dict:
    """POST /batches/{batchId}?action=COMPLETE — signal ingestion is complete.

    Returns a dict with at least 'id' and 'status' keys.
    """
    resp = await client.post(
        f"{BATCH_INGEST_BASE}/batches/{batch_id}",
        headers={**headers, "Content-Type": "application/json"},
        params={"action": "COMPLETE"},
    )
    _raise_for(resp, "Complete batch")
    return resp.json()
