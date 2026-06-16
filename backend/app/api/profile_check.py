"""
API route: check whether a user/profile is present in AJO (AEP Profile store).

The UI POSTs credentials + an identity to look up; the route authenticates
against IMS and queries the AEP Real-Time Customer Profile access endpoint,
returning a simple present/not-present result.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.schemas.profile_check import (
    ProfileCheckRequest,
    ProfileCheckResponse,
    TokenRequest,
    TokenResponse,
    ValidateUserRequest,
    ValidateUserResponse,
)
from app.services.ajo_profile_lookup import (
    AJOCredentials,
    AJOLookupError,
    AJOProfileClient,
    fetch_ims_token,
    tokens_identify_same_user,
)

router = APIRouter(prefix="/api/ajo", tags=["ajo"])


@router.post("/validate-user", response_model=ValidateUserResponse)
def validate_user(req: ValidateUserRequest) -> ValidateUserResponse:
    """
    Generate an access token from the entered credentials and validate it
    against the reference access token (from .env).

    Validation compares the token identity claims (org, client_id, user_id);
    the generated token is never returned to the client.
    """
    client_id = req.client_id or settings.client_id
    client_secret = req.client_secret or settings.client_secret
    ims_org_id = req.ims_org_id or settings.ims_org_id

    missing = [
        name
        for name, value in [
            ("client_id", client_id),
            ("client_secret", client_secret),
            ("ims_org_id", ims_org_id),
        ]
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing credentials (not in request or .env): {', '.join(missing)}",
        )

    if not settings.reference_access_token:
        raise HTTPException(
            status_code=500,
            detail="No reference access token configured (AJO_REFERENCE_ACCESS_TOKEN).",
        )

    # Step 1: mint a token from the entered credentials.
    try:
        payload = fetch_ims_token(
            client_id=client_id,
            client_secret=client_secret,
            scopes=settings.scopes,
            ims_token_url=settings.ims_token_url,
        )
    except AJOLookupError:
        # Bad credentials never mint a token -> not a valid user.
        return ValidateUserResponse(
            valid=False,
            message="Invalid credentials — could not generate an access token.",
        )

    generated_token = payload["access_token"]

    # Step 2: compare identity claims against the reference token.
    same_user = tokens_identify_same_user(generated_token, settings.reference_access_token)

    if same_user:
        return ValidateUserResponse(valid=True, message="Valid user")
    return ValidateUserResponse(
        valid=False,
        message="Credentials are valid but do not match the expected user.",
    )


@router.post("/token", response_model=TokenResponse)
def generate_token(req: TokenRequest) -> TokenResponse:
    """
    Generate an IMS access token from Org ID + Client ID + Client Secret.

    Credentials come from the request body when present, otherwise from .env.
    The token is minted by IMS from the client credentials + scopes; the Org ID
    is captured for context and echoed back (it is not part of the IMS call).
    """
    client_id = req.client_id or settings.client_id
    client_secret = req.client_secret or settings.client_secret
    ims_org_id = req.ims_org_id or settings.ims_org_id

    missing = [
        name
        for name, value in [
            ("client_id", client_id),
            ("client_secret", client_secret),
            ("ims_org_id", ims_org_id),
        ]
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing credentials (not in request or .env): {', '.join(missing)}",
        )

    try:
        payload = fetch_ims_token(
            client_id=client_id,
            client_secret=client_secret,
            scopes=req.scopes or settings.scopes,
            ims_token_url=req.ims_token_url or settings.ims_token_url,
        )
    except AJOLookupError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": exc.message, "upstream_status": exc.status_code, "detail": exc.detail},
        ) from exc

    return TokenResponse(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "bearer"),
        expires_in=int(payload.get("expires_in", 0)),
        ims_org_id=ims_org_id,
    )


@router.post("/profile-check", response_model=ProfileCheckResponse)
def check_profile_presence(req: ProfileCheckRequest) -> ProfileCheckResponse:
    """
    Return whether a profile with the given identity exists in AJO/AEP.

    Credentials come from the request body when present, otherwise from the
    .env file (loaded via app.config.settings).
    """
    client_id = req.client_id or settings.client_id
    client_secret = req.client_secret or settings.client_secret
    ims_org_id = req.ims_org_id or settings.ims_org_id

    missing = [
        name
        for name, value in [
            ("client_id", client_id),
            ("client_secret", client_secret),
            ("ims_org_id", ims_org_id),
        ]
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing credentials (not in request or .env): {', '.join(missing)}",
        )

    creds = AJOCredentials(
        ims_org_id=ims_org_id,
        sandbox_name=req.sandbox_name or settings.sandbox_name,
        client_id=client_id,
        client_secret=client_secret,
        scopes=req.scopes or settings.scopes,
        ims_token_url=req.ims_token_url or settings.ims_token_url,
        aep_base_url=req.aep_base_url or settings.aep_base_url,
    )

    client = AJOProfileClient(creds)

    try:
        result = client.lookup_profile(req.entity_id, req.namespace)
    except AJOLookupError as exc:
        # Surface auth / API failures as a 502 so the UI can distinguish them
        # from a clean "profile not found".
        raise HTTPException(
            status_code=502,
            detail={"message": exc.message, "upstream_status": exc.status_code, "detail": exc.detail},
        ) from exc

    return ProfileCheckResponse(
        present=result.present,
        entity_id=result.entity_id,
        namespace=result.namespace,
        message=result.message,
        entity=result.entity,
    )
