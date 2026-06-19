from dataclasses import dataclass


@dataclass
class PipelineStep:
    name: str
    label: str
    handler: str
    order: int


# Phase 2 (migrationpart) — extraction pipeline only, steps 1-5.
# Steps 6+ (AEP schema/identity descriptor API calls) belong to Phase 3 (AJOpart).
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
        name="BUILD_PAYLOAD",
        label="Assemble enriched JSON payload",
        handler="pipeline.handlers.build_payload",
        order=5,
    ),
]
