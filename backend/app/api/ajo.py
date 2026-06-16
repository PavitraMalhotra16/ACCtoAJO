import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.crypto import encrypt, decrypt
from app.db import get_db
from app.models import AjoConfig
from app.services.ajo_auth import get_ims_token, verify_ajo_access

router = APIRouter(prefix="/api/ajo", tags=["ajo"])


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str


def _get_config(db: Session) -> AjoConfig | None:
    return db.query(AjoConfig).first()


def _is_expired(data: dict) -> bool:
    expires_at = data.get("expires_at")
    if not expires_at:
        return True
    return datetime.utcnow() >= datetime.fromisoformat(expires_at)


def get_valid_access_token(db: Session) -> str:
    """Return a valid AJO access token, silently refreshing if expired."""
    config = _get_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="AJO not configured")

    data = json.loads(config.config_json)

    if not _is_expired(data):
        return decrypt(data["access_token"])

    # Token expired — refresh silently using stored encrypted client_secret
    try:
        client_secret = decrypt(data["client_secret"])
        access_token, expires_in = get_ims_token(data["client_id"], client_secret, data["org_id"])
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"AJO token refresh failed: {e}. Please reconnect.")

    data["access_token"] = encrypt(access_token)
    data["expires_at"] = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()
    config.config_json = json.dumps(data)
    config.updated_at = datetime.utcnow()
    db.commit()

    return access_token


@router.post("/connect")
def connect_ajo(body: AjoConnectRequest, db: Session = Depends(get_db)):
    try:
        access_token, expires_in = get_ims_token(body.client_id, body.client_secret, body.org_id)
        verify_ajo_access(access_token, body.client_id, body.org_id, body.sandbox_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"AJO connection failed: {str(e)}")

    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    config_data = {
        "org_id": body.org_id,
        "client_id": body.client_id,
        "sandbox_name": body.sandbox_name,
        # Encrypted so they're not readable as plain text in the DB
        "client_secret": encrypt(body.client_secret),
        "access_token": encrypt(access_token),
        "expires_at": expires_at,
    }

    existing = _get_config(db)
    if existing:
        existing.config_json = json.dumps(config_data)
        existing.connected = True
        existing.updated_at = datetime.utcnow()
    else:
        db.add(AjoConfig(
            config_json=json.dumps(config_data),
            connected=True,
            updated_at=datetime.utcnow(),
        ))

    db.commit()
    return {"status": "ok", "message": "AJO connected successfully"}


@router.get("/status")
def ajo_status(db: Session = Depends(get_db)):
    config = _get_config(db)
    if not config:
        return {"connected": False, "org_id": None, "sandbox_name": None, "token_expired": False}

    data = json.loads(config.config_json)
    expired = _is_expired(data)

    return {
        "connected": config.connected,
        "org_id": data.get("org_id"),
        "sandbox_name": data.get("sandbox_name"),
        "expires_at": data.get("expires_at"),
        "token_expired": expired,
    }
