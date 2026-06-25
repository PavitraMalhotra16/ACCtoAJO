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
    # ── Push to AJO (TEMPLATES.md §4–§8) ──────────────────────────────────────
    TemplatePipelineStep(
        name="BUILD_PAYLOAD",
        label="Build final AJO API payload",
        handler="pipeline.template_handlers.build_payload",
        order=5,
    ),
    TemplatePipelineStep(
        name="VALIDATE_FIELDS",
        label="Validate required fields",
        handler="pipeline.template_handlers.validate_fields",
        order=6,
    ),
    TemplatePipelineStep(
        name="PUSH_TEMPLATE",
        label="POST template to AJO",
        handler="pipeline.template_handlers.push_template",
        order=7,
    ),
    TemplatePipelineStep(
        name="VERIFY",
        label="Verify template created in AJO",
        handler="pipeline.template_handlers.verify",
        order=8,
    ),
]
