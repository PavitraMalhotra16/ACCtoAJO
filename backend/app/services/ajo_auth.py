import base64
import json
import httpx

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
AJO_JOURNEYS_URL = "https://cjm.adobe.io/imp/journeys"


def get_ims_token(client_id: str, client_secret: str, org_id: str) -> str:
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "openid,AdobeID",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            IMS_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

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
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Authorization": f"Bearer {access_token}",
        "X-Api-Key": client_id,
        "x-gw-ims-org-id": org_id,
        "x-sandbox-name": sandbox_name,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(AJO_JOURNEYS_URL, headers=headers, params={"limit": 1})

    if response.status_code == 200:
        return True

    if response.status_code in (401, 403):
        try:
            body = response.json()
            detail = body.get("title") or body.get("detail") or body.get("message") or response.text
        except Exception:
            detail = response.text
        raise ValueError(f"AJO access denied ({response.status_code}): {detail}")

    raise ValueError(f"AJO verification failed with status {response.status_code}: {response.text}")


def decode_jwt_claims(token: str) -> dict:
    """Decode JWT payload without verifying signature."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}")


def compare_token_claims(generated_token: str, reference_token: str) -> None:
    """Raise ValueError if client_id or org don't match between tokens."""
    gen = decode_jwt_claims(generated_token)
    ref = decode_jwt_claims(reference_token)

    if gen.get("client_id") != ref.get("client_id"):
        raise ValueError(
            f"client_id mismatch: credentials produced '{gen.get('client_id')}' "
            f"but reference token has '{ref.get('client_id')}'"
        )
    if gen.get("org") != ref.get("org"):
        raise ValueError(
            f"org mismatch: credentials produced '{gen.get('org')}' "
            f"but reference token has '{ref.get('org')}'"
        )
