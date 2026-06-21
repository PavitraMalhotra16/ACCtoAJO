"""
SOAP envelope builders and response parsers for Adobe Campaign Classic.

All functions return/accept plain strings (UTF-8 XML).
No credentials are logged anywhere in this module.
"""

import logging
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

log = logging.getLogger("acc_backend.soap")

# XML namespaces used by ACC SOAP responses
NS = {
    "env": "http://schemas.xmlsoap.org/soap/envelope/",
    "xtkses": "urn:xtk:session",
}


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------

def build_logon_envelope(login_id: str, password: str) -> bytes:
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:session">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<urn:Logon>"
        "<urn:sessiontoken/>"
        f"<urn:strLogin>{_xml_escape(login_id)}</urn:strLogin>"
        f"<urn:strPassword>{_xml_escape(password)}</urn:strPassword>"
        "<urn:elemParameters/>"
        "</urn:Logon>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_bearer_token_logon_envelope(ims_access_token: str) -> bytes:
    """Build xtk:session#BearerTokenLogon — used for Technical Account (IMS) auth."""
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:session">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<urn:BearerTokenLogon>"
        "<urn:sessiontoken/>"
        f"<urn:strIMSAccessToken>{_xml_escape(ims_access_token)}</urn:strIMSAccessToken>"
        "<urn:elemParameters/>"
        "</urn:BearerTokenLogon>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_test_cnx_envelope(session_token: str, security_token: str) -> bytes:
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:session">'
        "<soapenv:Header>"
        "<urn:SecurityHeader>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:TestCnx>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        "</urn:TestCnx>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_execute_query_envelope(
    session_token: str,
    security_token: str,
    schema: str,
    fields: list[str],
    where_condition: str = "",
    line_count: int = 100,
    start_line: int = 0,
) -> bytes:
    nodes = "".join(f'<node expr="{_xml_escape(f)}"/>' for f in fields)
    where_block = (
        f"<where><condition expr=\"{_xml_escape(where_condition)}\"/></where>"
        if where_condition
        else ""
    )

    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:queryDef">'
        "<soapenv:Header>"
        "<urn:SecurityHeader "
        '    xmlns:urn="urn:xtk:session">'
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:ExecuteQuery>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        "<urn:entity>"
        f'<queryDef schema="{_xml_escape(schema)}" operation="select" '
        f'lineCount="{line_count}" startLine="{start_line}">'
        f"<select>{nodes}</select>"
        f"{where_block}"
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_schema_inventory_envelope(session_token: str, security_token: str) -> bytes:
    """
    Fetch all schema metadata needed for DDL candidate filtering:
    @name, @namespace, @label, @sqltable, @mappingType, @isLog, @isTemporal, @hasKey
    """
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:queryDef">'
        "<soapenv:Header>"
        '<urn:SecurityHeader xmlns:urn="urn:xtk:session">'
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:ExecuteQuery>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        "<urn:entity>"
        '<queryDef schema="xtk:schema" operation="select" lineCount="9999">'
        "<select>"
        '<node expr="@namespace"/>'
        '<node expr="@name"/>'
        '<node expr="@label"/>'
        "</select>"
        "<where>"
        '<condition expr="@name != \'\'"/>'
        "</where>"
        '<orderBy><node expr="@namespace"/></orderBy>'
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def parse_schema_inventory(xml_text: str) -> list[dict]:
    """Parse the schema inventory SOAP response into a list of metadata dicts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse schema inventory XML: %s", exc)
        return []

    results = []
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local != "schema":
            continue
        name = el.get("name", "")
        if not name:
            continue
        results.append({
            "namespace": el.get("namespace", ""),
            "name":      name,
            "label":     el.get("label", "") or el.get("_cs", ""),
        })
    return results


def build_list_schemas_envelope(session_token: str, security_token: str) -> bytes:
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:queryDef">'
        "<soapenv:Header>"
        '<urn:SecurityHeader xmlns:urn="urn:xtk:session">'
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:ExecuteQuery>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        "<urn:entity>"
        '<queryDef schema="xtk:schema" operation="select" lineCount="9999">'
        "<select>"
        '<node expr="@namespace"/>'
        '<node expr="@name"/>'
        '<node expr="@label"/>'
        "</select>"
        "<where>"
        '<condition expr="@namespace != \'xtk\' and @name != \'\'"/>'
        "</where>"
        '<orderBy><node expr="@namespace"/></orderBy>'
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_get_schema_envelope(
    session_token: str, security_token: str, namespace: str, name: str
) -> bytes:
    """Build xtk:schema#Get envelope to fetch full schema definition."""
    schema_id = f"{_xml_escape(namespace)}:{_xml_escape(name)}"
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:schema">'
        "<soapenv:Header>"
        '<urn:SecurityHeader xmlns:urn="urn:xtk:session">'
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:Get>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f'<urn:strName>{schema_id}</urn:strName>'
        "</urn:Get>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_srcschema_get_envelope(
    session_token: str, security_token: str, namespace: str, name: str
) -> bytes:
    """Fallback: query xtk:srcSchema using ExecuteQuery to fetch schema XML."""
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope '
        '    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        '    xmlns:urn="urn:xtk:queryDef">'
        "<soapenv:Header>"
        '<urn:SecurityHeader xmlns:urn="urn:xtk:session">'
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        f"<urn:securityToken>{_xml_escape(security_token)}</urn:securityToken>"
        "</urn:SecurityHeader>"
        "</soapenv:Header>"
        "<soapenv:Body>"
        "<urn:ExecuteQuery>"
        f"<urn:sessiontoken>{_xml_escape(session_token)}</urn:sessiontoken>"
        "<urn:entity>"
        '<queryDef schema="xtk:srcSchema" operation="get">'
        "<select>"
        '<node expr="@namespace"/>'
        '<node expr="@name"/>'
        '<node expr="@label"/>'
        '<node expr="@desc"/>'
        "</select>"
        "<where>"
        f'<condition expr="@namespace = \'{_xml_escape(namespace)}\' and @name = \'{_xml_escape(name)}\'"/>'
        "</where>"
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def parse_logon_response(xml_text: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse Logon XML: %s", exc)
        return None, None

    session_token = _find_text(root, [
        ".//{urn:xtk:session}pstrSessionToken",
        ".//pstrSessionToken",
    ])
    security_token = _find_text(root, [
        ".//{urn:xtk:session}pstrSecurityToken",
        ".//pstrSecurityToken",
    ])

    if not session_token:
        session_token = _find_text(root, [".//sessionToken", ".//SessionToken"])
    if not security_token:
        security_token = _find_text(root, [".//securityToken", ".//SecurityToken"])

    return session_token, security_token


def parse_schemas(xml_text: str) -> list[dict]:
    log.debug("Raw schemas response (first 500 chars): %s", xml_text[:500])

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse schemas XML: %s", exc)
        return []

    results = []

    for el in root.iter():
        local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag

        if local_tag != "schema":
            continue

        ns    = el.get("namespace", "")
        name  = el.get("name", "")
        label = el.get("label", "") or el.get("_cs", "")

        if name:
            results.append({
                "namespace": ns,
                "name": name,
                "label": label or name,
                "labelSingular": label or name,
            })

    log.info("Parsed %d schemas from ACC response", len(results))
    return results


def parse_schema_detail(xml_text: str) -> dict:
    """Parse a full schema XML response into a structured dict with attributes and elements."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse schema detail XML: %s", exc)
        return {}

    # Find the schema element (may be nested in SOAP envelope)
    schema_el = None
    for el in root.iter():
        local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local_tag == "schema":
            schema_el = el
            break

    if schema_el is None:
        # Try srcSchema
        for el in root.iter():
            local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local_tag == "srcSchema":
                schema_el = el
                break

    if schema_el is None:
        log.warning("No schema element found in response")
        return {}

    attributes = []
    elements = []

    for child in schema_el:
        local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local_tag == "attribute":
            attributes.append({
                "name": child.get("name", ""),
                "type": child.get("type", ""),
                "label": child.get("label", "") or child.get("_cs", ""),
                "length": child.get("length", ""),
                "required": child.get("notNull", "false"),
                "enum": child.get("enum", ""),
                "desc": child.get("desc", ""),
            })
        elif local_tag == "element":
            elements.append(_parse_element(child))

    return {
        "namespace": schema_el.get("namespace", ""),
        "name": schema_el.get("name", ""),
        "label": schema_el.get("label", "") or schema_el.get("_cs", ""),
        "labelSingular": schema_el.get("labelSingular", ""),
        "desc": schema_el.get("desc", ""),
        "attributes": attributes,
        "elements": elements,
    }


def _parse_element(el: ET.Element) -> dict:
    local_tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    attrs = {k: v for k, v in el.attrib.items()}
    children = [_parse_element(child) for child in el]
    return {"tag": local_tag, "attrs": attrs, "children": children}


def parse_fault(xml_text: str) -> Optional[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    fault_string = _find_text(root, [
        ".//{http://schemas.xmlsoap.org/soap/envelope/}faultstring",
        ".//faultstring",
    ])
    return fault_string


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_text(root: ET.Element, paths: list[str]) -> Optional[str]:
    for path in paths:
        el = root.find(path)
        if el is not None and el.text:
            return el.text.strip()
    return None


def _xml_escape(value: str) -> str:
    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
