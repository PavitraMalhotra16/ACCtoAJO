"""
SOAP envelope builders and response parsers for Adobe Campaign Classic.

All functions return/accept plain strings (UTF-8 XML).
No credentials are logged anywhere in this module.
"""

import html as html_lib
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


def build_count_templates_envelope(session_token: str, security_token: str) -> bytes:
    """Count nms:delivery records where @isModel=1 and @schema='nms:delivery'."""
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
        '<queryDef schema="nms:delivery" operation="count">'
        "<where>"
        '<condition expr="@isModel = 1"/>'
        '<condition expr="@messageType = 0 OR @messageType = 1"/>'
        "</where>"
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_list_templates_envelope(
    session_token: str, security_token: str, page_size:int , start_line:int
) -> bytes:
    """Fetch all nms:delivery templates (isModel=1) with ALL fields — no select node restrictions
    so the response includes content, subject, HTML body, etc. in the returned XML."""
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
        f'<queryDef schema="nms:delivery" operation="select" lineCount="{page_size}" startLine="{start_line}">'
        "<select>"
        '<node expr="@id"/>'
        '<node expr="@internalName"/>'
        '<node expr="@label"/>'
        '<node expr="@isModel"/>'
        '<node expr="@messageType"/>'
        '<node expr="@lastModified"/>'
        "</select>"
        "<where>"
        '<condition expr="@isModel = 1"/>'
        '<condition expr="@builtIn != 1"/>'
        '<condition expr="@internalName != \'notifyWkfToStop\'"/>'
        '<condition expr="@messageType = 0 OR @messageType = 1"/>'
        "</where>"
        '<orderBy><node expr="@id"/></orderBy>'
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def build_get_delivery_envelope(session_token: str, security_token: str, delivery_id: str) -> bytes:
    """Fetch one nms:delivery template by @id.
    Uses NodeValue() to extract subject/html/text from inside the 'data' XML blob field."""
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
        '<queryDef schema="nms:delivery" operation="get">'
        "<select>"
        '<node expr="@id"/>'
        '<node expr="@internalName"/>'
        '<node expr="@label"/>'
        '<node expr="@messageType"/>'
        '<node expr="@lastModified"/>'
        '<node expr="desc"/>'
        '<node expr="data"/>'
        '<node expr="NodeValue(\'delivery/mailParameters/subject\', data)" alias="subject"/>'
        "</select>"
        "<where>"
        f'<condition expr="@id = {_xml_escape(delivery_id)}"/>'
        '<condition expr="@isModel = 1"/>'
        "</where>"
        "</queryDef>"
        "</urn:entity>"
        "</urn:ExecuteQuery>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )
    return envelope.encode("utf-8")


def parse_count_response(xml_text: str) -> int:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local in ("collection", "delivery-collection", "queryDef"):
            for attr in ("count", "recordCount"):
                val = el.get(attr, "")
                if val:
                    try:
                        return int(val)
                    except ValueError:
                        pass
    count = sum(
        1 for el in root.iter()
        if (el.tag.split("}")[-1] if "}" in el.tag else el.tag) == "delivery"
    )
    return count


_EXCLUDED_INTERNAL_NAMES = {"notifyWkfToStop"}


def parse_template_list(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    results = []
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local != "delivery":
            continue
        delivery_id = el.get("id", el.get("_id", ""))
        if not delivery_id:
            continue
        if el.get("internalName", "") in _EXCLUDED_INTERNAL_NAMES:
            continue
        msg_type = el.get("messageType", "0")
        channel = "sms" if msg_type == "1" else "email"

        # description
        desc_el = el.find("desc")
        description = ""
        if desc_el is not None:
            description = (desc_el.get("text", "") or desc_el.text or "").strip()

        # content fields — available when no <select> restrictions are used
        subject_raw = html_raw = text_raw = sms_raw = ""
        content_el = el.find("content")
        if content_el is not None:
            subject_raw = content_el.get("subject", "").strip()
            html_el = content_el.find("html")
            if html_el is not None:
                html_raw = (html_el.get("source", "") or html_el.text or "").strip()
            text_el = content_el.find("textContent")
            if text_el is not None:
                text_raw = (text_el.get("source", "") or text_el.text or "").strip()
            if channel == "sms":
                sms_raw = text_raw or content_el.get("text", "").strip()

        results.append({
            "id": delivery_id,
            "internalName": el.get("internalName", ""),
            "label": el.get("label", el.get("_cs", "")),
            "messageType": msg_type,
            "channel": channel,
            "lastModified": el.get("lastModified", ""),
            "description": description,
            "subjectRaw": subject_raw,
            "htmlRaw": html_raw,
            "textRaw": text_raw,
            "smsRaw": sms_raw,
            "rawXml": ET.tostring(el, encoding="unicode"),
        })
    return results


def parse_delivery_detail(xml_text: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    delivery_el = None
    for el in root.iter():
        if (el.tag.split("}")[-1] if "}" in el.tag else el.tag) == "delivery":
            delivery_el = el
            break
    if delivery_el is None:
        return {}

    msg_type = delivery_el.get("messageType", "0")
    channel = "sms" if msg_type == "1" else "email"

    desc_el = _find(delivery_el, "desc")
    description = (desc_el.text or "").strip() if desc_el is not None else ""

    # Subject: NodeValue alias is short enough — safe to use directly
    subject_el = _find(delivery_el, "subject")
    subject_raw = (subject_el.text or "").strip() if subject_el is not None else ""

    # Subject fallback: mailParameters/subject CDATA
    if not subject_raw:
        mail_params = _find(delivery_el, "mailParameters")
        if mail_params is not None:
            subj_el = _find(mail_params, "subject")
            if subj_el is not None:
                subject_raw = (subj_el.text or "").strip()

    # HTML: NodeValue truncates at ~1024 chars — always read from content/html/source CDATA
    html_raw = ""
    content_el = _find(delivery_el, "content")
    if content_el is not None:
        html_el = _find(content_el, "html")
        if html_el is not None:
            src_el = _find(html_el, "source")
            if src_el is not None:
                html_raw = (src_el.text or "").strip()

    # Text: read from content/text/source CDATA
    text_raw = ""
    if content_el is not None:
        text_el = _find(content_el, "text") or _find(content_el, "textContent")
        if text_el is not None:
            src_el = _find(text_el, "source")
            text_raw = (src_el.text if src_el is not None else (text_el.get("source", "") or text_el.text or "")).strip()

    sms_raw = text_raw if channel == "sms" else ""

    return {
        "id": delivery_el.get("id", ""),
        "internalName": delivery_el.get("internalName", ""),
        "label": delivery_el.get("label", delivery_el.get("_cs", "")),
        "messageType": msg_type,
        "channel": channel,
        "lastModified": delivery_el.get("lastModified", ""),
        "description": description,
        "subjectRaw": subject_raw,
        "htmlRaw": html_raw,
        "textRaw": text_raw,
        "smsRaw": sms_raw,
        "rawXml": ET.tostring(delivery_el, encoding="unicode"),
    }


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


def _find(el: ET.Element, local_tag: str) -> Optional[ET.Element]:
    """Find first direct child by local tag name, ignoring XML namespace."""
    for child in el:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == local_tag:
            return child
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
