"""Tests for the AJO content-template push handlers (pipeline steps 5–8).

All DB/HTTP is mocked — no Postgres or network. Mirrors the conventions in
test_template_handlers.py (import inside each test, AsyncMock/MagicMock).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── shared mock builders ───────────────────────────────────────────────────────

def _mock_httpx_client(responses):
    """Fake httpx.AsyncClient factory; post/get yield the given response(s) in order."""
    seq = responses if isinstance(responses, list) else [responses]
    client = AsyncMock()
    client.post = AsyncMock(side_effect=list(seq))
    client.get = AsyncMock(side_effect=list(seq))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), client


def _resp(status_code, json_body=None, headers=None, text=""):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_body if json_body is not None else {}
    r.headers = headers or {}
    r.text = text
    return r


def _mock_session(row):
    """Fake AsyncSessionLocal() context manager whose query returns `row`."""
    result = MagicMock()
    result.scalar_one.return_value = row
    result.scalar_one_or_none.return_value = row
    sess = AsyncMock()
    sess.execute = AsyncMock(return_value=result)
    sess.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=sess)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), sess


_AUTH = {"token": "tok", "api_key": "key", "org_id": "org@AdobeOrg", "sandbox": "prod"}


def _valid_email_payload():
    return {
        "name": "X", "description": "d", "templateType": "html", "channels": ["email"],
        "parentFolderId": "f", "template": {"html": "<p>hi</p>", "editorContext": {}},
    }


# ── build_payload (step 5) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_payload_email_shape():
    from pipeline import template_handlers as th

    enriched = {
        "name": "Welcome Email", "channel": "email",
        "convertedHtml": "<html>Hi {{profile.person.name.firstName}}</html>",
        "convertedSmsBody": None, "parentFolderId": "folder-email-uuid",
    }
    with patch.object(th, "_load_enriched", AsyncMock(return_value=enriched)):
        out = await th.build_payload({"item_id": "i1"}, {"channel": "email"}, None)

    p = out["ajoPayload"]
    assert p["templateType"] == "html"
    assert p["channels"] == ["email"]
    assert "subType" not in p  # omitted — live AJO rejects subType for templateType html
    assert p["template"]["html"].startswith("<html>")
    assert p["template"]["editorContext"] == {}
    assert p["source"] == {"origin": "ajo", "metadata": {}}
    assert p["parentFolderId"] == "folder-email-uuid"
    assert p["description"] == "This template is about Welcome Email"


@pytest.mark.asyncio
async def test_build_payload_sms_shape():
    from pipeline import template_handlers as th

    enriched = {
        "name": "Order Shipped", "channel": "sms",
        "convertedHtml": None, "convertedSmsBody": "Your order shipped.",
        "parentFolderId": "folder-sms-uuid",
    }
    with patch.object(th, "_load_enriched", AsyncMock(return_value=enriched)):
        out = await th.build_payload({"item_id": "i1"}, {"channel": "sms"}, None)

    p = out["ajoPayload"]
    assert p["templateType"] == "content"
    assert p["channels"] == ["sms"]
    assert "subType" not in p
    assert p["template"]["body"] == "Your order shipped."


# ── validate_fields (step 6) ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_fields_passes():
    from pipeline.template_handlers import validate_fields
    out = await validate_fields({"item_id": "i1"}, {"ajoPayload": _valid_email_payload()}, None)
    assert out["ajoPayload"]["name"] == "X"


@pytest.mark.asyncio
async def test_validate_fields_missing_name_skips():
    from pipeline.template_handlers import validate_fields, TemplateSkipped
    p = _valid_email_payload(); p["name"] = "  "
    with pytest.raises(TemplateSkipped, match="name is required"):
        await validate_fields({"item_id": "i1"}, {"ajoPayload": p}, None)


@pytest.mark.asyncio
async def test_validate_fields_bad_template_type_skips():
    from pipeline.template_handlers import validate_fields, TemplateSkipped
    p = _valid_email_payload(); p["templateType"] = "text"
    with pytest.raises(TemplateSkipped, match="templateType"):
        await validate_fields({"item_id": "i1"}, {"ajoPayload": p}, None)


@pytest.mark.asyncio
async def test_validate_fields_missing_html_skips():
    from pipeline.template_handlers import validate_fields, TemplateSkipped
    p = _valid_email_payload(); p["template"] = {"html": "", "editorContext": {}}
    with pytest.raises(TemplateSkipped, match="template.html is required"):
        await validate_fields({"item_id": "i1"}, {"ajoPayload": p}, None)


# ── push_template (step 7) — §8 error table ────────────────────────────────────

@pytest.mark.asyncio
async def test_push_template_201_stores_id():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    row = MagicMock(); row.ajo_template_id = None
    sess_factory, _ = _mock_session(row)
    client_factory, _ = _mock_httpx_client(_resp(201, {"id": "ajo-123"}))

    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory), \
         patch.object(th, "AsyncSessionLocal", sess_factory):
        out = await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)

    assert out["ajoTemplateId"] == "ajo-123"
    assert row.ajo_template_id == "ajo-123"


@pytest.mark.asyncio
async def test_push_template_400_fails():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    client_factory, _ = _mock_httpx_client(_resp(400, {"detail": "bad name"}))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        with pytest.raises(th.TemplateFailed, match="400: bad name"):
            await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)


@pytest.mark.asyncio
async def test_push_template_201_empty_body_uses_location():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    row = MagicMock(); row.ajo_template_id = None
    sess_factory, _ = _mock_session(row)
    r = _resp(201, headers={"Location": "/ajo/content/templates/loc-id-7"})
    r.json.side_effect = ValueError("no body")  # empty 201 body → json() raises
    client_factory, _ = _mock_httpx_client(r)

    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory), \
         patch.object(th, "AsyncSessionLocal", sess_factory):
        out = await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)

    assert out["ajoTemplateId"] == "loc-id-7"
    assert row.ajo_template_id == "loc-id-7"


@pytest.mark.asyncio
async def test_push_template_403_fatal():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    client_factory, _ = _mock_httpx_client(_resp(403, {"detail": "no perms"}))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        with pytest.raises(th.FatalRunError, match="403"):
            await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)


@pytest.mark.asyncio
async def test_push_template_413_manual():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    client_factory, _ = _mock_httpx_client(_resp(413, {"detail": "too big"}))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        with pytest.raises(th.TemplateManual, match="413"):
            await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)


@pytest.mark.asyncio
async def test_push_template_401_refresh_then_succeeds():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload()}
    row = MagicMock(); row.ajo_template_id = None
    sess_factory, _ = _mock_session(row)
    client_factory, client = _mock_httpx_client([_resp(401, {"message": "expired"}),
                                                 _resp(201, {"id": "ajo-999"})])
    resolve = AsyncMock(return_value=_AUTH)
    with patch.object(th, "_resolve_auth", resolve), \
         patch.object(th.httpx, "AsyncClient", client_factory), \
         patch.object(th, "AsyncSessionLocal", sess_factory):
        out = await th.push_template({"item_id": "i1", "destination_conn_id": "d1"}, data, None)

    assert out["ajoTemplateId"] == "ajo-999"
    assert client.post.await_count == 2      # retried once after refresh
    assert resolve.await_count == 2          # initial + forced refresh


# ── verify (step 8) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_success():
    from pipeline import template_handlers as th
    payload = _valid_email_payload()
    data = {"ajoPayload": payload, "ajoTemplateId": "ajo-1"}
    body = {"name": payload["name"], "channels": payload["channels"], "status": "DRAFT"}
    client_factory, _ = _mock_httpx_client(_resp(200, body))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        out = await th.verify({"item_id": "i1", "destination_conn_id": "d1"}, data, None)
    assert out["verified"] is True


@pytest.mark.asyncio
async def test_verify_status_mismatch_raises():
    from pipeline import template_handlers as th
    payload = _valid_email_payload()
    data = {"ajoPayload": payload, "ajoTemplateId": "ajo-1"}
    body = {"name": payload["name"], "channels": payload["channels"], "status": "ARCHIVED"}
    client_factory, _ = _mock_httpx_client(_resp(200, body))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        with pytest.raises(th.VerificationFailed, match="status"):
            await th.verify({"item_id": "i1", "destination_conn_id": "d1"}, data, None)


@pytest.mark.asyncio
async def test_verify_succeeds_when_status_absent():
    """Live vendor representation may omit status — 200 + matching name/channels is enough."""
    from pipeline import template_handlers as th
    payload = _valid_email_payload()
    data = {"ajoPayload": payload, "ajoTemplateId": "ajo-1"}
    body = {"name": payload["name"], "channels": payload["channels"]}  # no status field
    client_factory, _ = _mock_httpx_client(_resp(200, body))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        out = await th.verify({"item_id": "i1", "destination_conn_id": "d1"}, data, None)
    assert out["verified"] is True


@pytest.mark.asyncio
async def test_verify_get_non_200_raises():
    from pipeline import template_handlers as th
    data = {"ajoPayload": _valid_email_payload(), "ajoTemplateId": "ajo-1"}
    client_factory, _ = _mock_httpx_client(_resp(404, {"detail": "not found"}))
    with patch.object(th, "_resolve_auth", AsyncMock(return_value=_AUTH)), \
         patch.object(th.httpx, "AsyncClient", client_factory):
        with pytest.raises(th.VerificationFailed, match="404"):
            await th.verify({"item_id": "i1", "destination_conn_id": "d1"}, data, None)
