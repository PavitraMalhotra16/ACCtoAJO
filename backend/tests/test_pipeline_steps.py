import pytest
from pipeline_steps import PIPELINE_STEPS, PipelineStep


def test_step_count():
    assert len(PIPELINE_STEPS) == 14


def test_steps_ordered():
    orders = [s.order for s in PIPELINE_STEPS]
    assert orders == list(range(1, 15))


def test_step_names():
    names = [s.name for s in PIPELINE_STEPS]
    assert names == [
        "LOAD_JSON",
        "MAP_TYPES",
        "RESOLVE_IDENTITY",
        "FETCH_TENANT_ID",
        "BUILD_PAYLOAD",
        "NORMALIZE_INPUT",
        "DUPLICATE_CHECK",
        "CREATE_SCHEMA",
        "PRIMARY_KEY_DESCRIPTOR",
        "VERSION_DESCRIPTOR",
        "TIMESTAMP_DESCRIPTOR",
        "IDENTITY_DESCRIPTOR",
        "RELATIONSHIP_DESCRIPTORS",
        "VERIFY",
    ]


def test_phases():
    # Steps 1-12 are PASS 1 (per schema); 13-14 are PASS 2 (after all schemas exist).
    by_name = {s.name: s for s in PIPELINE_STEPS}
    assert by_name["RELATIONSHIP_DESCRIPTORS"].phase == 2
    assert by_name["VERIFY"].phase == 2
    assert all(s.phase == 1 for s in PIPELINE_STEPS if s.order <= 12)


def test_handlers_are_strings():
    for step in PIPELINE_STEPS:
        assert isinstance(step.handler, str)
        assert "." in step.handler, f"Handler {step.handler!r} must be a dotted path"


def test_dataclass_fields():
    step = PIPELINE_STEPS[0]
    assert isinstance(step, PipelineStep)
    assert step.name == "LOAD_JSON"
    assert step.order == 1
    assert step.phase == 1
