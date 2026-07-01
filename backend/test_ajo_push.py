"""
Standalone test: push one ACC workflow (WKF2) into an existing AJO orchestrated
campaign version via the Hermes authoring proxy.

Endpoint:
  PATCH https://hermes-authoring.adobe.io/apis/orchestratedCampaignVersions/{version_id}/workflow
  Content-Type: application/xml

The body is standard ACC workflow XML with _operation attributes on activities.
The workflow id in the XML must match the ACC workflow linked to the target campaign version.

Usage:
  cd backend
  python test_ajo_push.py
"""

import asyncio
import json
import xml.etree.ElementTree as ET

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# ── Config — edit these ───────────────────────────────────────────────────────

# The AJO orchestrated campaign version to update (from your captured request)
CAMPAIGN_VERSION_ID = "38149feb-4fe2-40db-98f4-cabe1a700a5e"

# The ACC workflow id linked to that campaign version (from the captured PATCH payload)
ACC_WORKFLOW_ID = "4600"

# Bearer token — refresh from browser DevTools if expired
BEARER_TOKEN = (
    "eyJhbGciOiJSUzI1NiIsIng1dSI6Imltc19uYTEta2V5LWF0LTEuY2VyIiwia2lkIjoiaW1zX25hMS1rZXktYXQtMSIsIml0dCI6ImF0In0"
    ".eyJpZCI6IjE3ODI2NDM5NzE2OTZfMmE5ZWMxOTctZTk5MS00Nzg0LWFkZjgtMDJiM2MxZmJkMDlmX3V3MiIsInR5cGUiOiJhY2Nlc3NfdG9rZW4iLCJjbGllbnRfaWQiOiJleGNfYXBwIiwidXNlcl9pZCI6IkY4RTg4MjQ5NkEyRkFEODQwQTQ5NUZGM0BjOTBmM2EyNDYyYWIyMjkxNDk1ZmRmLmUiLCJzdGF0ZSI6IntcInNlc3Npb25cIjpcImh0dHBzOi8vaW1zLW5hMS5hZG9iZWxvZ2luLmNvbS9pbXMvc2Vzc2lvbi92MS9NMlExTm1NeVpqVXRaVGxpTlMwMFlUVTBMV0ppWkdVdE5EWTNOek5rTTJKaU5EZzFMUzB3T1RaQk9ETkZNRFpCTURWQ1F6UXdNRUUwT1RWRk0wVkFZV1J2WW1VdVkyOXRcIn0iLCJhcyI6Imltcy1uYTEiLCJhYV9pZCI6IjA5NkE4M0UwNkEwNUJDNDAwQTQ5NUUzRUBhZG9iZS5jb20iLCJjdHAiOjAsImZnIjoiMlNNR1k2REJWTE01QURVS0ZBUVZLWEFBQzQ9PT09PT0iLCJzaWQiOiIxNzgyNDcyNTkyMDQ0X2QzOTIwMjI1LWFkMmYtNGQ1NS1hZTBiLThmMzhhZGRmY2EyMl91dzIiLCJtb2kiOiI2MmEwNWFlNyIsInBiYSI6Ik1lZFNlY05vRVYsTG93U2VjIiwiZXhwaXJlc19pbiI6Ijg2NDAwMDAwIiwic2NvcGUiOiJhYi5tYW5hZ2UsYWNjb3VudF9jbHVzdGVyLnJlYWQsYWNjb3VudHMucmVhZCxhZGRpdGlvbmFsX2luZm8sYWRkaXRpb25hbF9pbmZvLmpvYl9mdW5jdGlvbixhZGRpdGlvbmFsX2luZm8ucHJvamVjdGVkUHJvZHVjdENvbnRleHQsYWRkaXRpb25hbF9pbmZvLnJvbGVzLEFkb2JlSUQsYWRvYmVpby5hcHByZWdpc3RyeS5yZWFkLGFkb2JlaW9fYXBpLGFlbS5hZG9iZS5leHBlcmltZW50YWwsYWVtLmFzc2V0cy5hdXRob3IsYWVtLmFzc2V0cy5kZWxpdmVyeSxhZW0uZm9sZGVycyxhZW0uZnJvbnRlbmQuYWxsLGF1ZGllbmNlbWFuYWdlcl9hcGksY3JlYXRpdmVfY2xvdWQsbXBzLG9wZW5pZCxvcmcucmVhZCxwcHMucmVhZCxyZWFkX29yZ2FuaXphdGlvbnMscmVhZF9wYyxyZWFkX3BjLmFjcCxyZWFkX3BjLmRtYV90YXJ0YW4sc2VydmljZV9wcmluY2lwYWxzLndyaXRlLHNlc3Npb24iLCJjcmVhdGVkX2F0IjoiMTc4MjY0Mzk3MTY5NiJ9"
    ".cEjENyvR-ZcgSnsJzW0ujOxCtUKbbSPpRKyMv7AoNB-WRhVX9te6sCjoAve7G6ZT5yoL21WDPFyWRmKJj2h2ewFXTUvtynOnD9Y-DAeRk5Gi6NpjQkqwr3VFgNpK1ynD2s0HB6xRNbKn3EYxjNBdkgFon0Wr9wpYAIX12UGfEPz-XAbBCLiImvYnHcHIXGoot-V5BlyCvXOJ8DlY8GuIU42ZZaD22ceFU9UNR7i4VHSzmx6iEODnKTrgYKEqFMipQ9EIgXBLoJxjFlPaCa_g8p1S-uJ8EgfDX1N60m46j2kOCHeWtTIb-I6ixirB1Gg9tYZE5OS58mxXneMOSkT_mg"
)

ORG_ID = "31D5272C69BA859C0A495CE0@AdobeOrg"
SANDBOX_NAME = "prod"
DATABASE_URL = "postgresql+asyncpg://postgres:pavitra@localhost:5432/acc_ajo"

# Workflow to push (must exist in acc_workflow_parsed)
WORKFLOW_INTERNAL_NAME = "WKF2"

# ── Helpers ───────────────────────────────────────────────────────────────────

def strip_namespaces(el: ET.Element) -> ET.Element:
    """Recursively strip XML namespace prefixes from all tags and attributes."""
    # Strip namespace from tag: {urn:xtk:queryDef}start → start
    el.tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    # Strip namespace from attribute keys
    el.attrib = {
        (k.split("}")[-1] if "}" in k else k): v
        for k, v in el.attrib.items()
        if not k.startswith("{")  # drop xmlns:* declarations
    }
    for child in el:
        strip_namespaces(child)
    return el


def build_workflow_xml(workflow_data: dict, acc_workflow_id: str) -> str:
    """
    Build the PATCH XML body from parsed workflow_data.

    Takes the rawXml of each activity, strips SOAP namespace prefixes,
    adds _operation="insertOrUpdate", wraps in <workflow _operation="update">.
    """
    activities_xml_parts = []
    for act in workflow_data.get("activities", []):
        raw = act.get("rawXml", "")
        if not raw:
            continue
        try:
            el = ET.fromstring(raw)
            strip_namespaces(el)
            el.set("_operation", "insertOrUpdate")
            activities_xml_parts.append(ET.tostring(el, encoding="unicode"))
        except ET.ParseError as exc:
            print(f"  [WARN] Could not parse rawXml for activity {act.get('name')}: {exc}")

    activities_block = "".join(activities_xml_parts)
    return (
        f'<workflow id="{acc_workflow_id}" xtkschema="xtk:workflow" _operation="update">'
        f"<activities>{activities_block}</activities>"
        f"</workflow>"
    )


async def load_workflow_from_db(internal_name: str) -> dict | None:
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        from db import AccWorkflowParsed
        result = await session.execute(
            select(AccWorkflowParsed).where(
                AccWorkflowParsed.internal_name == internal_name
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return json.loads(row.workflow_data)

    await engine.dispose()


def _base_headers(content_type: str = "application/json") -> dict:
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": content_type,
        "Accept": "application/json",
        "x-api-key": "dx-hermes-ui",
        "x-api-version": "1",
        "x-gw-ims-org-id": ORG_ID,
        "x-sandbox-name": SANDBOX_NAME,
        "acc-sdk-auth": "ImsBearerToken",
        "acc-sdk-client-app": "brand-journey-ui",
        "acc-sdk-version": "@adobe/acc-js-sdk 1.1.60",
        "x-query-source": "@adobe/acc-js-sdk 1.1.60,brand-journey-ui",
    }


async def create_campaign(name: str, description: str = "") -> tuple[int, str]:
    """POST /apis/orchestratedCampaigns — create a new blank orchestrated campaign."""
    url = "https://hermes-authoring.adobe.io/apis/orchestratedCampaigns"
    body = {"name": name, "description": description}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=body, headers=_base_headers())
    return resp.status_code, resp.text


async def push_to_ajo(version_id: str, workflow_id: str, xml_body: str) -> tuple[int, str]:
    url = (
        f"https://hermes-authoring.adobe.io/apis/orchestratedCampaignVersions"
        f"/{version_id}/workflow"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.patch(
            url,
            content=xml_body.encode("utf-8"),
            headers=_base_headers("application/xml"),
        )
    return resp.status_code, resp.text


async def get_campaign_version(version_id: str) -> tuple[int, str]:
    """GET campaign version to check its current state and linked ACC workflow id."""
    url = f"https://hermes-authoring.adobe.io/apis/orchestratedCampaignVersions/{version_id}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_base_headers())
    return resp.status_code, resp.text


# nms:operation XML for the "demo" campaign containing WKF6 (start -> wait -> end)
OPERATION_XML = """<operation _cs="demo (OP1)" id="7540" internalName="OP1" label="demo" xtkschema="nms:operation">
  <workflow _cs="demo (WKF6)" id="7541" internalName="WKF6" label="demo" xtkschema="xtk:workflow">
    <activities>
      <start collision="0" img="xtk:activities/start.png" label="Start" mask="0"
             name="start" onError="0" runOnSimulation="true" timezone="_inherit_"
             x="172" y="133">
        <transitions>
          <initial enabled="true" name="initial" target="wait" x="0" y="0"/>
        </transitions>
      </start>
      <wait collision="0" img="xtk:activities/hourglass.png" label="Wait" mask="0"
            name="wait" onError="0" runOnSimulation="true" timezone="_inherit_" x="281"
            y="125">
        <transitions>
          <transition enabled="true" name="transition" target="end"/>
        </transitions>
      </wait>
      <end collision="0" img="xtk:activities/end.png" label="End" mask="0" name="end"
           onError="0" runOnSimulation="true" timezone="_inherit_" x="450" y="126"/>
    </activities>
  </workflow>
</operation>"""


def extract_activities_from_operation_xml(op_xml: str) -> list[ET.Element]:
    """Parse nms:operation XML and return the list of activity elements from the embedded workflow."""
    root = ET.fromstring(op_xml)
    # Find <workflow> child (may be direct child or nested)
    wf = root.find("workflow")
    if wf is None:
        raise ValueError("No <workflow> element found inside <operation>")
    acts_el = wf.find("activities")
    if acts_el is None:
        raise ValueError("No <activities> element found inside <workflow>")
    return list(acts_el)


def _strip_whitespace(el: ET.Element) -> None:
    """Remove formatting whitespace from text/tail so ACC doesn't see unexpected text nodes."""
    if el.text and not el.text.strip():
        el.text = None
    if el.tail and not el.tail.strip():
        el.tail = None
    for child in el:
        _strip_whitespace(child)


def build_patch_xml_from_operation(
    op_xml: str,
    acc_workflow_id: str,
    existing_activity_names: list[str] | None = None,
) -> str:
    """
    Build the PATCH body from an nms:operation XML.

    - existing_activity_names: names of activities currently in the ACC workflow.
      Each will be sent with _operation="delete" so they are removed before the
      new activities are inserted.  Pass None to skip deletes (insert-only).
    """
    activities = extract_activities_from_operation_xml(op_xml)

    parts = []

    # Delete existing activities first so we start with a clean slate
    if existing_activity_names:
        for name in existing_activity_names:
            # We need the right tag — infer from name prefix conventions:
            # start* → start, query* → query, end* → end, wait* → wait
            tag = "start" if name.startswith("start") else \
                  "query" if name.startswith("query") else \
                  "end"   if name.startswith("end")   else \
                  "wait"  if name.startswith("wait")  else "activity"
            parts.append(f'<{tag} name="{name}" _operation="delete"/>')

    # Insert new activities (no _operation = insert in ACC semantics)
    for el in activities:
        strip_namespaces(el)
        _strip_whitespace(el)
        el.attrib.pop("_operation", None)  # remove any existing _operation
        parts.append(ET.tostring(el, encoding="unicode"))

    return (
        f'<workflow id="{acc_workflow_id}" xtkschema="xtk:workflow" _operation="update">'
        f'<activities>{"".join(parts)}</activities>'
        f'</workflow>'
    )


async def main():
    import json as _json

    # Step 1: Create a brand new orchestrated campaign
    campaign_name = "Migration Test - WKF6 (start->wait->end)"
    print(f"Step 1: Creating new orchestrated campaign '{campaign_name}'...")
    c_status, c_body = await create_campaign(campaign_name)
    print(f"  POST {c_status}: {c_body[:600]}")

    if c_status not in (200, 201):
        if c_status == 401:
            print("  -> Token expired. Grab a fresh Bearer token from DevTools.")
        else:
            print("  -> Campaign creation failed.")
        return

    campaign = _json.loads(c_body)
    # Response may return campaign directly or wrap in currentVersion
    campaign_id = campaign.get("id") or campaign.get("orchestratedCampaignId")
    version_id = (
        campaign.get("orchestratedCampaignVersionId")
        or (campaign.get("currentVersion") or {}).get("orchestratedCampaignVersionId")
        or campaign.get("id")  # fallback if response IS the version
    )
    print(f"  Campaign ID:  {campaign_id}")
    print(f"  Version ID:   {version_id}")

    # Step 2: GET the version to find the linked ACC workflow ID
    print(f"\nStep 2: Fetching version details to get linked ACC workflow ID...")
    v_status, v_body = await get_campaign_version(version_id)
    version = _json.loads(v_body)
    workflow_id = version.get("workflowId")
    print(f"  workflowId: {workflow_id}  status: {version.get('status')}")

    if not workflow_id:
        print("  -> Could not determine workflowId from version response.")
        print(f"  Full response: {v_body[:600]}")
        return

    # Step 3: Build and PATCH the WKF6 activities into the blank workflow
    print(f"\nStep 3: Building PATCH XML from WKF6 (start->wait->end)...")
    xml_body = build_patch_xml_from_operation(OPERATION_XML, workflow_id)
    print(f"  XML ({len(xml_body)} chars): {xml_body[:300]}...")

    print(f"\n  PATCHing to version {version_id}...")
    p_status, p_body = await push_to_ajo(version_id, workflow_id, xml_body)
    print(f"\n-- Result ------------------------------------------")
    print(f"  HTTP {p_status}")
    print(f"  Response: {p_body[:600] if p_body else '(empty)'}")

    if p_status == 200:
        print(f"\n[SUCCESS] Full end-to-end flow works!")
        print(f"  Campaign ID:  {campaign_id}")
        print(f"  Version ID:   {version_id}")
        print(f"  ACC Workflow: {workflow_id}")
        print(f"  Open AJO Campaigns to verify start->wait->end on canvas.")
    elif p_status == 401:
        print("\n[FAIL] Token expired.")
    else:
        print("\n[FAIL] PATCH failed after successful campaign creation.")


if __name__ == "__main__":
    asyncio.run(main())
