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
        label="Load extracted schema from DB",
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
        name="MAKE_ENRICHED_JSON",
        label="Build enriched input JSON",
        handler="pipeline.handlers.make_enriched_json",
        order=5,
    ),
    PipelineStep(
        name="CALL_SCHEMA_API",
        label="Create schema in AEP Schema Registry",
        handler="pipeline.handlers.call_schema_api",
        order=6,
    ),
    PipelineStep(
        name="CALL_FIELDGROUP_API",
        label="Create custom field group with schema fields",
        handler="pipeline.handlers.call_fieldgroup_api",
        order=7,
    ),
    PipelineStep(
        name="ATTACH_FIELDGROUP",
        label="Attach field group to schema",
        handler="pipeline.handlers.attach_fieldgroup",
        order=8,
    ),
    PipelineStep(
        name="ENSURE_NAMESPACE",
        label="Check / create identity namespace",
        handler="pipeline.handlers.ensure_namespace",
        order=9,
    ),
    PipelineStep(
        name="CALL_IDENTITY_DESCRIPTOR_API",
        label="Register identity descriptor",
        handler="pipeline.handlers.call_identity_descriptor",
        order=10,
    ),
    PipelineStep(
        name="ENABLE_PROFILE_UNION",
        label="Enable schema for Profile (union)",
        handler="pipeline.handlers.enable_profile_union",
        order=11,
    ),
    PipelineStep(
        name="VERIFY",
        label="Verify schema exists in AEP",
        handler="pipeline.handlers.verify",
        order=12,
    ),
]
