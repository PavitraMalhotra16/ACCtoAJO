import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── load_raw ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_raw_parses_template_data():
    from pipeline.template_handlers import load_raw

    template_data = {
        "sourceId": "100",
        "internalName": "welcome_email",
        "label": "Welcome Email",
        "channel": "email",
        "subject": "Hi there",
        "htmlBody": "<html>Hello</html>",
        "smsContent": "",
        "description": "",
    }
    mock_row = MagicMock()
    mock_row.template_data = json.dumps(template_data)
    mock_row.source_id = "100"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = {"source_id": "100", "login_id": "user@example.com"}
    data = await load_raw(ctx, {}, mock_db)

    assert data["channel"] == "email"
    assert data["htmlBody"] == "<html>Hello</html>"
    assert data["label"] == "Welcome Email"


@pytest.mark.asyncio
async def test_load_raw_raises_on_missing_row():
    from pipeline.template_handlers import load_raw

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await load_raw({"source_id": "999", "login_id": "u"}, {}, mock_db)


# ── convert_placeholders ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_convert_recipient_placeholder():
    from pipeline.template_handlers import convert_placeholders

    placeholder_map = {"recipient.firstName": "profile.person.name.firstName"}
    ctx = {"placeholder_map": placeholder_map}
    data = {
        "channel": "email",
        "htmlBody": "<p>Hi <%= recipient.firstName %></p>",
        "subject": "Hello <%= recipient.firstName %>",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert "{{profile.person.name.firstName}}" in result["convertedHtml"]
    assert "{{profile.person.name.firstName}}" in result["convertedSubject"]
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_convert_unsub_token():
    from pipeline.template_handlers import convert_placeholders

    ctx = {"placeholder_map": {}}
    data = {
        "channel": "email",
        "htmlBody": '<a href="%UNSUB%">Unsubscribe</a>',
        "subject": "Test",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert "{{unsubscribeLink}}" in result["convertedHtml"]


@pytest.mark.asyncio
async def test_convert_scriptlet_goes_to_warnings():
    from pipeline.template_handlers import convert_placeholders

    ctx = {"placeholder_map": {}}
    data = {
        "channel": "email",
        "htmlBody": "<%@ include option='foo' %>",
        "subject": "Test",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert any(w["type"] == "scriptlet" for w in result["warnings"])


# ── resolve_folder ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_folder_returns_parent_id():
    from pipeline.template_handlers import resolve_folder

    mock_cfg = MagicMock()
    mock_cfg.parent_folder_id = "folder-uuid-abc"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_cfg

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = {"destination_conn_id": "dest-123"}
    data = {"channel": "email"}
    result = await resolve_folder(ctx, data, mock_db)
    assert result["parentFolderId"] == "folder-uuid-abc"


@pytest.mark.asyncio
async def test_resolve_folder_raises_if_not_configured():
    from pipeline.template_handlers import resolve_folder

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="folder not configured"):
        await resolve_folder({"destination_conn_id": "x"}, {"channel": "email"}, mock_db)
