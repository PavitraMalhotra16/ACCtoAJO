"""
AJO / AEP profile-presence lookup.

Adobe Journey Optimizer (AJO) does not store profiles in its own database. AJO
sits on top of the Adobe Experience Platform (AEP) Real-Time Customer Profile
store. So "is this user present in AJO?" is answered by querying the AEP
Real-Time Customer Profile *access entities* endpoint with an identity
(entityId + namespace).

Two REST calls are involved:

1. Fetch an IMS access token (OAuth Server-to-Server / client_credentials)
       POST https://ims-na1.adobelogin.com/ims/token/v3

2. Look the profile up by identity
       GET  https://platform.adobe.io/data/core/ups/access/entities
            ?schema.name=_xdm.context.profile&entityId=<id>&entityIdNS=<namespace>

Docs:
- Profile access entities API:
  https://experienceleague.adobe.com/en/docs/experience-platform/profile/api/entities
- OAuth Server-to-Server:
  https://developer.adobe.com/developer-console/docs/guides/authentication/ServerToServerAuthentication/
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass, field

import httpx

# Default endpoints. These are overridable so the same code works against
# other IMS regions (e.g. ims-na1 / ims-emea1) and AEP gateways.
DEFAULT_IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
DEFAULT_AEP_BASE_URL = "https://platform.adobe.io"
PROFILE_SCHEMA_NAME = "_xdm.context.profile"

# Scopes required for an OAuth Server-to-Server credential to read Profile data.
# These are the scopes attached to the credential in the Adobe Developer Console.
DEFAULT_SCOPES = (
    "openid,AdobeID,read_organizations,"
    "additional_info.projectedProductContext,session"
)


def decode_jwt_claims(token: str) -> dict:
    """
    Decode the payload (claims) of a JWT *without* verifying the signature.

    Used to compare the identity claims of two IMS access tokens. Returns an
    empty dict if the token is not a well-formed JWT.
    """
    try:
        payload_segment = token.split(".")[1]
        # base64url, padded to a multiple of 4.
        padded = payload_segment + "=" * (-len(payload_segment) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        return json.loads(decoded)
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return {}


# The claims that identify *who* a token belongs to. Volatile claims (id,
# created_at, expires_in, signature) are intentionally excluded — two tokens
# minted from the same credentials differ in those but share these.
IDENTITY_CLAIMS = ("org", "client_id", "user_id")


def tokens_identify_same_user(token_a: str, token_b: str) -> bool:
    """True when both tokens carry the same org + client_id + user_id claims."""
    a = decode_jwt_claims(token_a)
    b = decode_jwt_claims(token_b)
    if not a or not b:
        return False
    return all(a.get(c) and a.get(c) == b.get(c) for c in IDENTITY_CLAIMS)


def fetch_ims_token(
    client_id: str,
    client_secret: str,
    scopes: str = DEFAULT_SCOPES,
    ims_token_url: str = DEFAULT_IMS_TOKEN_URL,
    timeout: float = 30.0,
) -> dict:
    """
    Exchange client credentials for an IMS access token (OAuth Server-to-Server).

    Returns the raw IMS JSON payload: {access_token, token_type, expires_in}.
    Raises AJOLookupError on failure.
    """
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(
            ims_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scopes,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise AJOLookupError(
            "Failed to obtain IMS access token. Check Client ID, Client Secret "
            "and the credential's scopes.",
            status_code=resp.status_code,
            detail=_safe_json(resp),
        )

    payload = resp.json()
    if not payload.get("access_token"):
        raise AJOLookupError(
            "IMS token response did not contain an access_token.",
            status_code=resp.status_code,
            detail=payload,
        )
    return payload


@dataclass
class AJOCredentials:
    """Credentials collected from the UI."""

    ims_org_id: str  # e.g. "1234567890ABCDEF12345678@AdobeOrg"
    sandbox_name: str  # e.g. "prod" or "dev"
    client_id: str  # API key from Adobe Developer Console
    client_secret: str
    scopes: str = DEFAULT_SCOPES
    ims_token_url: str = DEFAULT_IMS_TOKEN_URL
    aep_base_url: str = DEFAULT_AEP_BASE_URL


@dataclass
class ProfileLookupResult:
    """Outcome of a presence check."""

    present: bool
    entity_id: str
    namespace: str
    message: str
    # Raw matched entity payload (only populated when present), useful for the UI.
    entity: dict | None = field(default=None)


class AJOLookupError(Exception):
    """Raised when authentication or the lookup call fails for a non-404 reason."""

    def __init__(self, message: str, status_code: int | None = None, detail: object = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.detail = detail


class AJOProfileClient:
    """
    Thin client that authenticates against IMS and queries the AEP
    Real-Time Customer Profile access endpoint.

    Tokens are cached in-memory for the life of the instance and refreshed
    automatically a little before expiry. Tokens are never persisted.
    """

    # Refresh the token this many seconds before its real expiry, to avoid
    # racing an expiry boundary mid-request.
    _TOKEN_EXPIRY_SKEW = 60

    def __init__(self, credentials: AJOCredentials, timeout: float = 30.0):
        self._creds = credentials
        self._timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ----------------------------------------------------------------- auth

    def _fetch_token(self, client: httpx.Client) -> str:
        """Exchange client credentials for an IMS Bearer access token."""
        resp = client.post(
            self._creds.ims_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._creds.client_id,
                "client_secret": self._creds.client_secret,
                "scope": self._creds.scopes,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            raise AJOLookupError(
                "Failed to obtain IMS access token. Check Client ID, Client "
                "Secret, Org ID and the credential's scopes.",
                status_code=resp.status_code,
                detail=_safe_json(resp),
            )

        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise AJOLookupError(
                "IMS token response did not contain an access_token.",
                status_code=resp.status_code,
                detail=payload,
            )

        # `expires_in` is documented in seconds (v3) — older responses use ms.
        expires_in = int(payload.get("expires_in", 3600))
        if expires_in > 86_400:  # almost certainly milliseconds
            expires_in //= 1000
        self._token_expires_at = time.monotonic() + expires_in - self._TOKEN_EXPIRY_SKEW
        self._token = token
        return token

    def _get_token(self, client: httpx.Client) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        return self._fetch_token(client)

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self._creds.client_id,
            "x-gw-ims-org-id": self._creds.ims_org_id,
            "x-sandbox-name": self._creds.sandbox_name,
            "Accept": "application/json",
        }

    # -------------------------------------------------------------- lookup

    def lookup_profile(self, entity_id: str, namespace: str) -> ProfileLookupResult:
        """
        Check whether a profile identified by (entity_id, namespace) exists.

        Args:
            entity_id: the identity value, e.g. "jane@example.com" or a CRM id.
            namespace: the identity namespace code, e.g. "email", "ECID",
                       "phone", or a custom namespace code.

        Returns:
            ProfileLookupResult with `present` set accordingly.

        Raises:
            AJOLookupError: on auth failure or unexpected API errors.
        """
        if not entity_id or not namespace:
            raise AJOLookupError("Both entity_id and namespace are required.")

        url = f"{self._creds.aep_base_url}/data/core/ups/access/entities"
        params = {
            "schema.name": PROFILE_SCHEMA_NAME,
            "entityId": entity_id,
            "entityIdNS": namespace,
        }

        with httpx.Client(timeout=self._timeout) as client:
            token = self._get_token(client)
            resp = client.get(url, params=params, headers=self._auth_headers(token))

            # A profile that doesn't exist returns 404, not an error condition.
            if resp.status_code == 404:
                return ProfileLookupResult(
                    present=False,
                    entity_id=entity_id,
                    namespace=namespace,
                    message="No profile found for this identity in the given sandbox.",
                )

            if resp.status_code != 200:
                raise AJOLookupError(
                    f"Profile lookup failed (HTTP {resp.status_code}).",
                    status_code=resp.status_code,
                    detail=_safe_json(resp),
                )

            body = resp.json()

        # The access endpoint returns {"<entityId>": {"entityId": ..., "entity": {...}}}.
        # An empty `data`/empty object means no matching profile.
        records = body.get("data") if isinstance(body, dict) else None
        if records is None and isinstance(body, dict):
            # Some responses key results directly by entity id rather than under "data".
            records = {k: v for k, v in body.items() if k not in ("_page", "_links")}

        matched_entity = _first_non_empty_entity(records)

        if matched_entity is not None:
            return ProfileLookupResult(
                present=True,
                entity_id=entity_id,
                namespace=namespace,
                message="Profile found.",
                entity=matched_entity,
            )

        return ProfileLookupResult(
            present=False,
            entity_id=entity_id,
            namespace=namespace,
            message="No profile found for this identity in the given sandbox.",
        )


# --------------------------------------------------------------------- helpers


def _safe_json(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except Exception:
        return resp.text


def _first_non_empty_entity(records: object) -> dict | None:
    """Extract the first real entity payload from the access-entities response."""
    if not records:
        return None
    if isinstance(records, dict):
        for value in records.values():
            if isinstance(value, dict):
                entity = value.get("entity", value)
                if entity:  # non-empty dict means a profile exists
                    return entity
    return None
