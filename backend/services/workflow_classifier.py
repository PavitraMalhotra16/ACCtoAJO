"""
LLM-based workflow classifier using Google Gemini.

Classification rules and model fallback chain are loaded from
backend/config/classifier_config.json — edit that file to change
rules or swap models without touching code.

Returns {"classification": "orchestrated_campaign"|"journey"|"unsupported", "reason": str}
"""

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("acc_backend.workflow_classifier")

_CONFIG_PATH = Path(__file__).parent.parent / "pipeline" / "classifier_config.json"


def _load_config() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_system_prompt(config: dict) -> str:
    """Build the system prompt from classifier_config.json classification rules."""
    rules_lines = []
    for key, cls in config["classifications"].items():
        indicators = "\n".join(f"   - {i}" for i in cls["indicators"])
        rules_lines.append(f'{len(rules_lines)+1}. "{key}" — {cls["description"]}\n  Signs:\n{indicators}')

    classification_rules = "\n\n".join(rules_lines)
    return config["prompt"]["system"].replace("{classification_rules}", classification_rules)


async def classify_workflow(workflow_data: dict) -> dict:
    """
    Classify a workflow using Gemini (falls back through model list, then rule-based).

    Returns {"classification": "orchestrated_campaign"|"journey"|"unsupported", "reason": str}
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    config = _load_config()
    models = config["models"]

    if not api_key:
        log.warning("GEMINI_API_KEY not set — falling back to rule-based classification")
        return _rule_based_classify(config)

    for model in models:
        try:
            return await _gemini_classify(workflow_data, api_key, model, config)
        except Exception as exc:
            log.warning("Gemini model '%s' failed (%s) — trying next fallback", model, exc)

    log.warning("All Gemini models exhausted — falling back to rule-based classification")
    return _rule_based_classify(config, workflow_data)


async def _gemini_classify(workflow_data: dict, api_key: str, model: str, config: dict) -> dict:
    from google import genai

    activities = workflow_data.get("activities", [])
    edges = workflow_data.get("edges", [])

    activity_summary = [
        {"type": a.get("type"), "name": a.get("name"), "label": a.get("label")}
        for a in activities
    ]
    edge_summary = [
        {"from": e.get("fromActivity"), "to": e.get("toActivity"), "type": e.get("transitionType")}
        for e in edges
    ]

    user_message = (
        config["prompt"]["user_template"]
        .replace("{workflow_name}", workflow_data.get("label", workflow_data.get("internalName", "unknown")))
        .replace("{activity_count}", str(len(activities)))
        .replace("{activities}", json.dumps(activity_summary, indent=2))
        .replace("{edge_count}", str(len(edges)))
        .replace("{edges}", json.dumps(edge_summary, indent=2))
    )

    system_prompt = _build_system_prompt(config)

    log.info("Classifying workflow with model '%s'", model)
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=f"{system_prompt}\n\n{user_message}",
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    result = json.loads(text)
    classification = result.get("classification", "unsupported")
    reason = result.get("reason", "")

    valid = set(config["classifications"].keys())
    if classification not in valid:
        classification = "unsupported"
        reason = f"Unexpected Gemini response: {text[:200]}"

    log.info("Gemini classified workflow as '%s': %s", classification, reason)
    return {"classification": classification, "reason": reason}


def _rule_based_classify(config: dict, workflow_data: dict | None = None) -> dict:
    """Deterministic fallback — uses activity_types lists from classifier_config.json."""
    if not workflow_data:
        return {"classification": "unsupported", "reason": "No workflow data available"}

    types = {a.get("type", "") for a in workflow_data.get("activities", [])}
    classifications = config["classifications"]

    for key in ("unsupported", "journey", "orchestrated_campaign"):
        activity_types = set(classifications[key].get("activity_types", []))
        if types & activity_types:
            matched = sorted(types & activity_types)
            return {
                "classification": key,
                "reason": f"Contains {key} activity types: {matched}",
            }

    return {
        "classification": "orchestrated_campaign",
        "reason": "Simple workflow with no disqualifying activity types",
    }
