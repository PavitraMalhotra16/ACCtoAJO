import json
import pytest
from pathlib import Path
from pipeline.file_manager import (
    tmp_path, write_tmp, read_tmp, finalize, cleanup_tmp
)


@pytest.fixture
def storage_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEMA_STORAGE_DIR", str(tmp_path))
    import importlib, pipeline.file_manager as fm
    importlib.reload(fm)
    return tmp_path


def test_write_and_read_tmp(storage_root):
    from pipeline.file_manager import write_tmp, read_tmp
    data = {"source": {"fullName": "cus:test"}, "attributes": []}
    write_tmp("user1", "cus:test", data)
    result = read_tmp("user1", "cus:test")
    assert result == data


def test_finalize_moves_file(storage_root):
    from pipeline.file_manager import write_tmp, finalize, tmp_path, permanent_path
    data = {"tenantId": "_acme"}
    write_tmp("user1", "cus:order", data)
    assert tmp_path("user1", "cus:order").exists()

    final = finalize("user1", "cus:order")
    assert final.exists()
    assert not tmp_path("user1", "cus:order").exists()
    assert json.loads(final.read_text()) == data


def test_cleanup_removes_empty_tmp(storage_root):
    from pipeline.file_manager import write_tmp, finalize, cleanup_tmp, tmp_path
    write_tmp("user1", "cus:x", {"a": 1})
    finalize("user1", "cus:x")
    cleanup_tmp("user1")
    assert not tmp_path("user1", "cus:x").parent.exists()


def test_schema_name_colon_safe(storage_root):
    from pipeline.file_manager import write_tmp, read_tmp
    write_tmp("user1", "cus:my:schema", {"ok": True})
    result = read_tmp("user1", "cus:my:schema")
    assert result == {"ok": True}
