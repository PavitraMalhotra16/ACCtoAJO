from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS


def test_steps_ordered_correctly():
    orders = [s.order for s in TEMPLATE_PIPELINE_STEPS]
    assert orders == sorted(orders)
    assert orders[0] == 1


def test_has_eight_steps():
    assert len(TEMPLATE_PIPELINE_STEPS) == 8


def test_all_steps_active_no_stubs():
    active = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
    assert len(active) == 8
    assert [s.name for s in active] == [
        "LOAD_RAW", "CONVERT_PLACEHOLDERS", "RESOLVE_FOLDER", "BUILD_ENRICHED",
        "BUILD_PAYLOAD", "VALIDATE_FIELDS", "PUSH_TEMPLATE", "VERIFY",
    ]


def test_dropped_duplicate_check():
    assert all(s.name != "DUPLICATE_CHECK" for s in TEMPLATE_PIPELINE_STEPS)
