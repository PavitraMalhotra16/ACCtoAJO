"""
Hermes authoring API calls for pushing ACC workflows into AJO Orchestrated Campaigns.

Three-step flow per workflow:
  1. POST /apis/orchestratedCampaigns          → create blank campaign, get version_id
  2. GET  /apis/orchestratedCampaignVersions/{version_id} → get linked ACC workflow_id
  3. PATCH /apis/orchestratedCampaignVersions/{version_id}/workflow → push activities XML
"""

import logging
import re

import httpx

log = logging.getLogger("acc_backend.ajo_workflow_pusher")

HERMES_BASE = "https://hermes-authoring.adobe.io/apis"
TIMEOUT = 30.0


def _headers(bearer_token: str, org_id: str, sandbox_name: str, content_type: str = "application/json") -> dict:
    return {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": content_type,
        "Accept": "application/json",
        "x-api-key": "dx-hermes-ui",
        "x-api-version": "1",
        "x-gw-ims-org-id": org_id,
        "x-sandbox-name": sandbox_name,
        "acc-sdk-auth": "ImsBearerToken",
        "acc-sdk-client-app": "brand-journey-ui",
        "acc-sdk-version": "@adobe/acc-js-sdk 1.1.60",
        "x-query-source": "@adobe/acc-js-sdk 1.1.60,brand-journey-ui",
    }


async def create_campaign(
    name: str,
    bearer_token: str,
    org_id: str,
    sandbox_name: str,
    description: str = "",
) -> tuple[str, str]:
    """
    POST /apis/orchestratedCampaigns — create a blank orchestrated campaign.

    Returns (campaign_id, version_id).
    Raises RuntimeError on non-2xx response.
    """
    url = f"{HERMES_BASE}/orchestratedCampaigns"
    body = {"name": name, "description": description}

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(url, json=body, headers=_headers(bearer_token, org_id, sandbox_name))

    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Campaign creation failed HTTP {resp.status_code}: {resp.text[:400]}")

    data = resp.json()
    campaign_id = data.get("id") or data.get("orchestratedCampaignId")
    version_id = (
        (data.get("currentVersion") or {}).get("orchestratedCampaignVersionId")
        or data.get("orchestratedCampaignVersionId")
    )

    if not campaign_id or not version_id:
        raise RuntimeError(f"Unexpected campaign creation response: {resp.text[:400]}")

    log.info("Created campaign %s version %s", campaign_id, version_id)
    return campaign_id, version_id


async def get_acc_workflow_id(
    version_id: str,
    bearer_token: str,
    org_id: str,
    sandbox_name: str,
) -> str:
    """
    GET /apis/orchestratedCampaignVersions/{version_id} — get the ACC workflowId
    that AJO linked to this campaign version.

    Returns the numeric workflowId string (e.g. "4662").
    Raises RuntimeError on failure.
    """
    url = f"{HERMES_BASE}/orchestratedCampaignVersions/{version_id}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(url, headers=_headers(bearer_token, org_id, sandbox_name))

    if resp.status_code != 200:
        raise RuntimeError(f"GET version failed HTTP {resp.status_code}: {resp.text[:400]}")

    workflow_id = resp.json().get("workflowId")
    if not workflow_id:
        raise RuntimeError(f"workflowId missing from version response: {resp.text[:400]}")

    return str(workflow_id)


async def push_workflow_xml(
    version_id: str,
    workflow_id: str,
    xml_body: str,
    bearer_token: str,
    org_id: str,
    sandbox_name: str,
) -> None:
    """
    PATCH /apis/orchestratedCampaignVersions/{version_id}/workflow — push activities.

    xml_body must be a complete <workflow id="{workflow_id}" ...><activities>...</activities></workflow>.
    Raises RuntimeError on non-200 response.
    """
    url = f"{HERMES_BASE}/orchestratedCampaignVersions/{version_id}/workflow"

    log.info("PATCH XML for version %s:\n%s", version_id, xml_body)

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.patch(
            url,
            content=xml_body.encode("utf-8"),
            headers=_headers(bearer_token, org_id, sandbox_name, content_type="application/xml"),
        )

    log.info("PATCH response %s: %s", resp.status_code, resp.text[:1000])

    if resp.status_code != 200:
        raise RuntimeError(f"Workflow PATCH failed HTTP {resp.status_code}: {resp.text[:400]}")

    log.info("Pushed workflow %s to version %s", workflow_id, version_id)


async def migrate_workflow(
    name: str,
    xml_body: str,
    bearer_token: str,
    org_id: str,
    sandbox_name: str,
    description: str = "",
) -> dict:
    """
    Full 3-step migration for one ACC workflow:
      1. Create blank campaign
      2. Get linked ACC workflow_id
      3. PATCH activities

    Returns { campaign_id, version_id, workflow_id }.
    Raises RuntimeError on any step failure.
    """
    campaign_id, version_id = await create_campaign(name, bearer_token, org_id, sandbox_name, description)
    workflow_id = await get_acc_workflow_id(version_id, bearer_token, org_id, sandbox_name)

    # Inject the correct workflow_id into the XML body
    xml_body = re.sub(r'<workflow\s+id="[^"]*"', f'<workflow id="{workflow_id}"', xml_body, count=1)

    await push_workflow_xml(version_id, workflow_id, xml_body, bearer_token, org_id, sandbox_name)

    return {
        "campaign_id": campaign_id,
        "version_id": version_id,
        "workflow_id": workflow_id,
    }
