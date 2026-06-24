from dataclasses import dataclass


@dataclass
class TemplatePipelineStep:
    name: str
    label: str
    handler: str
    order: int
    stub: bool = False  # True = reserved slot for next developer


TEMPLATE_PIPELINE_STEPS: list[TemplatePipelineStep] = [
    TemplatePipelineStep(
        name="LOAD_RAW",
        label="Load template from DB",
        handler="pipeline.template_handlers.load_raw",
        order=1,
    ),
    TemplatePipelineStep(
        name="CONVERT_PLACEHOLDERS",
        label="Convert ACC placeholders to AJO syntax",
        handler="pipeline.template_handlers.convert_placeholders",
        order=2,
    ),
    TemplatePipelineStep(
        name="RESOLVE_FOLDER",
        label="Resolve AJO folder ID by channel",
        handler="pipeline.template_handlers.resolve_folder",
        order=3,
    ),
    TemplatePipelineStep(
        name="BUILD_ENRICHED",
        label="Write enriched JSON to DB",
        handler="pipeline.template_handlers.build_enriched",
        order=4,
    ),
    # ── Stubs for next developer ──────────────────────────────────────────────
    TemplatePipelineStep(
        name="DUPLICATE_CHECK",
        label="Check if template already exists in AJO",
        handler="pipeline.template_handlers.duplicate_check_stub",
        order=5,
        stub=True,
    ),
    TemplatePipelineStep(
        name="BUILD_PAYLOAD",
        label="Build final AJO API payload",
        handler="pipeline.template_handlers.build_payload_stub",
        order=6,
        stub=True,
    ),
    TemplatePipelineStep(
        name="PUSH_TEMPLATE",
        label="POST template to AJO",
        handler="pipeline.template_handlers.push_template_stub",
        order=7,
        stub=True,
    ),
    TemplatePipelineStep(
        name="VERIFY",
        label="Verify template created in AJO",
        handler="pipeline.template_handlers.verify_stub",
        order=8,
        stub=True,
    ),
]
