import httpx
import xml.etree.ElementTree as ET

ACC_SOAP_URL = "http://localhost:8080/nl/jsp/soaprouter.jsp"

SOAP_NS = {
    "soapenv": "http://schemas.xmlsoap.org/soap/envelope/",
    "urn": "urn:xtk:session",
}


def logon(login: str, password: str) -> str:
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

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:session#Logon",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(ACC_SOAP_URL, content=envelope.encode("utf-8"), headers=headers)

    root = ET.fromstring(response.text)

    # Check for SOAP fault
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or "Unknown SOAP fault"
        raise ValueError(f"SOAP fault: {fault_string}")

    # Extract session token
    token_el = root.find(".//{urn:xtk:session}pstrSessionToken")
    if token_el is None:
        raise ValueError("No session token returned from ACC SOAP Logon")

    return token_el.text or ""


def get_schemas(session_token: str) -> list[dict]:
    envelope = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:xtk:queryDef">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>{session_token}</urn:sessiontoken>
      <urn:entity>
        <queryDef schema="xtk:schema" operation="select">
          <select>
            <node expr="@namespace"/>
            <node expr="@name"/>
            <node expr="@label"/>
            <node expr="@labelSingular"/>
          </select>
        </queryDef>
      </urn:entity>
    </urn:ExecuteQuery>
  </soapenv:Body>
</soapenv:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "xtk:queryDef#ExecuteQuery",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(ACC_SOAP_URL, content=envelope.encode("utf-8"), headers=headers)

    root = ET.fromstring(response.text)

    # Check for SOAP fault
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        fault_string = fault.findtext("faultstring") or "Unknown SOAP fault"
        raise ValueError(f"SOAP fault: {fault_string}")

    schemas = []
    # Schema elements are returned as <schema> elements inside the response
    for schema_el in root.iter("schema"):
        schemas.append(
            {
                "namespace": schema_el.get("namespace", ""),
                "name": schema_el.get("name", ""),
                "label": schema_el.get("label", ""),
                "labelSingular": schema_el.get("labelSingular", ""),
            }
        )

    return schemas
