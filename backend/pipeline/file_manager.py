import json
import os
import shutil
from pathlib import Path

from config import settings


def _storage_root() -> Path:
    return Path(os.getenv("SCHEMA_STORAGE_DIR", settings.schema_storage_dir))


def _safe(schema_name: str) -> str:
    return schema_name.replace(":", "_")


def tmp_dir(login_id: str) -> Path:
    return _storage_root() / login_id / "_tmp"


def tmp_path(login_id: str, schema_name: str) -> Path:
    return tmp_dir(login_id) / f"{_safe(schema_name)}.json"


def permanent_path(login_id: str, schema_name: str) -> Path:
    return _storage_root() / login_id / f"{_safe(schema_name)}.json"


def write_tmp(login_id: str, schema_name: str, data: dict) -> Path:
    path = tmp_path(login_id, schema_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def read_tmp(login_id: str, schema_name: str) -> dict:
    return json.loads(tmp_path(login_id, schema_name).read_text(encoding="utf-8"))


def finalize(login_id: str, schema_name: str) -> Path:
    src = tmp_path(login_id, schema_name)
    dst = permanent_path(login_id, schema_name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst


def cleanup_tmp(login_id: str) -> None:
    d = tmp_dir(login_id)
    if d.exists() and not any(d.iterdir()):
        d.rmdir()
