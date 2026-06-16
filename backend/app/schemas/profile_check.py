"""Pydantic request/response models for the AJO profile-presence check."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProfileCheckRequest(BaseModel):
    """
    Payload sent from the UI form.

    Credentials are optional: if omitted, the backend falls back to the values
    loaded from the .env file. Any provided value overrides the .env default.
    """

    # --- credentials (optional; default to .env) ---
    ims_org_id: str | None = Field(None, description="IMS Org ID, e.g. XXXX@AdobeOrg")
    sandbox_name: str | None = Field(None, description="AEP/AJO sandbox name, e.g. 'prod'")
    client_id: str | None = Field(None, description="Client ID (API key) from Developer Console")
    client_secret: str | None = Field(None, description="Client Secret from Developer Console")

    # --- which user to look for ---
    entity_id: str = Field(..., description="Identity value, e.g. an email address")
    namespace: str = Field(
        "email",
        description="Identity namespace code, e.g. 'email', 'ECID', 'phone'.",
    )

    # --- optional overrides for non-default regions ---
    scopes: str | None = Field(None, description="Override OAuth scopes if needed.")
    ims_token_url: str | None = Field(None, description="Override IMS token endpoint.")
    aep_base_url: str | None = Field(None, description="Override AEP gateway base URL.")


class TokenRequest(BaseModel):
    """Payload for generating an IMS access token from the UI."""

    ims_org_id: str | None = Field(None, description="IMS Org ID, e.g. XXXX@AdobeOrg")
    client_id: str | None = Field(None, description="Client ID (API key)")
    client_secret: str | None = Field(None, description="Client Secret")
    scopes: str | None = Field(None, description="Override OAuth scopes if needed.")
    ims_token_url: str | None = Field(None, description="Override IMS token endpoint.")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int  # seconds until expiry
    ims_org_id: str


class ValidateUserRequest(BaseModel):
    """Credentials entered in the UI to validate the user."""

    ims_org_id: str | None = Field(None, description="IMS Org ID, e.g. XXXX@AdobeOrg")
    client_id: str | None = Field(None, description="Client ID (API key)")
    client_secret: str | None = Field(None, description="Client Secret")


class ValidateUserResponse(BaseModel):
    """Result of the validation. The access token is deliberately NOT returned."""

    valid: bool
    message: str


class ProfileCheckResponse(BaseModel):
    present: bool
    entity_id: str
    namespace: str
    message: str
    # Only included when a profile is found.
    entity: dict | None = None
