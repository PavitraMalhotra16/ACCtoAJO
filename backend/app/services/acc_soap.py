import httpx
import xml.etree.ElementTree as ET

DEFAULT_INSTANCE_URL = "http://localhost:8080"


def _soap_url(instance_url: str) -> str:
    return f"{instance_url.rstrip('/')}/nl/jsp/soaprouter.jsp"


def _check_fault(root: ET.Element) -> None:
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or ""
        detail_el = fault.find("detail")
        detail = ET.tostring(detail_el, encoding="unicode") if detail_el is not None else ""
        raise ValueError(f"SOAP fault: {fault_string} | {detail}")


def _classic_header_block(session_token: str, security_token: str) -> str:
    return f"""  <soapenv:Header>
    <Cookie xmlns="urn:xtk:session">__sessiontoken={session_token}</Cookie>
    <X-Security-Token xmlns="urn:xtk:session">{security_token}</X-Security-Token>
  </soapenv:Header>"""


def _http_headers(action: str, ims_token: str | None = None) -> dict:
    h = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": action}
    if ims_token:
        h["Authorization"] = f"Bearer {ims_token}"
    return h


def logon(login: str, password: str, instance_url: str = DEFAULT_INSTANCE_URL) -> tuple[str, str]:
    """Classic login — returns (session_token, security_token)."""
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
        response = client.post(
            _soap_url(instance_url),
            content=envelope.encode("utf-8"),
            headers=_http_headers("xtk:session#Logon"),
        )

    root = ET.fromstring(response.text)
    _check_fault(root)

    session_token_el = root.find(".//{urn:xtk:session}pstrSessionToken")
    if session_token_el is None:
        raise ValueError("No session token returned from ACC SOAP Logon")

    security_token_el = root.find(".//{urn:xtk:session}pstrSecurityToken")
    security_token = security_token_el.text if security_token_el is not None else ""
    return (session_token_el.text or "", security_token)


def get_schemas(
    session_token: str | None,
    security_token: str | None,
    instance_url: str = DEFAULT_INSTANCE_URL,
    ims_token: str | None = None,
) -> list[dict]:
    if ims_token:
        header_block = "  <soapenv:Header/>"
        body_session = ""
    else:
        header_block = _classic_header_block(session_token, security_token)
        body_session = session_token

    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">
{header_block}
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>{body_session}</urn:sessiontoken>
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
        response = client.post(
            _soap_url(instance_url),
            content=envelope.encode("utf-8"),
            headers=_http_headers("xtk:queryDef#ExecuteQuery", ims_token),
        )

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


def get_schema_detail(
    session_token: str | None,
    security_token: str | None,
    namespace: str,
    name: str,
    instance_url: str = DEFAULT_INSTANCE_URL,
    ims_token: str | None = None,
) -> dict:
    if ims_token:
        header_block = "  <soapenv:Header/>"
        body_session = ""
    else:
        header_block = _classic_header_block(session_token, security_token)
        body_session = session_token

    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">
{header_block}
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>{body_session}</urn:sessiontoken>
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
        response = client.post(
            _soap_url(instance_url),
            content=envelope.encode("utf-8"),
            headers=_http_headers("xtk:queryDef#ExecuteQuery", ims_token),
        )

    root = ET.fromstring(response.text)
    _check_fault(root)

    schema_el = None
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == "data":
            for child in el:
                child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_local in ("srcSchema", "schema"):
                    schema_el = child
                    break
            if schema_el is None and el.text and el.text.strip():
                try:
                    schema_el = ET.fromstring(el.text.strip())
                except Exception:
                    pass
            break

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
    def parse_element(el: ET.Element) -> dict:
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        result: dict = {"tag": local, "attrs": dict(el.attrib), "children": []}
        for child in el:
            child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_local in ("element", "attribute", "key", "join", "condition",
                               "compute-string", "dbindex", "methods", "method",
                               "parameters", "param"):
                result["children"].append(parse_element(child))
        return result

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

    elements = []
    attributes = []
    others = []

    for child in schema_el:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "element":
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
