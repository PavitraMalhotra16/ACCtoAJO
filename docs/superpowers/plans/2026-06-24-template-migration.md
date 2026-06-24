# Template Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ACC → AJO template migration pipeline: folder setup, placeholder analysis + user review, conversion, enriched JSON output, and live aggregate progress UI.

**Architecture:** Mirrors the existing schema migration pipeline — ORM models in `db.py`, step definitions in `template_pipeline_steps.py`, handlers in `pipeline/template_handlers.py`, orchestration in `pipeline/template_runner.py`, and routes added to `routes/templates.py`. Frontend adds three pages (setup, analysis, run) wired into `App.tsx`.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy async / asyncpg / React + TypeScript + Vite + Tailwind + react-router-dom / pytest + aiosqlite

---

## Context You Must Know Before Starting

- **Source table:** `acc_deliverytemplate_parsed` — ORM class `AccTemplateParsed` in `db.py`. The JSON blob is in the `template_data` (Text) column. JSON keys: `sourceId`, `internalName`, `label`, `description`, `channel`, `lastModified`, `subject`, `htmlBody`, `textBody`, `smsContent`.
- **`DestinationConnection.id`** is a `String` UUID (not integer). Use it as `destination_conn_id` in all new tables.
- **AJO access token:** use `get_valid_access_token(dest, db)` from `pipeline.handlers` — it refreshes automatically.
- **`routes/templates.py` already exists** with extraction routes. Add migration routes to the SAME file (new section at the bottom).
- **`main.py` already imports** `templates_router` — no change needed there.
- **DB init:** new tables use `Base.metadata.create_all` in `init_db()` — no manual ALTER needed for new tables.
- **Tests:** mock `AsyncSessionLocal` and never hit real DB or network. Follow `tests/test_handlers.py` pattern.
- **Backend restart required** after any backend code change (no `--reload`). Use `scripts/start-backend.ps1`.

---

## File Map

**Create:**
- `backend/pipeline/placeholder_config.py` — `RECIPIENT_MAPPINGS` dict
- `backend/template_pipeline_steps.py` — 8-step definitions
- `backend/pipeline/template_handlers.py` — step 1–4 handlers + stubs 5–8
- `backend/pipeline/template_runner.py` — async orchestration
- `frontend_app/src/pages/TemplateAnalysisPage.tsx` — placeholder review
- `frontend_app/src/pages/TemplateRunPage.tsx` — progress bars + summary

**Modify:**
- `backend/db.py` — add 3 ORM models + `init_db` ALTER stmts
- `backend/routes/templates.py` — add 5 migration routes
- `frontend_app/src/App.tsx` — add 2 new routes
- `frontend_app/src/pages/TemplateMigrationPage.tsx` — rebuild as setup page

---

## Task 1: DB Models

**Files:**
- Modify: `backend/db.py`

- [ ] **Step 1: Write failing test for new models**

In `backend/tests/test_db_schema_sync.py`, add at the bottom:

```python
def test_template_models_registered():
    from db import TemplateFolderConfig, TemplateMigrationRun, TemplateJobItem
    tables = {m.class_.__tablename__ for m in Base.registry.mappers}
    assert "template_folder_config" in tables
    assert "template_migration_runs" in tables
    assert "template_job_items" in tables
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_db_schema_sync.py::test_template_models_registered -v
```

Expected: `ImportError` or `AssertionError`

- [ ] **Step 3: Add ORM models to `db.py`**

After the `TenantConfig` class (around line 95), add:

```python
class TemplateFolderConfig(Base):
    __tablename__ = "template_folder_config"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    destination_conn_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)          # 'email' | 'sms'
    folder_name: Mapped[str] = mapped_column(String(255), nullable=False)     # user-typed sample name
    parent_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TemplateMigrationRun(Base):
    __tablename__ = "template_migration_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    destination_conn_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    placeholder_map: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TemplateJobItem(Base):
    __tablename__ = "template_job_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_step_order: Mapped[int] = mapped_column(Integer, default=0)
    enriched_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ajo_template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_db_schema_sync.py::test_template_models_registered -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_db_schema_sync.py
git commit -m "feat: add TemplateFolderConfig, TemplateMigrationRun, TemplateJobItem ORM models"
```

---

## Task 2: Placeholder Config

**Files:**
- Create: `backend/pipeline/placeholder_config.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_placeholder_config.py`:

```python
from pipeline.placeholder_config import get_ajo_mapping


def test_known_recipient_field():
    assert get_ajo_mapping("recipient.firstName") == "profile.person.name.firstName"


def test_unknown_recipient_field_gets_profile_prefix():
    assert get_ajo_mapping("recipient.customField") == "profile.customField"


def test_target_data_field_gets_context_prefix():
    assert get_ajo_mapping("targetData.orderId") == "context.targetData.orderId"


def test_unknown_prefix_returns_none():
    assert get_ajo_mapping("delivery.something") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_placeholder_config.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `backend/pipeline/placeholder_config.py`**

```python
RECIPIENT_MAPPINGS: dict[str, str] = {
    "recipient.firstName":      "profile.person.name.firstName",
    "recipient.lastName":       "profile.person.name.lastName",
    "recipient.email":          "profile.workEmail.address",
    "recipient.phone":          "profile.mobilePhone.number",
    "recipient.mobilePhone":    "profile.mobilePhone.number",
    "recipient.gender":         "profile.person.gender",
    "recipient.birthDate":      "profile.person.birthDate",
    "recipient.language":       "profile.preferredLanguage",
}


def get_ajo_mapping(acc_field: str) -> str | None:
    """
    Map an ACC placeholder field name to its AJO equivalent.

    recipient.x  → RECIPIENT_MAPPINGS lookup, else profile.x
    targetData.x → context.targetData.x
    anything else → None (caller decides how to handle)
    """
    if acc_field in RECIPIENT_MAPPINGS:
        return RECIPIENT_MAPPINGS[acc_field]
    if acc_field.startswith("recipient."):
        suffix = acc_field[len("recipient."):]
        return f"profile.{suffix}"
    if acc_field.startswith("targetData."):
        return f"context.{acc_field}"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_placeholder_config.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/placeholder_config.py backend/tests/test_placeholder_config.py
git commit -m "feat: add placeholder_config with ACC→AJO field mapping"
```

---

## Task 3: Pipeline Step Definitions

**Files:**
- Create: `backend/template_pipeline_steps.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_template_pipeline_steps.py`:

```python
from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS


def test_steps_ordered_correctly():
    orders = [s.order for s in TEMPLATE_PIPELINE_STEPS]
    assert orders == sorted(orders)
    assert orders[0] == 1


def test_has_eight_steps():
    assert len(TEMPLATE_PIPELINE_STEPS) == 8


def test_active_steps_are_1_to_4():
    active = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
    assert len(active) == 4
    assert [s.name for s in active] == [
        "LOAD_RAW", "CONVERT_PLACEHOLDERS", "RESOLVE_FOLDER", "BUILD_ENRICHED"
    ]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_template_pipeline_steps.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `backend/template_pipeline_steps.py`**

```python
from dataclasses import dataclass, field


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_template_pipeline_steps.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/template_pipeline_steps.py backend/tests/test_template_pipeline_steps.py
git commit -m "feat: add template pipeline step definitions"
```

---

## Task 4: Template Handlers (Steps 1–4 + Stubs)

**Files:**
- Create: `backend/pipeline/template_handlers.py`
- Create: `backend/tests/test_template_handlers.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_template_handlers.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── load_raw ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_raw_parses_template_data():
    from pipeline.template_handlers import load_raw

    template_data = {
        "sourceId": "100",
        "internalName": "welcome_email",
        "label": "Welcome Email",
        "channel": "email",
        "subject": "Hi there",
        "htmlBody": "<html>Hello</html>",
        "smsContent": "",
        "description": "",
    }
    mock_row = MagicMock()
    mock_row.template_data = json.dumps(template_data)
    mock_row.source_id = "100"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = {"source_id": "100", "login_id": "user@example.com"}
    data = await load_raw(ctx, {}, mock_db)

    assert data["channel"] == "email"
    assert data["htmlBody"] == "<html>Hello</html>"
    assert data["label"] == "Welcome Email"


@pytest.mark.asyncio
async def test_load_raw_raises_on_missing_row():
    from pipeline.template_handlers import load_raw

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="not found"):
        await load_raw({"source_id": "999", "login_id": "u"}, {}, mock_db)


# ── convert_placeholders ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_convert_recipient_placeholder():
    from pipeline.template_handlers import convert_placeholders

    placeholder_map = {"recipient.firstName": "profile.person.name.firstName"}
    ctx = {"placeholder_map": placeholder_map}
    data = {
        "channel": "email",
        "htmlBody": "<p>Hi <%= recipient.firstName %></p>",
        "subject": "Hello <%= recipient.firstName %>",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert "{{profile.person.name.firstName}}" in result["convertedHtml"]
    assert "{{profile.person.name.firstName}}" in result["convertedSubject"]
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_convert_unsub_token():
    from pipeline.template_handlers import convert_placeholders

    ctx = {"placeholder_map": {}}
    data = {
        "channel": "email",
        "htmlBody": '<a href="%UNSUB%">Unsubscribe</a>',
        "subject": "Test",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert "{{unsubscribeLink}}" in result["convertedHtml"]


@pytest.mark.asyncio
async def test_convert_scriptlet_goes_to_warnings():
    from pipeline.template_handlers import convert_placeholders

    ctx = {"placeholder_map": {}}
    data = {
        "channel": "email",
        "htmlBody": "<%@ include option='foo' %>",
        "subject": "Test",
        "smsContent": "",
    }
    result = await convert_placeholders(ctx, data, None)
    assert any(w["type"] == "scriptlet" for w in result["warnings"])


# ── resolve_folder ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_folder_returns_parent_id():
    from pipeline.template_handlers import resolve_folder

    mock_cfg = MagicMock()
    mock_cfg.parent_folder_id = "folder-uuid-abc"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_cfg

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    ctx = {"destination_conn_id": "dest-123"}
    data = {"channel": "email"}
    result = await resolve_folder(ctx, data, mock_db)
    assert result["parentFolderId"] == "folder-uuid-abc"


@pytest.mark.asyncio
async def test_resolve_folder_raises_if_not_configured():
    from pipeline.template_handlers import resolve_folder

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    with pytest.raises(ValueError, match="folder not configured"):
        await resolve_folder({"destination_conn_id": "x"}, {"channel": "email"}, mock_db)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_template_handlers.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `backend/pipeline/template_handlers.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_template_handlers.py -v
```

Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/template_handlers.py backend/tests/test_template_handlers.py
git commit -m "feat: add template pipeline handlers for steps 1-4"
```

---

## Task 5: Template Runner

**Files:**
- Create: `backend/pipeline/template_runner.py`
- Create: `backend/tests/test_template_runner.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_template_runner.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_template_updates_status_to_completed():
    from pipeline.template_runner import run_template

    with patch("pipeline.template_runner._update_item") as mock_update, \
         patch("pipeline.template_runner._load_handler") as mock_load:

        async def fake_handler(ctx, data, db):
            return {**data, "loaded": True}

        mock_load.return_value = fake_handler
        mock_update.return_value = None

        mock_db = AsyncMock()
        result = await run_template(
            item_id="item-1",
            source_id="100",
            login_id="user@test.com",
            destination_conn_id="dest-1",
            placeholder_map={"recipient.email": "profile.workEmail.address"},
            channel="email",
            db=mock_db,
        )
        assert result is True
        # COMPLETED should have been called
        completed_calls = [
            c for c in mock_update.call_args_list
            if c.args and c.args[1] == "COMPLETED"
        ]
        assert len(completed_calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_template_runner.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `backend/pipeline/template_runner.py`**

```python
import asyncio
import importlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db import AsyncSessionLocal, TemplateMigrationRun, TemplateJobItem
from template_pipeline_steps import TEMPLATE_PIPELINE_STEPS

log = logging.getLogger("acc_backend.pipeline.template_runner")

_ACTIVE_STEPS = [s for s in TEMPLATE_PIPELINE_STEPS if not s.stub]
_GLOBAL_SEM = asyncio.Semaphore(10)


async def _load_handler(dotted_path: str):
    module_path, fn_name = dotted_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, fn_name)


async def _update_item(item_id: str, status: str, step_name: str, step_order: int,
                       error_step: str | None = None, error_message: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TemplateJobItem).where(TemplateJobItem.id == item_id))
        item = result.scalar_one()
        item.status = status
        item.current_step = step_name
        item.current_step_order = step_order
        item.updated_at = datetime.now(timezone.utc)
        if error_step is not None:
            item.error_step = error_step
        if error_message is not None:
            item.error_message = error_message
        await db.commit()


async def run_template(
    item_id: str,
    source_id: str,
    login_id: str,
    destination_conn_id: str,
    placeholder_map: dict,
    channel: str,
    db,
) -> bool:
    """Run all active pipeline steps for one template. Returns True on success."""
    ctx = {
        "item_id": item_id,
        "source_id": source_id,
        "login_id": login_id,
        "destination_conn_id": destination_conn_id,
        "placeholder_map": placeholder_map,
    }
    data: dict = {"channel": channel}

    for step in _ACTIVE_STEPS:
        await _update_item(item_id, "RUNNING", step.name, step.order)
        try:
            handler = await _load_handler(step.handler)
            data = await handler(ctx, data, db)
        except Exception as exc:
            log.exception("Template %s failed at %s: %s", source_id, step.name, exc)
            await _update_item(
                item_id, "FAILED", step.name, step.order,
                error_step=step.name,
                error_message=str(exc) or type(exc).__name__,
            )
            return False

    await _update_item(item_id, "COMPLETED", "BUILD_ENRICHED", len(_ACTIVE_STEPS))
    return True


async def _run_one(item: dict, placeholder_map: dict, sem: asyncio.Semaphore) -> None:
    async with _GLOBAL_SEM:
        async with sem:
            async with AsyncSessionLocal() as db:
                await run_template(
                    item_id=item["id"],
                    source_id=item["source_id"],
                    login_id=item["login_id"],
                    destination_conn_id=item["destination_conn_id"],
                    placeholder_map=placeholder_map,
                    channel=item["channel"],
                    db=db,
                )


async def run_template_migration(run_id: str, items: list[dict], placeholder_map: dict) -> None:
    """Orchestrate concurrent template migration for all items in a run."""
    sem = asyncio.Semaphore(5)
    tasks = [asyncio.create_task(_run_one(item, placeholder_map, sem)) for item in items]
    await asyncio.gather(*tasks, return_exceptions=True)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id)
        )
        run = result.scalar_one()
        run.status = "COMPLETED"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    log.info("Template migration run %s complete", run_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && python -m pytest tests/test_template_runner.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/template_runner.py backend/tests/test_template_runner.py
git commit -m "feat: add template pipeline runner"
```

---

## Task 6: Backend Routes — Setup, Analysis, Migrate, Status

**Files:**
- Modify: `backend/routes/templates.py`

Add the following imports at the top of `routes/templates.py` (after existing imports):

```python
import asyncio
import uuid as uuid_module
from pydantic import BaseModel
from pipeline.placeholder_config import RECIPIENT_MAPPINGS, get_ajo_mapping
from pipeline.template_runner import run_template_migration
from db import (
    DestinationConnection, TemplateFolderConfig,
    TemplateMigrationRun, TemplateJobItem,
)
```

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_template_migration_routes.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_setup_returns_401_without_auth(client):
    resp = client.post("/api/templates/setup", json={
        "email_sample_name": "email sample",
        "sms_sample_name": "sms sample",
    })
    assert resp.status_code == 401


def test_analysis_returns_401_without_auth(client):
    resp = client.get("/api/templates/analysis")
    assert resp.status_code == 401


def test_run_status_404_for_unknown_run(client):
    with patch("routes.templates.get_login_from_cookie", return_value="user@test.com"):
        resp = client.get("/api/templates/runs/nonexistent-run-id/status",
                          cookies={"acc_user": "user@test.com"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_template_migration_routes.py -v
```

Expected: some PASS (401 tests may pass if route doesn't exist yet and FastAPI returns 404 not 401 — that's acceptable at this stage; we fix in implementation).

- [ ] **Step 3: Add helper `_require_ajo` and setup route to `routes/templates.py`**

Add at bottom of the file:

```python
# ── Template migration routes ─────────────────────────────────────────────────

async def _require_ajo(db: AsyncSession) -> DestinationConnection:
    result = await db.execute(
        select(DestinationConnection).where(DestinationConnection.authenticated == True)
    )
    dest = result.scalar_one_or_none()
    if not dest:
        raise HTTPException(400, "AJO not connected — connect AJO first")
    return dest


async def _get_valid_ajo_token(dest: DestinationConnection, db: AsyncSession) -> str:
    from pipeline.handlers import get_valid_access_token
    return await get_valid_access_token(dest, db)


class SetupRequest(BaseModel):
    email_sample_name: str
    sms_sample_name: str


@router.post("/api/templates/setup")
async def template_setup(
    body: SetupRequest,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    dest = await _require_ajo(db)
    token = await _get_valid_ajo_token(dest, db)

    import httpx
    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": dest.client_id or "",
        "x-gw-ims-org-id": dest.org_id,
        "x-sandbox-name": dest.sandbox_name or "prod",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://platform.adobe.io/ajo/content/templates",
            headers=headers,
            params={"orderBy": "-modifiedAt", "limit": 200},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"AJO GET /templates failed: {resp.status_code} {resp.text[:200]}")

    items = resp.json().get("items", [])
    name_to_folder: dict[str, str] = {
        item["name"]: item.get("parentFolderId", "")
        for item in items
        if item.get("parentFolderId")
    }

    results = {}
    for channel, sample_name in [("email", body.email_sample_name), ("sms", body.sms_sample_name)]:
        folder_id = name_to_folder.get(sample_name)
        if not folder_id:
            raise HTTPException(
                404,
                f"No template named '{sample_name}' with a parentFolderId found in AJO. "
                "Create the sample template inside a folder first."
            )
        existing = await db.execute(
            select(TemplateFolderConfig).where(
                TemplateFolderConfig.destination_conn_id == dest.id,
                TemplateFolderConfig.channel == channel,
            )
        )
        cfg = existing.scalar_one_or_none()
        if cfg:
            cfg.parent_folder_id = folder_id
            cfg.folder_name = sample_name
        else:
            db.add(TemplateFolderConfig(
                destination_conn_id=dest.id,
                channel=channel,
                folder_name=sample_name,
                parent_folder_id=folder_id,
            ))
        results[channel] = folder_id

    await db.commit()
    return {"email_folder_id": results["email"], "sms_folder_id": results["sms"]}
```

- [ ] **Step 4: Add analysis route**

```python
@router.get("/api/templates/analysis")
async def template_analysis(
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    result = await db.execute(
        select(AccTemplateParsed).where(AccTemplateParsed.login_id == login_id)
    )
    rows = result.scalars().all()

    import re
    re_recipient = re.compile(r"<%=\s*(recipient\.\w+)\s*%>")
    re_target = re.compile(r"<%=\s*(targetData\.\w+)\s*%>")

    unique_recipient: dict[str, str] = {}
    unique_target: dict[str, str] = {}

    for row in rows:
        if not row.template_data:
            continue
        parsed = json.loads(row.template_data)
        text = (parsed.get("htmlBody", "") or "") + " " + (parsed.get("smsContent", "") or "")
        for m in re_recipient.finditer(text):
            field = m.group(1)
            if field not in unique_recipient:
                unique_recipient[field] = get_ajo_mapping(field) or f"profile.{field.split('.', 1)[-1]}"
        for m in re_target.finditer(text):
            field = m.group(1)
            if field not in unique_target:
                unique_target[field] = f"context.{field}"

    return {
        "recipient": [
            {"acc": f"<%= {k} %>", "field": k, "ajo": v}
            for k, v in sorted(unique_recipient.items())
        ],
        "targetData": [
            {"acc": f"<%= {k} %>", "field": k, "ajo": v}
            for k, v in sorted(unique_target.items())
        ],
    }
```

- [ ] **Step 5: Add migrate and status routes**

```python
class MigrateRequest(BaseModel):
    placeholder_map: dict[str, str]  # acc_field → ajo_path, e.g. {"recipient.email": "profile.workEmail.address"}


@router.post("/api/templates/migrate")
async def template_migrate(
    body: MigrateRequest,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")
    dest = await _require_ajo(db)

    templates_result = await db.execute(
        select(AccTemplateParsed).where(AccTemplateParsed.login_id == login_id)
    )
    templates = templates_result.scalars().all()
    if not templates:
        raise HTTPException(400, "No templates found in acc_deliverytemplate_parsed for this user")

    run_id = str(uuid_module.uuid4())
    run = TemplateMigrationRun(
        run_id=run_id,
        destination_conn_id=dest.id,
        login_id=login_id,
        status="RUNNING",
        placeholder_map=json.dumps(body.placeholder_map),
    )
    db.add(run)
    await db.flush()

    items: list[dict] = []
    for tmpl in templates:
        parsed = json.loads(tmpl.template_data) if tmpl.template_data else {}
        channel = parsed.get("channel", "email")
        if channel not in ("email", "sms"):
            channel_status = "SKIPPED"
        else:
            channel_status = "PENDING"

        job_item = TemplateJobItem(
            run_id=run_id,
            source_id=tmpl.source_id,
            internal_name=parsed.get("internalName"),
            channel=channel,
            status=channel_status,
        )
        db.add(job_item)
        await db.flush()

        if channel_status == "PENDING":
            items.append({
                "id": job_item.id,
                "source_id": tmpl.source_id,
                "login_id": login_id,
                "destination_conn_id": dest.id,
                "channel": channel,
            })

    await db.commit()

    asyncio.create_task(
        run_template_migration(run_id, items, body.placeholder_map)
    )
    return {"run_id": run_id, "total": len(items)}


@router.get("/api/templates/runs/{run_id}/status")
async def template_run_status(
    run_id: str,
    acc_session: str | None = Cookie(default=None),
    acc_user: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    run_result = await db.execute(
        select(TemplateMigrationRun).where(TemplateMigrationRun.run_id == run_id)
    )
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    from sqlalchemy import func, case
    counts = await db.execute(
        select(
            TemplateJobItem.channel,
            TemplateJobItem.status,
            func.count().label("cnt"),
        )
        .where(TemplateJobItem.run_id == run_id)
        .group_by(TemplateJobItem.channel, TemplateJobItem.status)
    )
    rows = counts.all()

    def _tally(channel: str) -> dict:
        total = completed = failed = 0
        for r in rows:
            if r.channel == channel:
                total += r.cnt
                if r.status == "COMPLETED":
                    completed += r.cnt
                elif r.status == "FAILED":
                    failed += r.cnt
        return {"total": total, "completed": completed, "failed": failed}

    failures = []
    if run.status == "COMPLETED":
        fail_result = await db.execute(
            select(TemplateJobItem).where(
                TemplateJobItem.run_id == run_id,
                TemplateJobItem.status == "FAILED",
            )
        )
        for fi in fail_result.scalars().all():
            failures.append({
                "source_id": fi.source_id,
                "internal_name": fi.internal_name,
                "channel": fi.channel,
                "error_step": fi.error_step,
                "error_message": fi.error_message,
            })

    return {
        "status": run.status,
        "email": _tally("email"),
        "sms": _tally("sms"),
        "failures": failures,
    }
```

- [ ] **Step 6: Run all route tests**

```bash
cd backend && python -m pytest tests/test_template_migration_routes.py -v
```

Expected: 3 PASS

- [ ] **Step 7: Restart backend and smoke-test setup endpoint (requires live AJO)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
```

Then in another terminal:
```bash
curl -X POST http://localhost:8001/api/templates/setup \
  -H "Content-Type: application/json" \
  -d '{"email_sample_name":"email sample","sms_sample_name":"sms sample"}' \
  -b "acc_session=<your_session>"
```

Expected: `{"email_folder_id": "<uuid>", "sms_folder_id": "<uuid>"}`

- [ ] **Step 8: Commit**

```bash
git add backend/routes/templates.py backend/tests/test_template_migration_routes.py
git commit -m "feat: add template migration routes (setup, analysis, migrate, status)"
```

---

## Task 7: Frontend Routes

**Files:**
- Modify: `frontend_app/src/App.tsx`

- [ ] **Step 1: Add imports and routes to `App.tsx`**

Add imports after existing imports:
```typescript
import TemplateAnalysisPage from './pages/TemplateAnalysisPage'
import TemplateRunPage from './pages/TemplateRunPage'
```

Add routes inside `<Routes>` after the `/migration/template` route:
```tsx
<Route path="/migration/template/analysis" element={
  <ProtectedRoute condition={accConnected && ajoConnected}>
    <TemplateAnalysisPage />
  </ProtectedRoute>
} />
<Route path="/migration/template/run/:runId" element={
  <ProtectedRoute condition={accConnected && ajoConnected}>
    <TemplateRunPage />
  </ProtectedRoute>
} />
```

- [ ] **Step 2: Type-check**

```bash
cd frontend_app && npx tsc --noEmit
```

Expected: errors only about missing page files (TemplateAnalysisPage, TemplateRunPage) — those are created in Tasks 9 and 10.

- [ ] **Step 3: Commit**

```bash
git add frontend_app/src/App.tsx
git commit -m "feat: add template analysis and run routes to App.tsx"
```

---

## Task 8: Rebuild TemplateMigrationPage (Setup Phase)

**Files:**
- Modify: `frontend_app/src/pages/TemplateMigrationPage.tsx`

- [ ] **Step 1: Replace the stub with the setup page**

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function TemplateMigrationPage() {
  const navigate = useNavigate()
  const [emailName, setEmailName] = useState('email sample')
  const [smsName, setSmsName] = useState('sms sample')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleVerify() {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/templates/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_sample_name: emailName, sms_sample_name: smsName }),
        credentials: 'include',
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        throw new Error(body.detail || `Server error ${resp.status}`)
      }
      navigate('/migration/template/analysis')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg flex flex-col gap-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Template Migration — Setup</h1>
          <p className="mt-2 text-gray-500">Follow these steps before continuing</p>
        </div>

        <ol className="list-decimal list-inside space-y-2 text-sm text-gray-700 bg-gray-50 rounded-lg p-4 border border-gray-200">
          <li>In AJO, create a folder named <strong>Email</strong> and a folder named <strong>SMS</strong>.</li>
          <li>Inside the <strong>Email</strong> folder, create one template with the exact name below.</li>
          <li>Inside the <strong>SMS</strong> folder, create one template with the exact name below.</li>
          <li>Enter those names here and click <strong>Verify &amp; Continue</strong>.</li>
        </ol>

        <div className="flex flex-col gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Email sample template name
            </label>
            <input
              type="text"
              value={emailName}
              onChange={e => setEmailName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              SMS sample template name
            </label>
            <input
              type="text"
              value={smsName}
              onChange={e => setSmsName(e.target.value)}
              className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 rounded-md px-3 py-2 border border-red-200">
            {error}
          </p>
        )}

        <button
          onClick={handleVerify}
          disabled={loading || !emailName.trim() || !smsName.trim()}
          className="w-full rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
        >
          {loading ? 'Verifying…' : 'Verify & Continue'}
        </button>

        <button
          onClick={() => navigate('/migration/type')}
          className="text-sm text-center text-gray-400 hover:text-gray-600 transition-colors"
        >
          ← Back to migration type
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend_app && npx tsc --noEmit
```

Expected: 0 errors (or only errors from missing TemplateAnalysisPage/TemplateRunPage)

- [ ] **Step 3: Commit**

```bash
git add frontend_app/src/pages/TemplateMigrationPage.tsx
git commit -m "feat: rebuild TemplateMigrationPage as setup + folder verification page"
```

---

## Task 9: TemplateAnalysisPage (Placeholder Review)

**Files:**
- Create: `frontend_app/src/pages/TemplateAnalysisPage.tsx`

- [ ] **Step 1: Create the analysis page**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

interface PlaceholderRow {
  acc: string
  field: string
  ajo: string
}

interface AnalysisData {
  recipient: PlaceholderRow[]
  targetData: PlaceholderRow[]
}

function PlaceholderTable({
  title,
  rows,
  onEdit,
}: {
  title: string
  rows: PlaceholderRow[]
  onEdit: (field: string, newAjo: string) => void
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  function startEdit(row: PlaceholderRow) {
    setEditing(row.field)
    setDraft(row.ajo)
  }

  function commitEdit(field: string) {
    if (draft.trim()) onEdit(field, draft.trim())
    setEditing(null)
  }

  if (rows.length === 0) return null

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-700 mb-2">{title}</h2>
      <table className="w-full text-sm border border-gray-200 rounded-lg overflow-hidden">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            <th className="text-left px-3 py-2 font-medium">ACC Placeholder</th>
            <th className="text-left px-3 py-2 font-medium">AJO Mapping</th>
            <th className="px-3 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map(row => (
            <tr key={row.field} className="hover:bg-gray-50">
              <td className="px-3 py-2 font-mono text-xs text-gray-600">{row.acc}</td>
              <td className="px-3 py-2">
                {editing === row.field ? (
                  <input
                    autoFocus
                    value={draft}
                    onChange={e => setDraft(e.target.value)}
                    onBlur={() => commitEdit(row.field)}
                    onKeyDown={e => e.key === 'Enter' && commitEdit(row.field)}
                    className="w-full font-mono text-xs border border-purple-400 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-purple-500"
                  />
                ) : (
                  <span className="font-mono text-xs text-purple-700">
                    {`{{${row.ajo}}}`}
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  onClick={() => startEdit(row)}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                  title="Edit mapping"
                >
                  ✏️
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function TemplateAnalysisPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<AnalysisData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetch('/api/templates/analysis', { credentials: 'include' })
      .then(r => r.ok ? r.json() : r.json().then(b => Promise.reject(b.detail || 'Failed to load analysis')))
      .then(setData)
      .catch(e => setLoadError(String(e)))
  }, [])

  function editMapping(field: string, newAjo: string) {
    if (!data) return
    setData(prev => {
      if (!prev) return prev
      const update = (rows: PlaceholderRow[]) =>
        rows.map(r => r.field === field ? { ...r, ajo: newAjo } : r)
      return { recipient: update(prev.recipient), targetData: update(prev.targetData) }
    })
  }

  async function handleConfirm() {
    if (!data) return
    setSubmitting(true)
    const placeholder_map: Record<string, string> = {}
    for (const r of [...data.recipient, ...data.targetData]) {
      placeholder_map[r.field] = r.ajo
    }
    try {
      const resp = await fetch('/api/templates/migrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ placeholder_map }),
        credentials: 'include',
      })
      if (!resp.ok) {
        const b = await resp.json().catch(() => ({}))
        throw new Error(b.detail || `Error ${resp.status}`)
      }
      const { run_id } = await resp.json()
      navigate(`/migration/template/run/${run_id}`)
    } catch (e: any) {
      alert(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loadError) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-red-600">{loadError}</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">Scanning templates for placeholders…</p>
      </div>
    )
  }

  const totalPlaceholders = data.recipient.length + data.targetData.length

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="mx-auto max-w-3xl flex flex-col gap-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Placeholder Review</h1>
          <p className="mt-1 text-sm text-gray-500">
            Found <strong>{totalPlaceholders}</strong> unique placeholder(s) across all templates.
            Review the default AJO mappings and edit any you want to change.
          </p>
        </div>

        {totalPlaceholders === 0 ? (
          <p className="text-sm text-gray-500 bg-gray-50 rounded-lg px-4 py-3 border border-gray-200">
            No <code>recipient.*</code> or <code>targetData.*</code> placeholders found. You can proceed directly.
          </p>
        ) : (
          <div className="flex flex-col gap-6">
            <PlaceholderTable title="recipient.* placeholders" rows={data.recipient} onEdit={editMapping} />
            <PlaceholderTable title="targetData.* placeholders" rows={data.targetData} onEdit={editMapping} />
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={() => navigate('/migration/template')}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
          >
            ← Back
          </button>
          <button
            onClick={handleConfirm}
            disabled={submitting}
            className="flex-1 rounded-md bg-purple-600 px-4 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Starting migration…' : 'Confirm & Start Migration'}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend_app && npx tsc --noEmit
```

Expected: 0 errors (or only TemplateRunPage error)

- [ ] **Step 3: Commit**

```bash
git add frontend_app/src/pages/TemplateAnalysisPage.tsx
git commit -m "feat: add TemplateAnalysisPage with editable placeholder mapping table"
```

---

## Task 10: TemplateRunPage (Progress + Summary)

**Files:**
- Create: `frontend_app/src/pages/TemplateRunPage.tsx`

- [ ] **Step 1: Create the run page**

```tsx
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

interface ChannelCounts {
  total: number
  completed: number
  failed: number
}

interface FailureItem {
  source_id: string
  internal_name: string
  channel: string
  error_step: string
  error_message: string
}

interface RunStatus {
  status: string
  email: ChannelCounts
  sms: ChannelCounts
  failures: FailureItem[]
}

function ProgressBar({ label, counts, color }: { label: string; counts: ChannelCounts; color: string }) {
  const pct = counts.total === 0 ? 0 : Math.round((counts.completed / counts.total) * 100)
  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between text-sm">
        <span className="font-medium text-gray-700">{label}</span>
        <span className="text-gray-500">
          {counts.completed} / {counts.total} done
          {counts.failed > 0 && <span className="text-red-500 ml-2">({counts.failed} failed)</span>}
        </span>
      </div>
      <div className="h-3 w-full rounded-full bg-gray-200 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export default function TemplateRunPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [status, setStatus] = useState<RunStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showFailures, setShowFailures] = useState(false)

  useEffect(() => {
    if (!runId) return
    let stopped = false

    async function poll() {
      while (!stopped) {
        try {
          const resp = await fetch(`/api/templates/runs/${runId}/status`, { credentials: 'include' })
          if (!resp.ok) {
            const b = await resp.json().catch(() => ({}))
            setError(b.detail || `Error ${resp.status}`)
            return
          }
          const data: RunStatus = await resp.json()
          setStatus(data)
          if (data.status === 'COMPLETED' || data.status === 'FAILED') return
        } catch (e: any) {
          setError(e.message)
          return
        }
        await new Promise(r => setTimeout(r, 2500))
      }
    }

    poll()
    return () => { stopped = true }
  }, [runId])

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-red-600">{error}</p>
      </div>
    )
  }

  if (!status) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-500">Starting migration…</p>
      </div>
    )
  }

  const overall: ChannelCounts = {
    total: status.email.total + status.sms.total,
    completed: status.email.completed + status.sms.completed,
    failed: status.email.failed + status.sms.failed,
  }
  const isDone = status.status === 'COMPLETED' || status.status === 'FAILED'

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="mx-auto max-w-2xl flex flex-col gap-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Template Migration</h1>
          <p className="mt-1 text-sm text-gray-500">
            {isDone ? 'Migration complete.' : 'Migrating templates — this may take a few minutes.'}
          </p>
        </div>

        <div className="flex flex-col gap-4 bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
          <ProgressBar label="Email templates" counts={status.email} color="bg-purple-500" />
          <ProgressBar label="SMS templates" counts={status.sms} color="bg-blue-500" />
          <div className="border-t border-gray-100 pt-4">
            <ProgressBar label="Overall" counts={overall} color="bg-gray-700" />
          </div>
        </div>

        {isDone && (
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex flex-col gap-4">
            <h2 className="font-semibold text-gray-900">Summary</h2>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-purple-50 px-4 py-3">
                <p className="text-purple-700 font-medium">Email</p>
                <p className="text-gray-700">{status.email.completed} / {status.email.total} created</p>
              </div>
              <div className="rounded-lg bg-blue-50 px-4 py-3">
                <p className="text-blue-700 font-medium">SMS</p>
                <p className="text-gray-700">{status.sms.completed} / {status.sms.total} created</p>
              </div>
            </div>

            {overall.failed > 0 && (
              <div>
                <button
                  onClick={() => setShowFailures(v => !v)}
                  className="text-sm text-red-600 hover:text-red-800 font-medium"
                >
                  {showFailures ? '▲ Hide' : '▼ Show'} {overall.failed} failed template(s)
                </button>
                {showFailures && (
                  <table className="mt-3 w-full text-xs border border-gray-200 rounded-lg overflow-hidden">
                    <thead className="bg-gray-50 text-gray-600">
                      <tr>
                        <th className="text-left px-3 py-2">Internal Name</th>
                        <th className="text-left px-3 py-2">Channel</th>
                        <th className="text-left px-3 py-2">Failed at Step</th>
                        <th className="text-left px-3 py-2">Error</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {status.failures.map(f => (
                        <tr key={f.source_id} className="hover:bg-red-50">
                          <td className="px-3 py-2 font-mono">{f.internal_name || f.source_id}</td>
                          <td className="px-3 py-2">{f.channel}</td>
                          <td className="px-3 py-2 font-mono text-orange-600">{f.error_step}</td>
                          <td className="px-3 py-2 text-red-600 max-w-xs truncate">{f.error_message}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            <button
              onClick={() => navigate('/migration/type')}
              className="mt-2 rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors w-fit"
            >
              ← Back to migration type
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend_app && npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add frontend_app/src/pages/TemplateRunPage.tsx
git commit -m "feat: add TemplateRunPage with live progress bars and failure drill-down"
```

---

## Task 11: Run Full Test Suite

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && python -m pytest -q
```

Expected: all PASS, 0 failures

- [ ] **Step 2: Type-check frontend**

```bash
cd frontend_app && npx tsc --noEmit
```

Expected: 0 errors

- [ ] **Step 3: Start the app and walk through the full flow**

```powershell
# Terminal 1
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
# Terminal 2
powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
```

Walk through:
1. Log in → go to `/migration/type` → click Template
2. Enter sample template names → click Verify & Continue
3. Review placeholder table → edit one mapping → click Confirm & Start Migration
4. Watch progress bars update live
5. When complete, verify summary view and failure list appear

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete template migration pipeline — setup, analysis, conversion, run UI"
```
