import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_template_updates_status_to_completed():
    from pipeline.template_runner import run_template

    with patch("pipeline.template_runner._update_item") as mock_update, \
         patch("pipeline.template_runner._load_handler") as mock_load:

        async def fake_handler(ctx, data, db):
            return {**data, "loaded": True}

        mock_load.return_value = fake_handler
        mock_update.return_value = None

        mock_db = AsyncMock()
        result = await run_template(
            item_id="item-1",
            source_id="100",
            login_id="user@test.com",
            destination_conn_id="dest-1",
            placeholder_map={"recipient.email": "profile.workEmail.address"},
            channel="email",
            db=mock_db,
        )
        assert result is True
        # COMPLETED should have been called
        completed_calls = [
            c for c in mock_update.call_args_list
            if c.args and c.args[1] == "COMPLETED"
        ]
        assert len(completed_calls) == 1
        # final label must be the actual last step (VERIFY), not the stale BUILD_ENRICHED
        assert completed_calls[0].args[2] == "VERIFY"


@pytest.mark.asyncio
@pytest.mark.parametrize("exc_name,expected_status", [
    ("TemplateSkipped", "SKIPPED"),
    ("TemplateFailed", "FAILED"),
    ("TemplateManual", "MANUAL"),
    ("VerificationFailed", "VERIFICATION_FAILED"),
    ("FatalRunError", "HALTED"),
])
async def test_typed_exception_maps_to_status(exc_name, expected_status):
    from pipeline import template_runner as tr
    from pipeline import template_handlers as th

    exc_cls = getattr(th, exc_name)

    async def boom(ctx, data, db):
        raise exc_cls("400: boom")

    with patch("pipeline.template_runner._update_item") as mock_update, \
         patch("pipeline.template_runner._load_handler", return_value=boom):
        mock_update.return_value = None
        abort = asyncio.Event()
        result = await tr.run_template(
            item_id="item-1", source_id="100", login_id="u",
            destination_conn_id="d1", placeholder_map={}, channel="email",
            db=AsyncMock(), abort_event=abort,
        )

    assert result is False
    status_calls = [c for c in mock_update.call_args_list if c.args and c.args[1] == expected_status]
    assert len(status_calls) == 1
    # error_step recorded as "<order> (<NAME>)"
    assert "(" in (status_calls[0].kwargs.get("error_step") or "")
    # FatalRunError must trip the run-wide abort flag
    assert abort.is_set() is (exc_name == "FatalRunError")


@pytest.mark.asyncio
async def test_resume_skips_completed_steps():
    """resume_from_step=7 should run only VERIFY (step 8)."""
    from pipeline import template_runner as tr

    seen = []

    async def fake_handler(ctx, data, db):
        return data

    def load(dotted):
        seen.append(dotted)
        return fake_handler

    with patch("pipeline.template_runner._update_item", AsyncMock()), \
         patch("pipeline.template_runner._load_handler", side_effect=lambda d: load(d)):
        result = await tr.run_template(
            item_id="i1", source_id="100", login_id="u",
            destination_conn_id="d1", placeholder_map={}, channel="email",
            db=AsyncMock(), resume_from_step=7,
        )

    assert result is True
    assert len(seen) == 1 and seen[0].endswith(".verify")
