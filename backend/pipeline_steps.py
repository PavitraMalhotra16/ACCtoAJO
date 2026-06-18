from dataclasses import dataclass


@dataclass
class PipelineStep:
    name: str
    label: str
    handler: str
    order: int


PIPELINE_STEPS: list[PipelineStep] = [
    PipelineStep(
        name="LOAD_JSON",
        label="Load extracted schema from disk",
        handler="pipeline.handlers.load_json",
        order=1,
    ),
    PipelineStep(
        name="MAP_TYPES",
        label="Map ACC types to XDM types",
        handler="pipeline.handlers.map_types",
        order=2,
    ),
    PipelineStep(
        name="RESOLVE_IDENTITY",
        label="Detect identity field from primary key",
        handler="pipeline.handlers.resolve_identity",
        order=3,
    ),
    PipelineStep(
        name="FETCH_TENANT_ID",
        label="Fetch and cache AEP tenant ID",
        handler="pipeline.handlers.fetch_tenant_id",
        order=4,
    ),
    PipelineStep(
        name="BUILD_PAYLOAD",
        label="Assemble AJO schema payload",
        handler="pipeline.handlers.build_payload_stub",
        order=5,
    ),
    PipelineStep(
        name="CALL_SCHEMA_API",
        label="POST schema to AEP Schema Registry",
        handler="pipeline.handlers.call_schema_api_stub",
        order=6,
    ),
    PipelineStep(
        name="CALL_IDENTITY_DESCRIPTOR_API",
        label="POST identity descriptor to AEP",
        handler="pipeline.handlers.call_identity_descriptor_stub",
        order=7,
    ),
    PipelineStep(
        name="VERIFY",
        label="GET schema back from AEP to confirm live",
        handler="pipeline.handlers.verify_stub",
        order=8,
    ),
]
