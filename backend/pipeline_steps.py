from dataclasses import dataclass


@dataclass
class PipelineStep:
    name: str
    label: str
    handler: str
    order: int
    # PASS-1 (phase 1): create each schema + its own descriptors, per schema.
    # PASS-2 (phase 2): relationships + verify — runs only after every schema exists.
    phase: int = 1


# Phase 2 (migrationpart) steps 1-5 build the enriched JSON.
# Phase 3 (AJOpart) steps 6-14 push the relational schema into AEP / AJO:
#   PASS 1 (per schema)  : NORMALIZE_INPUT → DUPLICATE_CHECK → CREATE_SCHEMA →
#                          PRIMARY_KEY/VERSION/TIMESTAMP/IDENTITY descriptors
#   PASS 2 (after all)   : RELATIONSHIP_DESCRIPTORS → CREATE_DATASET → VERIFY → VALIDATE_OC → ENABLE_OC
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
    # ── Phase 3 / PASS 1 — create the schema and its own descriptors ─────────────
    PipelineStep(
        name="NORMALIZE_INPUT",
        label="Read & validate enriched JSON",
        handler="pipeline.handlers.normalize_input",
        order=6,
    ),
    PipelineStep(
        name="DUPLICATE_CHECK",
        label="Check schema in AEP registry",
        handler="pipeline.handlers.duplicate_check",
        order=7,
    ),
    PipelineStep(
        name="CREATE_SCHEMA",
        label="Create relational schema in AEP",
        handler="pipeline.handlers.create_schema",
        order=8,
    ),
    PipelineStep(
        name="PRIMARY_KEY_DESCRIPTOR",
        label="Attach primary-key descriptor",
        handler="pipeline.handlers.primary_key_descriptor",
        order=9,
    ),
    PipelineStep(
        name="VERSION_DESCRIPTOR",
        label="Attach version descriptor",
        handler="pipeline.handlers.version_descriptor",
        order=10,
    ),
    PipelineStep(
        name="TIMESTAMP_DESCRIPTOR",
        label="Attach timestamp descriptor (time-series)",
        handler="pipeline.handlers.timestamp_descriptor",
        order=11,
    ),
    PipelineStep(
        name="IDENTITY_DESCRIPTOR",
        label="Attach identity descriptor (person keys)",
        handler="pipeline.handlers.identity_descriptor",
        order=12,
    ),
    # ── Phase 3 / PASS 2 — wire relationships, then verify ───────────────────────
    PipelineStep(
        name="RELATIONSHIP_DESCRIPTORS",
        label="Wire relationships to target schemas",
        handler="pipeline.handlers.relationship_descriptors",
        order=13,
        phase=2,
    ),
    PipelineStep(
        name="CREATE_DATASET",
        label="Create dataset in AEP Catalog",
        handler="pipeline.handlers.create_dataset",
        order=14,
        phase=2,
    ),
    PipelineStep(
        name="VERIFY",
        label="Verify schema & descriptors in AEP",
        handler="pipeline.handlers.verify",
        order=15,
        phase=2,
    ),
    PipelineStep(
        name="VALIDATE_OC",
        label="Check OC eligibility",
        handler="pipeline.handlers.validate_oc",
        order=16,
        phase=2,
    ),
    PipelineStep(
        name="ENABLE_OC",
        label="Enable for Orchestrated Campaigns",
        handler="pipeline.handlers.enable_oc",
        order=17,
        phase=2,
    ),
]
