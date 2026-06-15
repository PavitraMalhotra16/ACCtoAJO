import httpx

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
AEP_SCHEMA_URL = "https://platform.adobe.io/data/foundation/schemaregistry/global/classes"


def get_ims_token(client_id: str, client_secret: str, org_id: str) -> str:
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "openid,AdobeID,adobeio_api,read_organizations,additional_info.projectedProductContext",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(IMS_TOKEN_URL, data=data)

    body = response.json()

    if response.status_code != 200:
        error_msg = body.get("error_description") or body.get("error") or response.text
        raise ValueError(f"IMS token error: {error_msg}")

    access_token = body.get("access_token")
    if not access_token:
        raise ValueError("No access_token in IMS response")

    return access_token


def verify_ajo_access(access_token: str, client_id: str, org_id: str, sandbox_name: str) -> bool:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": client_id,
        "x-gw-ims-org-id": org_id,
        "x-sandbox-name": sandbox_name,
    }
    params = {"orderby": "title", "limit": 1}

    with httpx.Client(timeout=30.0) as client:
        response = client.get(AEP_SCHEMA_URL, headers=headers, params=params)

    if response.status_code == 200:
        return True

    if response.status_code in (401, 403):
        try:
            detail = response.json().get("title") or response.json().get("detail") or response.text
        except Exception:
            detail = response.text
        raise ValueError(f"AJO access denied ({response.status_code}): {detail}")

    raise ValueError(f"AJO verification failed with status {response.status_code}: {response.text}")
