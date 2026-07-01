"""
Transform extracted ACC workflow JSON into AJO-compatible workflow XML.

Only activity types supported by AJO Orchestrated Campaigns are included.
Unsupported types (fileImport, writer, javascript, etc.) are skipped.
"""

import logging
import xml.etree.ElementTree as ET

log = logging.getLogger("acc_backend.workflow_transformer")

# ACC activity types supported by AJO Orchestrated Campaigns
SUPPORTED_TYPES = {
    "start", "end",
    "query",
    "delivery", "notification",
    "split", "test",
    "enrichment",
    "wait", "scheduler",
    "deduplication",
    "union", "intersection", "exclusion",
    "reconciliation",
    "updateData",
    "fork",
    "readAudience", "saveAudience",
}

# Activity types that make a workflow NOT suitable for AJO Orchestrated Campaigns
UNSUPPORTED_TYPES = {
    "fileImport", "fileExport", "writer", "extract",
    "javascript", "execJs",
    "signal",
    "approval", "alert", "task",
    "nlserver", "transfer",
}


def is_ajo_candidate(workflow_data: dict) -> tuple[bool, str]:
    """
    Check if an extracted ACC workflow is suitable for AJO Orchestrated Campaign migration.

    Returns (is_candidate, reason).
    A workflow qualifies if:
    - It has at least one activity
    - It contains NO unsupported activity types
    - It has at least one start activity
    """
    activities = workflow_data.get("activities", [])
    if not activities:
        return False, "No activities"

    types = {a.get("type", "") for a in activities}
    unsupported = types & UNSUPPORTED_TYPES
    if unsupported:
        return False, f"Contains unsupported activity types: {sorted(unsupported)}"

    has_start = any(a.get("type") == "start" for a in activities)
    if not has_start:
        return False, "No start activity"

    return True, "OK"


def _strip_namespaces(el: ET.Element) -> ET.Element:
    """Strip XML namespace prefixes from all tags and attributes."""
    el.tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    el.attrib = {
        (k.split("}")[-1] if "}" in k else k): v
        for k, v in el.attrib.items()
        if not k.startswith("{")
    }
    for child in el:
        _strip_namespaces(child)
    return el


def _strip_whitespace(el: ET.Element) -> None:
    """Remove formatting whitespace from text/tail nodes."""
    if el.text and not el.text.strip():
        el.text = None
    if el.tail and not el.tail.strip():
        el.tail = None
    for child in el:
        _strip_whitespace(child)


def build_workflow_xml(workflow_data: dict, acc_workflow_id: str) -> str:
    """
    Build the PATCH XML body from extracted workflow_data.

    - Skips unsupported activity types
    - Strips SOAP namespace prefixes
    - Removes formatting whitespace
    - Wraps in <workflow id="{acc_workflow_id}" _operation="update">

    acc_workflow_id is a placeholder — migrate_workflow() replaces it with the
    real ID returned by AJO after campaign creation.
    """
    activities = workflow_data.get("activities", [])
    parts = []
    skipped = []

    for act in activities:
        act_type = act.get("type", "")
        if act_type in UNSUPPORTED_TYPES:
            skipped.append(act.get("name", act_type))
            continue

        raw_xml = act.get("rawXml", "")
        if not raw_xml:
            skipped.append(act.get("name", act_type))
            continue

        try:
            el = ET.fromstring(raw_xml)
            _strip_namespaces(el)
            _strip_whitespace(el)
            activity_xml = ET.tostring(el, encoding="unicode")
            activity_xml = activity_xml.replace("nms:recipient", "caas:recipients")
            parts.append(activity_xml)
        except ET.ParseError as exc:
            log.warning("Could not parse rawXml for activity %s: %s", act.get("name"), exc)
            skipped.append(act.get("name", act_type))

    if skipped:
        log.info("Skipped %d unsupported activities: %s", len(skipped), skipped)

    activities_xml = "".join(parts)
    return (
        f'<workflow id="{acc_workflow_id}" xtkschema="xtk:workflow" _operation="update">'
        f'<activities>{activities_xml}</activities>'
        f'</workflow>'
    )
