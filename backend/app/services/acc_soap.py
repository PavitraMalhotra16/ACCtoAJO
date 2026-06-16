import httpx
import xml.etree.ElementTree as ET

ACC_SOAP_URL = "http://localhost:8080/nl/jsp/soaprouter.jsp"


def _soap_headers(session_token: str, security_token: str) -> dict:
    return {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "",
    }


def _check_fault(root: ET.Element) -> None:
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or ""
        detail_el = fault.find("detail")
        detail = ET.tostring(detail_el, encoding="unicode") if detail_el is not None else ""
        raise ValueError(f"SOAP fault: {fault_string} | {detail}")


def _header_block(session_token: str, security_token: str) -> str:
    return f"""  <soapenv:Header>
    <Cookie xmlns="urn:xtk:session">__sessiontoken={session_token}</Cookie>
    <X-Security-Token xmlns="urn:xtk:session">{security_token}</X-Security-Token>
  </soapenv:Header>"""


def logon(login: str, password: str) -> tuple[str, str]:
    """Returns (session_token, security_token)."""
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:session">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:Logon>
      <urn:sessiontoken></urn:sessiontoken>
      <urn:strLogin>{login}</urn:strLogin>
      <urn:strPassword>{password}</urn:strPassword>
      <urn:elemParameters></urn:elemParameters>
    </urn:Logon>
  </soapenv:Body>
</soapenv:Envelope>"""

    with httpx.Client(timeout=30.0) as client:
        response = client.post(ACC_SOAP_URL, content=envelope.encode("utf-8"), headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "xtk:session#Logon",
        })

    root = ET.fromstring(response.text)
    _check_fault(root)

    session_token_el = root.find(".//{urn:xtk:session}pstrSessionToken")
    if session_token_el is None:
        raise ValueError("No session token returned from ACC SOAP Logon")

    security_token_el = root.find(".//{urn:xtk:session}pstrSecurityToken")
    security_token = security_token_el.text if security_token_el is not None else ""

    return (session_token_el.text or "", security_token or "")


def get_schemas(session_token: str, security_token: str) -> list[dict]:
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">
{_header_block(session_token, security_token)}
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>{session_token}</urn:sessiontoken>
      <urn:entity>
        <queryDef schema="xtk:schema" operation="select" lineCount="9999">
          <select>
            <node expr="@namespace"/>
            <node expr="@name"/>
            <node expr="@label"/>
          </select>
          <orderBy>
            <node expr="@namespace"/>
            <node expr="@name"/>
          </orderBy>
        </queryDef>
      </urn:entity>
    </urn:ExecuteQuery>
  </soapenv:Body>
</soapenv:Envelope>"""

    with httpx.Client(timeout=30.0) as client:
        response = client.post(ACC_SOAP_URL, content=envelope.encode("utf-8"), headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "xtk:queryDef#ExecuteQuery",
        })

    root = ET.fromstring(response.text)
    _check_fault(root)

    schemas = []
    for el in root.iter():
        if el.tag in ("schema", "{urn:xtk:queryDef}schema"):
            name = el.get("name", "")
            namespace = el.get("namespace", "")
            if name and namespace:
                schemas.append({
                    "namespace": namespace,
                    "name": name,
                    "label": el.get("label", "") or el.get("_cs", ""),
                })

    return schemas


def get_schema_detail(session_token: str, security_token: str, namespace: str, name: str) -> dict:
    """Fetch schema structure by querying nested element/attribute paths via xtk:schema."""
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">
{_header_block(session_token, security_token)}
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>{session_token}</urn:sessiontoken>
      <urn:entity>
        <queryDef xtkschema="xtk:queryDef" schema="xtk:srcSchema" operation="get">
          <select>
            <node expr="@namespace"/>
            <node expr="@name"/>
            <node expr="@label"/>
            <node expr="data"/>
          </select>
          <where>
            <condition expr="@namespace = &apos;{namespace}&apos;"/>
            <condition expr="@name = &apos;{name}&apos;"/>
          </where>
        </queryDef>
      </urn:entity>
    </urn:ExecuteQuery>
  </soapenv:Body>
</soapenv:Envelope>"""

    with httpx.Client(timeout=30.0) as client:
        response = client.post(ACC_SOAP_URL, content=envelope.encode("utf-8"), headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "xtk:queryDef#ExecuteQuery",
        })

    print("=== SCHEMA DETAIL RESPONSE ===")
    print(response.text[:4000])
    print("==============================")

    root = ET.fromstring(response.text)
    _check_fault(root)

    # The schema XML lives inside a <data> element in the response
    schema_el = None

    # First: look for <data> containing srcSchema/schema XML
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == "data":
            # The actual schema XML is a child of <data>
            for child in el:
                child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_local in ("srcSchema", "schema"):
                    schema_el = child
                    break
            if schema_el is None and el.text and el.text.strip():
                # data might be a text blob — parse it
                try:
                    inner = ET.fromstring(el.text.strip())
                    schema_el = inner
                except Exception:
                    pass
            break

    # Fallback: direct srcSchema/schema element anywhere
    if schema_el is None:
        for el in root.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if local in ("srcSchema", "schema") and el.get("name") == name:
                schema_el = el
                break

    if schema_el is None:
        raise ValueError(f"Schema {namespace}:{name} not found in response")

    return _parse_schema_element(schema_el)


def _parse_schema_element(schema_el: ET.Element) -> dict:
    """Recursively parse a schema XML element into a structured dict."""

    def parse_element(el: ET.Element) -> dict:
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        result: dict = {
            "tag": local,
            "attrs": {k: v for k, v in el.attrib.items()},
            "children": [],
        }
        for child in el:
            child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_local in ("element", "attribute", "key", "join", "condition", "compute-string", "dbindex", "methods", "method", "parameters", "param"):
                result["children"].append(parse_element(child))
        return result

    elements = []
    attributes = []
    others = []

    # attributes can be at top level or nested inside the main <element>
    def extract_attrs(el: ET.Element) -> list[dict]:
        result = []
        for child in el:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "attribute":
                result.append({
                    "name": child.get("name", ""),
                    "type": child.get("type", ""),
                    "label": child.get("label", ""),
                    "length": child.get("length", ""),
                    "required": child.get("required", ""),
                    "enum": child.get("enum", ""),
                    "desc": child.get("desc", ""),
                })
        return result

    for child in schema_el:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "element":
            # collect attributes from inside the main element
            inner_attrs = extract_attrs(child)
            if inner_attrs:
                attributes.extend(inner_attrs)
            elements.append(parse_element(child))
        elif local == "attribute":
            attributes.append({
                "name": child.get("name", ""),
                "type": child.get("type", ""),
                "label": child.get("label", ""),
                "length": child.get("length", ""),
                "required": child.get("required", ""),
                "enum": child.get("enum", ""),
                "desc": child.get("desc", ""),
            })
        elif local not in ("createdBy", "modifiedBy"):
            others.append(parse_element(child))

    return {
        "namespace": schema_el.get("namespace", ""),
        "name": schema_el.get("name", ""),
        "label": schema_el.get("label", ""),
        "labelSingular": schema_el.get("labelSingular", ""),
        "desc": schema_el.get("desc", ""),
        "img": schema_el.get("img", ""),
        "elements": elements,
        "attributes": attributes,
        "others": others,
    }
