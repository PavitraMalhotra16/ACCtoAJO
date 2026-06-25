import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import InvalidToken as FernetInvalidToken
from sqlalchemy import select

from db import (
    AccTemplateParsed,
    AsyncSessionLocal,
    DestinationConnection,
    TemplateFolderConfig,
    TemplateJobItem,
)
from core.security import decrypt, encrypt
from pipeline.placeholder_config import get_ajo_mapping

log = logging.getLogger("acc_backend.pipeline.template_handlers")

# ── AJO Content Template endpoints / constants (TEMPLATES.md §3, §5, §6, §11) ──
IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"
TEMPLATES_URL = "https://platform.adobe.io/ajo/content/templates"
# POST/PUT must use this exact vendor content-type — application/json yields a 406 (§3).
TEMPLATE_CONTENT_TYPE = "application/vnd.adobe.ajo.template.v1+json"

_ALLOWED_TEMPLATE_TYPES = {"html", "html_primary_page", "html_sub_page", "content"}
_HTTP_TIMEOUT = 60.0


# ── Typed exceptions — let the runner map each failure to a distinct status ────
class TemplateSkipped(Exception):
    """Invalid input (§9 step 2) — runner marks the item SKIPPED."""


class TemplateFailed(Exception):
    """Recoverable per-template failure (400/409/5xx) — runner marks FAILED, continues."""


class TemplateManual(Exception):
    """413 payload too large — runner marks MANUAL, flag for manual review, continues."""


class VerificationFailed(Exception):
    """GET-verify failed/mismatched (§6) — runner marks VERIFICATION_FAILED."""


class FatalRunError(Exception):
    """403/406 config-level error — runner aborts the whole run (HALTED)."""

# ── Regex patterns ────────────────────────────────────────────────────────────
_RE_RECIPIENT = re.compile(r"(?:<%=|&lt;%=)\s*(recipient\.[\w.]+)\s*(?:%>|%&gt;)")
_RE_TARGET_DATA = re.compile(r"(?:<%=|&lt;%=)\s*(targetData\.[\w.]+)\s*(?:%>|%&gt;)")
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


# ── AJO push: auth + headers (self-contained — TEMPLATES.md §3) ────────────────

async def _get_ajo_token(dest: DestinationConnection, db, *, force_refresh: bool = False) -> str:
    """Return a usable AJO access token.

    Normally the token was fetched + encrypted at connect time (routes/auth.py) and is
    still valid (~24h), so we just decrypt it. If it is expired/near-expiry, or a 401 forced
    a refresh mid-run, we re-mint one in-module from the stored encrypted client credentials
    and persist it back. No dependency on the relational push module.
    """
    now = datetime.now(timezone.utc)
    buffer = timedelta(minutes=5)

    if not force_refresh and dest.token_expires_at and dest.token_expires_at > now + buffer:
        try:
            return decrypt(dest.encrypted_access_token)
        except FernetInvalidToken:
            # Key changed / token corrupt — fall through to a fresh mint.
            log.warning("Stored AJO token could not be decrypted — refreshing from credentials")

    if not dest.encrypted_credentials:
        raise TemplateFailed("401: AJO token expired and no stored credentials — reconnect AJO")
    try:
        raw = decrypt(dest.encrypted_credentials)
    except FernetInvalidToken:
        raise TemplateFailed("401: AJO credentials could not be decrypted — reconnect AJO")
    client_id, _, client_secret = raw.partition(":")
    if not client_id or not client_secret:
        raise TemplateFailed("401: stored AJO credentials malformed — reconnect AJO")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            IMS_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": IMS_SCOPES,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code != 200:
        raise TemplateFailed(f"401: token refresh failed — reconnect AJO ({resp.status_code})")

    payload = resp.json()
    new_token = payload.get("access_token")
    if not new_token:
        raise TemplateFailed("401: token refresh returned no access_token — reconnect AJO")
    expires_in = int(payload.get("expires_in", 3600))
    if expires_in > 86_400:
        expires_in //= 1000

    dest.encrypted_access_token = encrypt(new_token)
    dest.token_expires_at = now + timedelta(seconds=expires_in)
    await db.commit()
    log.info("AJO token refreshed in-module (expires in %ds)", expires_in)
    return new_token


async def _resolve_auth(ctx: dict, *, force_refresh: bool = False) -> dict:
    """Load the AJO destination + a usable token. Uses its own session so token-refresh
    commits don't entangle the runner's per-template session."""
    async with AsyncSessionLocal() as db:
        dest = (
            await db.execute(
                select(DestinationConnection).where(
                    DestinationConnection.id == ctx["destination_conn_id"]
                )
            )
        ).scalar_one_or_none()
        if not dest or not dest.authenticated:
            raise FatalRunError("403: AJO is not connected — connect AJO before pushing templates")
        token = await _get_ajo_token(dest, db, force_refresh=force_refresh)
        return {
            "token": token,
            "api_key": (dest.client_id or "").strip(),
            "org_id": dest.org_id.strip(),
            "sandbox": (dest.sandbox_name or "prod").strip(),
        }


def _headers(auth: dict, *, post: bool = False, accept: str = "application/json") -> dict:
    h = {
        "Authorization": f"Bearer {auth['token']}",
        "x-api-key": auth["api_key"],
        "x-gw-ims-org-id": auth["org_id"],
        "x-sandbox-name": auth["sandbox"],
        "Accept": accept,
    }
    if post:
        h["Content-Type"] = TEMPLATE_CONTENT_TYPE
    return h


def _error_detail(resp: httpx.Response) -> str:
    """Pull the most useful message out of an AJO/IMS error body (§7)."""
    try:
        body = resp.json()
    except Exception:
        return resp.text[:300]
    if isinstance(body, dict):
        return str(body.get("detail") or body.get("message") or body.get("title") or body)[:300]
    return str(body)[:300]


# ── Payload (re)builder — resume-safe: rebuilds from enriched_json in the DB ────

async def _load_enriched(ctx: dict) -> dict:
    """Read template_job_items.enriched_json for this item and parse it to a dict.
    Handles the "is it JSON?" contract — converts the stored string to JSON, or accepts a
    dict as-is. Raises TemplateFailed if absent/unparseable."""
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(TemplateJobItem).where(TemplateJobItem.id == ctx["item_id"]))
        ).scalar_one()
        raw = row.enriched_json
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TemplateFailed(f"400: stored enriched_json is not valid JSON ({exc})")
    raise TemplateFailed("400: no enriched_json found for this template — run earlier steps first")


def _build_ajo_payload(enriched: dict, channel: str) -> dict:
    """Transform enriched_json into the confirmed AJO Content Template POST shape (§4.1/§4.2).
    Description is synthesised here ('This template is about <name>') since the input has none."""
    name = (enriched.get("name") or "").strip()
    description = f"This template is about {name}"
    base = {
        "name": name,
        "description": description,
        "channels": [channel],
        "source": {"origin": "ajo", "metadata": {}},
        "parentFolderId": enriched.get("parentFolderId"),
    }
    if channel == "email":
        # html: sets only the body; subject is added by the marketer later (§10).
        # subType is intentionally omitted: although §4.1 shows "subType": "HTML", live AJO
        # rejects it for templateType html ("subType is only supported with ... code channel").
        # §4.3 says it is optional with no functional effect for email, so we leave it off.
        base["templateType"] = "html"
        base["template"] = {"html": enriched.get("convertedHtml") or "", "editorContext": {}}
    elif channel == "sms":
        # SMS uses templateType "content" ("text" is not valid) (§10).
        base["templateType"] = "content"
        base["template"] = {"body": enriched.get("convertedSmsBody") or "", "editorContext": {}}
    else:
        raise TemplateSkipped(f"unsupported channel {channel!r} — must be email or sms")
    return base


async def _ensure_payload(ctx: dict, data: dict) -> dict:
    """Return the in-memory AJO payload, or rebuild it from enriched_json when a resume
    skipped BUILD_PAYLOAD. Keeps PUSH/VALIDATE/VERIFY correct on resumed runs."""
    payload = data.get("ajoPayload")
    if payload:
        return payload
    enriched = await _load_enriched(ctx)
    channel = enriched.get("channel") or data.get("channel", "email")
    payload = _build_ajo_payload(enriched, channel)
    data["ajoPayload"] = payload
    return payload


# ── Step 5: BUILD_PAYLOAD ──────────────────────────────────────────────────────

async def build_payload(ctx: dict, data: dict, db) -> dict:
    """Step 5: read enriched_json (DB, source of truth) → final AJO POST payload."""
    enriched = await _load_enriched(ctx)
    channel = enriched.get("channel") or data.get("channel", "email")
    payload = _build_ajo_payload(enriched, channel)
    return {**data, "channel": channel, "ajoPayload": payload}


# ── Step 6: VALIDATE_FIELDS (TEMPLATES.md §9 step 2) ───────────────────────────

async def validate_fields(ctx: dict, data: dict, db) -> dict:
    """Step 6: validate the built payload's required fields; invalid → SKIPPED."""
    payload = await _ensure_payload(ctx, data)

    if not (payload.get("name") or "").strip():
        raise TemplateSkipped("name is required and cannot be empty")
    if payload.get("templateType") not in _ALLOWED_TEMPLATE_TYPES:
        raise TemplateSkipped(
            f"templateType must be one of {sorted(_ALLOWED_TEMPLATE_TYPES)}, got {payload.get('templateType')!r}"
        )
    channels = payload.get("channels")
    if channels not in (["email"], ["sms"]):
        raise TemplateSkipped('channels must be ["email"] or ["sms"]')
    tmpl = payload.get("template") or {}
    if channels == ["email"] and not (tmpl.get("html") or "").strip():
        raise TemplateSkipped("template.html is required for email")
    if channels == ["sms"] and not (tmpl.get("body") or "").strip():
        raise TemplateSkipped("template.body is required for SMS")
    if not (payload.get("parentFolderId") or "").strip():
        raise TemplateSkipped("parentFolderId is required and cannot be empty")

    return {**data, "ajoPayload": payload}


# ── Step 7: PUSH_TEMPLATE (TEMPLATES.md §5 + §8 error table) ───────────────────

def _id_from_body(resp: httpx.Response) -> str | None:
    try:
        body = resp.json()
    except Exception:
        return None
    return body.get("id") if isinstance(body, dict) else None


def _id_from_location(resp: httpx.Response) -> str | None:
    """Last path segment of a Location header (REST 201 convention)."""
    loc = resp.headers.get("Location") or resp.headers.get("location") or ""
    if not loc:
        return None
    return loc.rstrip("/").rsplit("/", 1)[-1] or None


async def _find_template_id_by_name(auth: dict, name: str | None) -> str | None:
    """Fallback for an empty-body 201: list templates newest-first and match by name."""
    if not name:
        return None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            TEMPLATES_URL, headers=_headers(auth), params={"orderBy": "-createdAt", "limit": 50}
        )
    if resp.status_code != 200:
        return None
    try:
        items = resp.json().get("items", [])
    except Exception:
        return None
    for item in items:
        if item.get("name") == name:
            return item.get("id")
    return None


async def push_template(ctx: dict, data: dict, db) -> dict:
    """Step 7: POST the payload to AJO; handle every §8 status code; store the id on 201."""
    payload = await _ensure_payload(ctx, data)
    auth = await _resolve_auth(ctx)

    did_refresh = False
    rate_retries = 0
    server_retries = 0
    while True:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(TEMPLATES_URL, headers=_headers(auth, post=True), json=payload)
        code = resp.status_code

        if code == 201:
            # Spec §5 says 201 returns the template JSON, but live AJO sometimes returns 201
            # with an empty body. Resolve the id from the body, else the Location header,
            # else by listing templates and matching the name.
            template_id = _id_from_body(resp) or _id_from_location(resp)
            if not template_id:
                template_id = await _find_template_id_by_name(auth, payload.get("name"))
            if not template_id:
                raise TemplateFailed("201: created but AJO returned no id (empty body/Location) and name lookup failed")
            break

        detail = _error_detail(resp)
        if code == 400:
            raise TemplateFailed(f"400: {detail}")
        if code == 401:
            if did_refresh:
                raise TemplateFailed("401: token refresh did not resolve auth — reconnect AJO")
            auth = await _resolve_auth(ctx, force_refresh=True)
            did_refresh = True
            continue
        if code == 403:
            raise FatalRunError(f"403: {detail}")
        if code == 406:
            raise FatalRunError(f"406: {detail}")
        if code == 409:
            raise TemplateFailed(f"409: {detail}")
        if code == 413:
            raise TemplateManual(f"413: {detail}")
        if code == 429:
            if rate_retries >= 3:
                raise TemplateFailed(f"429: rate limited — retries exhausted: {detail}")
            wait = float(resp.headers.get("Retry-After") or 2)
            await asyncio.sleep(wait * (2 ** rate_retries))  # honour Retry-After, back off (§10)
            rate_retries += 1
            continue
        if code in (500, 503):
            if server_retries >= 1:
                raise TemplateFailed(f"{code}: {detail}")
            await asyncio.sleep(3)
            server_retries += 1
            continue
        raise TemplateFailed(f"{code}: {detail}")

    # Persist the AJO id against this template's row (keyed by unique id = item_id).
    async with AsyncSessionLocal() as sess:
        row = (
            await sess.execute(select(TemplateJobItem).where(TemplateJobItem.id == ctx["item_id"]))
        ).scalar_one()
        row.ajo_template_id = template_id
        await sess.commit()

    return {**data, "ajoPayload": payload, "ajoTemplateId": template_id}


# ── Step 8: VERIFY (TEMPLATES.md §6) ───────────────────────────────────────────

async def _resolve_template_id(ctx: dict, data: dict) -> str:
    """In-memory id, or the persisted ajo_template_id from the DB (resume-safe)."""
    template_id = data.get("ajoTemplateId")
    if template_id:
        return template_id
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(TemplateJobItem).where(TemplateJobItem.id == ctx["item_id"]))
        ).scalar_one()
        template_id = row.ajo_template_id
    if not template_id:
        raise VerificationFailed("no AJO template id to verify — push may not have completed")
    return template_id


async def verify(ctx: dict, data: dict, db) -> dict:
    """Step 8: GET the template by id; confirm 200 + name/channels/status DRAFT (§6)."""
    template_id = await _resolve_template_id(ctx, data)
    payload = await _ensure_payload(ctx, data)
    auth = await _resolve_auth(ctx)

    # The GET-by-id endpoint serves only the vendor representation — Accept: application/json
    # is rejected with 406, so request the template media type (same family as the POST body).
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(
            f"{TEMPLATES_URL}/{template_id}", headers=_headers(auth, accept=TEMPLATE_CONTENT_TYPE)
        )

    if resp.status_code != 200:
        raise VerificationFailed(f"{resp.status_code}: verify GET failed: {_error_detail(resp)}")
    body = resp.json()
    if body.get("name") != payload.get("name"):
        raise VerificationFailed(
            f"verify mismatch: name {body.get('name')!r} != {payload.get('name')!r}"
        )
    if body.get("channels") != payload.get("channels"):
        raise VerificationFailed(
            f"verify mismatch: channels {body.get('channels')!r} != {payload.get('channels')!r}"
        )
    # status is only DRAFT for templates and the live vendor representation may omit it —
    # a 200 with matching name + channels already proves creation. Only fail on a present,
    # non-DRAFT status.
    status = body.get("status")
    if status is not None and status != "DRAFT":
        raise VerificationFailed(f"verify mismatch: status {status!r} (expected DRAFT)")

    return {**data, "ajoTemplateId": template_id, "verified": True}
