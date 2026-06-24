from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS


def test_steps_ordered_correctly():
    orders = [s.order for s in TEMPLATE_PIPELINE_STEPS]
    assert orders == sorted(orders)
    assert orders[0] == 1


def test_has_eight_steps():
    assert len(TEMPLATE_PIPELINE_STEPS) == 8


def test_active_steps_are_1_to_4():
    active = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
    assert len(active) == 4
    assert [s.name for s in active] == [
        "LOAD_RAW", "CONVERT_PLACEHOLDERS", "RESOLVE_FOLDER", "BUILD_ENRICHED"
    ]
