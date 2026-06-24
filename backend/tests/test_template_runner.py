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
