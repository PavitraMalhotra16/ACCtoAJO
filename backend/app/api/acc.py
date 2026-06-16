import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AccConfig
from app.services.acc_soap import logon, get_schemas, get_schema_detail
from app.services.ajo_auth import get_ims_token

router = APIRouter(prefix="/api/acc", tags=["acc"])


class AccConnectClassic(BaseModel):
    auth_type: Literal["classic"]
    instance_url: str
    login: str
    password: str


class AccConnectTechnical(BaseModel):
    auth_type: Literal["technical"]
    instance_url: str
    client_id: str
    client_secret: str
    scope: str


AccConnectRequest = AccConnectClassic | AccConnectTechnical


def _get_config(db: Session) -> AccConfig | None:
    return db.query(AccConfig).first()


def _save_config(db: Session, auth_type: str, data: dict, connected: bool = True):
    existing = _get_config(db)
    if existing:
        existing.auth_type = auth_type
        existing.config_json = json.dumps(data)
        existing.connected = connected
        existing.updated_at = datetime.utcnow()
    else:
        db.add(AccConfig(
            auth_type=auth_type,
            config_json=json.dumps(data),
            connected=connected,
            updated_at=datetime.utcnow(),
        ))
    db.commit()


@router.post("/connect")
def connect_acc(body: AccConnectRequest, db: Session = Depends(get_db)):
    if body.auth_type == "classic":
        try:
            instance_url = body.instance_url.rstrip("/")
            session_token, security_token = logon(body.login, body.password, instance_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ACC connection failed: {str(e)}")

        _save_config(db, "classic", {
            "instance_url": body.instance_url,
            "login": body.login,
            "session_token": session_token,
            "security_token": security_token,
        })
        return {"status": "ok", "message": "ACC connected (classic)"}

    else:  # technical
        try:
            access_token, _ = get_ims_token(body.client_id, body.client_secret, scope=body.scope)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"IMS token error: {str(e)}")

        _save_config(db, "technical", {
            "instance_url": body.instance_url,
            "client_id": body.client_id,
            "access_token": access_token,
        })
        return {"status": "ok", "message": "ACC connected (technical account)"}


@router.get("/schemas")
def list_schemas(db: Session = Depends(get_db)):
    config = _get_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="ACC not configured")

    data = json.loads(config.config_json)

    try:
        if config.auth_type == "classic":
            schemas = get_schemas(data["session_token"], data["security_token"], data["instance_url"])
        else:
            schemas = get_schemas(None, None, data["instance_url"], ims_token=data["access_token"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch schemas: {str(e)}")

    return {"schemas": schemas}


@router.get("/schemas/{namespace}/{name}")
def get_schema(namespace: str, name: str, db: Session = Depends(get_db)):
    config = _get_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="ACC not configured")

    data = json.loads(config.config_json)

    try:
        if config.auth_type == "classic":
            detail = get_schema_detail(data["session_token"], data["security_token"], namespace, name, data["instance_url"])
        else:
            detail = get_schema_detail(None, None, namespace, name, data["instance_url"], ims_token=data["access_token"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch schema: {str(e)}")

    return detail


@router.post("/disconnect")
def disconnect_acc(db: Session = Depends(get_db)):
    config = _get_config(db)
    if config:
        db.delete(config)
        db.commit()
    return {"status": "ok"}


@router.get("/status")
def acc_status(db: Session = Depends(get_db)):
    config = _get_config(db)
    if not config:
        return {"connected": False, "auth_type": None, "login": None, "instance_url": None}
    data = json.loads(config.config_json)
    return {
        "connected": config.connected,
        "auth_type": config.auth_type,
        "login": data.get("login"),
        "instance_url": data.get("instance_url"),
    }
