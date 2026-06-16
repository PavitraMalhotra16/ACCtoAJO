import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Config
from app.services.acc_soap import logon, get_schemas, get_schema_detail

router = APIRouter(prefix="/api/acc", tags=["acc"])


class AccConnectRequest(BaseModel):
    login: str
    password: str


def _get_acc_config(db: Session) -> Config | None:
    return db.query(Config).filter(Config.service == "acc").first()


def _get_tokens(config: Config) -> tuple[str, str]:
    data = json.loads(config.config_json)
    return data["session_token"], data["security_token"]


@router.post("/connect")
def connect_acc(body: AccConnectRequest, db: Session = Depends(get_db)):
    try:
        session_token, security_token = logon(body.login, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to ACC: {str(e)}")

    config_data = {
        "login": body.login,
        "session_token": session_token,
        "security_token": security_token,
    }

    existing = _get_acc_config(db)
    if existing:
        existing.config_json = json.dumps(config_data)
        existing.connected = True
        existing.updated_at = datetime.utcnow()
    else:
        db.add(Config(
            service="acc",
            config_json=json.dumps(config_data),
            connected=True,
            updated_at=datetime.utcnow(),
        ))

    db.commit()
    return {"status": "ok", "message": "ACC connected successfully"}


@router.get("/schemas")
def list_schemas(db: Session = Depends(get_db)):
    config = _get_acc_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="ACC not configured")

    try:
        session_token, security_token = _get_tokens(config)
        schemas = get_schemas(session_token, security_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch schemas: {str(e)}")

    return {"schemas": schemas}


@router.get("/schemas/{namespace}/{name}")
def get_schema(namespace: str, name: str, db: Session = Depends(get_db)):
    config = _get_acc_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="ACC not configured")

    try:
        session_token, security_token = _get_tokens(config)
        detail = get_schema_detail(session_token, security_token, namespace, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch schema detail: {str(e)}")

    return detail


@router.post("/disconnect")
def disconnect_acc(db: Session = Depends(get_db)):
    existing = _get_acc_config(db)
    if existing:
        db.delete(existing)
        db.commit()
    return {"status": "ok", "message": "ACC disconnected"}


@router.get("/status")
def acc_status(db: Session = Depends(get_db)):
    config = _get_acc_config(db)
    if not config:
        return {"connected": False, "login": None}
    data = json.loads(config.config_json)
    return {"connected": config.connected, "login": data.get("login")}
