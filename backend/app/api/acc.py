import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Config
from app.services.acc_soap import logon, get_schemas

router = APIRouter(prefix="/api/acc", tags=["acc"])


class AccConnectRequest(BaseModel):
    login: str
    password: str


def _get_acc_config(db: Session) -> Config | None:
    return db.query(Config).filter(Config.service == "acc").first()


@router.post("/connect")
def connect_acc(body: AccConnectRequest, db: Session = Depends(get_db)):
    try:
        session_token = logon(body.login, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to ACC: {str(e)}")

    config_data = {"session_token": session_token, "login": body.login}

    existing = _get_acc_config(db)
    if existing:
        existing.config_json = json.dumps(config_data)
        existing.connected = True
        existing.updated_at = datetime.utcnow()
    else:
        record = Config(
            service="acc",
            config_json=json.dumps(config_data),
            connected=True,
            updated_at=datetime.utcnow(),
        )
        db.add(record)

    db.commit()
    return {"status": "ok", "message": "ACC connected successfully"}


@router.get("/schemas")
def list_schemas(db: Session = Depends(get_db)):
    config = _get_acc_config(db)
    if not config or not config.connected:
        raise HTTPException(status_code=400, detail="ACC not configured")

    config_data = json.loads(config.config_json)
    session_token = config_data.get("session_token")
    if not session_token:
        raise HTTPException(status_code=400, detail="ACC not configured")

    try:
        schemas = get_schemas(session_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch schemas: {str(e)}")

    return {"schemas": schemas}


@router.get("/status")
def acc_status(db: Session = Depends(get_db)):
    config = _get_acc_config(db)
    if not config:
        return {"connected": False, "login": None}

    config_data = json.loads(config.config_json)
    return {
        "connected": config.connected,
        "login": config_data.get("login"),
    }
