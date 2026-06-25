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
]
