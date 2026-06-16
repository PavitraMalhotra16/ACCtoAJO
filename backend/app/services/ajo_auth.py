import base64
import json
import httpx

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"


def get_ims_token(client_id: str, client_secret: str, org_id: str = "", scope: str = "openid,AdobeID") -> tuple[str, int]:
    """Returns (access_token, expires_in_seconds)."""
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope or "openid,AdobeID",
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

    expires_in = int(body.get("expires_in", 86400))
    return access_token, expires_in


def verify_ajo_access(access_token: str, client_id: str, org_id: str, sandbox_name: str) -> bool:
    """Verify AJO credentials by checking JWT claims match the provided client_id and org_id."""
    claims = decode_jwt_claims(access_token)

    token_client_id = claims.get("client_id") or claims.get("azp") or ""
    token_org = claims.get("org") or ""

    if token_client_id and token_client_id != client_id:
        raise ValueError(
            f"Token client_id '{token_client_id}' does not match provided client_id '{client_id}'"
        )

    # org_id in token is typically without the @AdobeOrg suffix
    org_id_short = org_id.replace("@AdobeOrg", "")
    if token_org and token_org != org_id and token_org != org_id_short:
        raise ValueError(
            f"Token org '{token_org}' does not match provided org_id '{org_id}'"
        )

    return True


def decode_jwt_claims(token: str) -> dict:
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}")


def compare_token_claims(generated_token: str, reference_token: str) -> None:
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
