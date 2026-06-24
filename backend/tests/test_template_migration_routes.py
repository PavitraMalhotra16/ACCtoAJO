import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_setup_returns_401_without_auth(client):
    resp = client.post("/api/templates/setup", json={
        "email_sample_name": "email sample",
        "sms_sample_name": "sms sample",
    })
    assert resp.status_code == 401


def test_analysis_returns_401_without_auth(client):
    resp = client.get("/api/templates/analysis")
    assert resp.status_code == 401


def test_run_status_404_for_unknown_run(client):
    with patch("routes.templates.get_login_from_cookie", return_value="user@test.com"):
        resp = client.get("/api/templates/runs/nonexistent-run-id/status",
                          cookies={"acc_user": "user@test.com"})
    assert resp.status_code == 404
