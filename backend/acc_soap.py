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
    """
    Build the xtk:session#Logon SOAP envelope.

    Exact envelope sent:

        <?xml version="1.0" encoding="UTF-8"?>
        <soapenv:Envelope
            xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:urn="urn:xtk:session">
          <soapenv:Header/>
          <soapenv:Body>
            <urn:Logon>
              <urn:sessiontoken/>
              <urn:strLogin>LOGIN_ID</urn:strLogin>
              <urn:strPassword>PASSWORD</urn:strPassword>
              <urn:elemParameters/>
            </urn:Logon>
          </soapenv:Body>
        </soapenv:Envelope>
    """
    # Use manual string building to avoid any library silently stringifying creds
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


def build_test_cnx_envelope(session_token: str, security_token: str) -> bytes:
    """
    Build the xtk:session#TestCnx SOAP envelope.

    The tokens are placed in the SOAP header as ACC expects.

    Exact envelope:

        <?xml version="1.0" encoding="UTF-8"?>
        <soapenv:Envelope
            xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
            xmlns:urn="urn:xtk:session">
          <soapenv:Header>
            <urn:SecurityHeader>
              <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
              <urn:securityToken>SECURITY_TOKEN</urn:securityToken>
            </urn:SecurityHeader>
          </soapenv:Header>
          <soapenv:Body>
            <urn:TestCnx>
              <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
            </urn:TestCnx>
          </soapenv:Body>
        </soapenv:Envelope>
    """
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
    """
    Build an xtk:queryDef#ExecuteQuery envelope.

    Example (nms:recipient, first 5 rows):

        <urn:ExecuteQuery>
          <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
          <urn:entity>
            <queryDef schema="nms:recipient" operation="select">
              <select>
                <node expr="@firstName"/>
                <node expr="@lastName"/>
                <node expr="@email"/>
              </select>
              <where>
                <condition expr="@email != ''"/>
              </where>
            </queryDef>
          </urn:entity>
        </urn:ExecuteQuery>
    """
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


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def parse_logon_response(xml_text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (session_token, security_token) from a successful Logon response.

    Expected fragment:
        <LogonResponse>
          <pstrSessionToken>SESSION_TOKEN</pstrSessionToken>
          <pstrSecurityToken>SECURITY_TOKEN</pstrSecurityToken>
        </LogonResponse>
    """
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

    # ACC sometimes returns tokens without a namespace prefix
    if not session_token:
        session_token = _find_text(root, [".//sessionToken", ".//SessionToken"])
    if not security_token:
        security_token = _find_text(root, [".//securityToken", ".//SecurityToken"])

    return session_token, security_token


def build_list_schemas_envelope(session_token: str, security_token: str) -> bytes:
    """
    Query all xtk:schema entries using xtk:queryDef#ExecuteQuery.

    Returns schemas with @namespace, @name, @label, @labelSingular.
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
        '<queryDef schema="xtk:schema" operation="select" lineCount="200" startLine="0">'
        "<select>"
        '<node expr="@namespace"/>'
        '<node expr="@name"/>'
        '<node expr="@label"/>'
        '<node expr="@labelSingular"/>'
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


def parse_schemas(xml_text: str) -> list[dict]:
    """
    Parse the ExecuteQuery response for xtk:schema into a list of dicts:
      [{ namespace, name, label, labelSingular }, ...]
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.error("Failed to parse schemas XML: %s", exc)
        return []

    results = []
    # ACC wraps rows in <schema .../> elements inside the response collection
    for el in root.iter():
        if el.tag in ("schema", "{urn:xtk:schema}schema") or el.tag.endswith("}schema"):
            ns = el.get("namespace") or el.get("@namespace", "")
            name = el.get("name") or el.get("@name", "")
            label = el.get("label") or el.get("@label", "")
            label_singular = el.get("labelSingular") or el.get("@labelSingular", "")
            if name:
                results.append({
                    "namespace": ns,
                    "name": name,
                    "label": label,
                    "labelSingular": label_singular,
                })
    return results


def parse_fault(xml_text: str) -> Optional[str]:
    """
    Return the SOAP fault string if present, otherwise None.

    SOAP fault structure:
        <soapenv:Fault>
          <faultcode>...</faultcode>
          <faultstring>Human-readable message</faultstring>
        </soapenv:Fault>
    """
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
    """Try each XPath in order; return the first non-empty text found."""
    for path in paths:
        el = root.find(path)
        if el is not None and el.text:
            return el.text.strip()
    return None


def _xml_escape(value: str) -> str:
    """Minimal XML escaping for attribute values and text content."""
    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
