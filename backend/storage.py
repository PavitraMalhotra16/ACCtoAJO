"""
Local file storage for converted schemas.
Writes JSON to disk under SCHEMA_STORAGE_DIR and returns the relative path.
"""

import json
import os
from config import settings


def _make_path(login_id: str, job_id: str, schema_name: str) -> str:
    """Build folder path: <storage_dir>/<login_id>/<job_id>/"""
    safe_login = login_id.replace("/", "_").replace("\\", "_")
    safe_schema = schema_name.replace(":", "_")
    folder = os.path.join(settings.schema_storage_dir, safe_login, job_id)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{safe_schema}.json")


def save_schema(login_id: str, job_id: str, schema_name: str, data: dict) -> str:
    """Write JSON to disk. Returns the absolute file path stored in DB."""
    path = _make_path(login_id, job_id, schema_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_schema(storage_path: str) -> dict:
    """Read JSON from disk given a stored path."""
    with open(storage_path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_user_schemas(login_id: str):
    """Delete all schema files for a user (call on connection reset)."""
    import shutil
    safe_login = login_id.replace("/", "_").replace("\\", "_")
    folder = os.path.join(settings.schema_storage_dir, safe_login)
    if os.path.exists(folder):
        shutil.rmtree(folder)
