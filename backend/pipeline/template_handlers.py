import json
import logging
import re

from sqlalchemy import select

from db import AccTemplateParsed, TemplateFolderConfig, TemplateJobItem, AsyncSessionLocal
from pipeline.placeholder_config import get_ajo_mapping

log = logging.getLogger("acc_backend.pipeline.template_handlers")

# ── Regex patterns ────────────────────────────────────────────────────────────
_RE_RECIPIENT = re.compile(r"<%=\s*(recipient\.\w+)\s*%>")
_RE_TARGET_DATA = re.compile(r"<%=\s*(targetData\.\w+)\s*%>")
_RE_SCRIPTLET = re.compile(r"<%@[^%]*%>")
_RE_CONTROL = re.compile(r"<%\s*(if|for|else|end)\b")
_RE_EXPR_GENERIC = re.compile(r"<%=([^%]+)%>")
_RE_NL_REQUIRE = re.compile(r"NL\.Require\s*\(")
_RE_FORMAT_FN = re.compile(r"\b(formatDate|formatPrice)\s*\(")
_RE_IMG_SRC = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
_RE_BG_IMG = re.compile(r'background-image\s*:\s*url\(["\']?([^"\')\s]+)["\']?\)', re.IGNORECASE)
_RE_SIGNED = re.compile(r"(token=|expires=|X-Amz-Expires=)", re.IGNORECASE)


def _apply_placeholder_map(text: str, placeholder_map: dict[str, str]) -> tuple[str, list[dict]]:
    """Replace <%= recipient.x %> and <%= targetData.x %> using the approved map.
    Returns (converted_text, warnings_list)."""
    warnings: list[dict] = []

    def _replace_recipient(m: re.Match) -> str:
        field = m.group(1)
        mapped = placeholder_map.get(field) or get_ajo_mapping(field)
        if mapped:
            return "{{" + mapped + "}}"
        warnings.append({"type": "unmapped_placeholder", "raw": m.group(0), "field": field})
        return m.group(0)

    def _replace_target(m: re.Match) -> str:
        field = m.group(1)
        mapped = placeholder_map.get(field) or get_ajo_mapping(field)
        if mapped:
            return "{{" + mapped + "}}"
        # fallback: bracket swap with context prefix
        return "{{context." + field + "}}"

    text = _RE_RECIPIENT.sub(_replace_recipient, text)
    text = _RE_TARGET_DATA.sub(_replace_target, text)

    # Fixed token replacements
    text = text.replace("%UNSUB%", "{{unsubscribeLink}}")
    text = text.replace("%MIRROR%", "{{mirrorPageLink}}")

    # Scriptlets → flag
    for m in _RE_SCRIPTLET.finditer(text):
        warnings.append({"type": "scriptlet", "raw": m.group(0)})

    # Control flow → flag
    for m in _RE_CONTROL.finditer(text):
        warnings.append({"type": "control_flow", "raw": m.group(0)})

    # Campaign helpers → flag
    for m in _RE_FORMAT_FN.finditer(text):
        warnings.append({"type": "manual_migration", "raw": m.group(0)})

    # NL.Require → flag
    for m in _RE_NL_REQUIRE.finditer(text):
        warnings.append({"type": "server_side_cannot_migrate", "raw": "NL.Require()"})

    return text, warnings


def _audit_images(html: str) -> list[dict]:
    """Scan image references and return per-image audit entries."""
    audits: list[dict] = []
    for m in _RE_IMG_SRC.finditer(html):
        url = m.group(1)
        audits.append(_classify_url(url, "img-src"))
    for m in _RE_BG_IMG.finditer(html):
        url = m.group(1)
        audits.append(_classify_url(url, "css-background"))
    return audits


def _classify_url(url: str, found_in: str) -> dict:
    entry: dict = {"url": url, "foundIn": found_in}
    if url.startswith("data:"):
        entry["status"] = "base64_image"
    elif url.startswith("http://"):
        entry["status"] = "http_image"
    elif not url.startswith("https://"):
        entry["status"] = "relative_url"
    elif _RE_SIGNED.search(url):
        entry["status"] = "signed_url"
    elif _RE_EXPR_GENERIC.search(url):
        entry["status"] = "dynamic_url"
    else:
        entry["status"] = "ok"
    return entry


# ── Step handlers ─────────────────────────────────────────────────────────────

async def load_raw(ctx: dict, data: dict, db) -> dict:
    """Step 1: Load one row from acc_deliverytemplate_parsed."""
    result = await db.execute(
        select(AccTemplateParsed).where(
            AccTemplateParsed.source_id == ctx["source_id"],
            AccTemplateParsed.login_id == ctx["login_id"],
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError(f"Template source_id={ctx['source_id']} not found in acc_deliverytemplate_parsed")

    parsed = json.loads(row.template_data) if row.template_data else {}
    return {
        **data,
        "sourceId": parsed.get("sourceId", ctx["source_id"]),
        "internalName": parsed.get("internalName", ""),
        "label": parsed.get("label", ""),
        "description": parsed.get("description", ""),
        "channel": parsed.get("channel", "email"),
        "subject": parsed.get("subject", ""),
        "htmlBody": parsed.get("htmlBody", ""),
        "smsContent": parsed.get("smsContent", ""),
    }


async def convert_placeholders(ctx: dict, data: dict, db) -> dict:
    """Step 2: Convert ACC syntax to AJO syntax in HTML/SMS/subject."""
    placeholder_map: dict[str, str] = ctx.get("placeholder_map", {})
    channel = data.get("channel", "email")
    all_warnings: list[dict] = []

    if channel == "email":
        html, w1 = _apply_placeholder_map(data.get("htmlBody", ""), placeholder_map)
        subj, w2 = _apply_placeholder_map(data.get("subject", ""), placeholder_map)
        image_audit = _audit_images(html)
        all_warnings.extend(w1)
        all_warnings.extend(w2)
        all_warnings.extend(
            {"type": a["status"], "url": a["url"], "foundIn": a["foundIn"]}
            for a in image_audit
            if a["status"] != "ok"
        )
        return {**data, "convertedHtml": html, "convertedSubject": subj,
                "convertedSmsBody": None, "imageAudit": image_audit, "warnings": all_warnings}
    else:
        sms, w = _apply_placeholder_map(data.get("smsContent", ""), placeholder_map)
        all_warnings.extend(w)
        return {**data, "convertedHtml": None, "convertedSubject": None,
                "convertedSmsBody": sms, "imageAudit": [], "warnings": all_warnings}


async def resolve_folder(ctx: dict, data: dict, db) -> dict:
    """Step 3: Look up parentFolderId from template_folder_config."""
    result = await db.execute(
        select(TemplateFolderConfig).where(
            TemplateFolderConfig.destination_conn_id == ctx["destination_conn_id"],
            TemplateFolderConfig.channel == data["channel"],
        )
    )
    cfg = result.scalar_one_or_none()
    if not cfg:
        raise ValueError(
            f"AJO {data['channel']} folder not configured — run setup first"
        )
    return {**data, "parentFolderId": cfg.parent_folder_id}


async def build_enriched(ctx: dict, data: dict, db) -> dict:
    """Step 4: Write enriched_json to template_job_items."""
    payload = {
        "sourceId": data.get("sourceId"),
        "internalName": data.get("internalName"),
        "channel": data.get("channel"),
        "name": data.get("label"),
        "description": data.get("description", ""),
        "subject": data.get("convertedSubject"),
        "convertedHtml": data.get("convertedHtml"),
        "convertedSmsBody": data.get("convertedSmsBody"),
        "parentFolderId": data.get("parentFolderId"),
        "warnings": data.get("warnings", []),
        "imageAudit": data.get("imageAudit", []),
        "source": {"origin": "ajo", "metadata": {}},
    }
    async with AsyncSessionLocal() as sess:
        result = await sess.execute(
            select(TemplateJobItem).where(TemplateJobItem.id == ctx["item_id"])
        )
        item = result.scalar_one()
        item.enriched_json = json.dumps(payload)
        await sess.commit()
    return {**data, "enrichedPayload": payload}


# ── Stubs for next developer ──────────────────────────────────────────────────

async def duplicate_check_stub(ctx: dict, data: dict, db) -> dict:
    """Step 5 stub: check if template already exists in AJO by name."""
    raise NotImplementedError("duplicate_check: implement in next developer's phase")


async def build_payload_stub(ctx: dict, data: dict, db) -> dict:
    """Step 6 stub: build final AJO POST payload from enriched_json."""
    raise NotImplementedError("build_payload: implement in next developer's phase")


async def push_template_stub(ctx: dict, data: dict, db) -> dict:
    """Step 7 stub: POST template to AJO content templates API."""
    raise NotImplementedError("push_template: implement in next developer's phase")


async def verify_stub(ctx: dict, data: dict, db) -> dict:
    """Step 8 stub: GET template from AJO to confirm creation."""
    raise NotImplementedError("verify: implement in next developer's phase")
