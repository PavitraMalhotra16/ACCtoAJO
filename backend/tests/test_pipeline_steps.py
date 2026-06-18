import pytest
from pipeline_steps import PIPELINE_STEPS, PipelineStep


def test_step_count():
    assert len(PIPELINE_STEPS) == 8


def test_steps_ordered():
    orders = [s.order for s in PIPELINE_STEPS]
    assert orders == list(range(1, 9))


def test_step_names():
    names = [s.name for s in PIPELINE_STEPS]
    assert names == [
        "LOAD_JSON",
        "MAP_TYPES",
        "RESOLVE_IDENTITY",
        "FETCH_TENANT_ID",
        "BUILD_PAYLOAD",
        "CALL_SCHEMA_API",
        "CALL_IDENTITY_DESCRIPTOR_API",
        "VERIFY",
    ]


def test_handlers_are_strings():
    for step in PIPELINE_STEPS:
        assert isinstance(step.handler, str)
        assert "." in step.handler, f"Handler {step.handler!r} must be a dotted path"


def test_dataclass_fields():
    step = PIPELINE_STEPS[0]
    assert isinstance(step, PipelineStep)
    assert step.name == "LOAD_JSON"
    assert step.order == 1
