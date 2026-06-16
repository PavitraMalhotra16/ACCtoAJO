import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Config
from app.services.ajo_auth import get_ims_token, verify_ajo_access, compare_token_claims

router = APIRouter(prefix="/api/ajo", tags=["ajo"])


class AjoConnectRequest(BaseModel):
    org_id: str
    client_id: str
    client_secret: str
    sandbox_name: str
    reference_token: str | None = None


def _get_ajo_config(db: Session) -> Config | None:
    return db.query(Config).filter(Config.service == "ajo").first()


@router.post("/connect")
def connect_ajo(body: AjoConnectRequest, db: Session = Depends(get_db)):
    try:
        access_token, expires_in = get_ims_token(body.client_id, body.client_secret, body.org_id)
        if body.reference_token:
            compare_token_claims(access_token, body.reference_token)
        verify_ajo_access(access_token, body.client_id, body.org_id, body.sandbox_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to AJO: {str(e)}")

    config_data = {
        "org_id": body.org_id,
        "client_id": body.client_id,
        "sandbox_name": body.sandbox_name,
        "access_token": access_token,
    }

    existing = _get_ajo_config(db)
    if existing:
        existing.config_json = json.dumps(config_data)
        existing.connected = True
        existing.updated_at = datetime.utcnow()
    else:
        db.add(Config(
            service="ajo",
            config_json=json.dumps(config_data),
            connected=True,
            updated_at=datetime.utcnow(),
        ))

    db.commit()
    return {"status": "ok", "message": "AJO connected successfully"}


@router.get("/status")
def ajo_status(db: Session = Depends(get_db)):
    config = _get_ajo_config(db)
    if not config:
        return {"connected": False, "org_id": None, "sandbox_name": None}
    data = json.loads(config.config_json)
    return {
        "connected": config.connected,
        "org_id": data.get("org_id"),
        "sandbox_name": data.get("sandbox_name"),
    }
