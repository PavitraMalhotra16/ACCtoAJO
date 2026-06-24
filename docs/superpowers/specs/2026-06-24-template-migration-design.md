# Template Migration Design
_Date: 2026-06-24_

## Overview

Extends the ACC → AJO migration tool to handle **delivery templates** (email + SMS) from Adobe Campaign Classic. Templates are extracted upstream into a Postgres table (`acc_deliverytemplate_parsed`) by another developer and stored as raw JSON blobs. This feature reads from that table, converts ACC syntax to AJO syntax, resolves AJO folder IDs, writes an `enriched_json` handoff per template, and shows live aggregate progress in the UI.

Scope of this feature: **Steps 1–4** (load → convert → resolve folder → write enriched JSON). Steps 5+ (duplicate check, AJO POST, verify) are stub pipeline slots for the next developer.

---

## Input

### Source DB table: `acc_deliverytemplate_parsed`

Each row is one ACC delivery template. Key fields used:

| Field | Notes |
|---|---|
| `sourceId` | ACC numeric ID — used as dedup key and traceability |
| `internalName` | ACC internal name, e.g. `remktCartAbandonment` |
| `label` | Human-readable name used as AJO template `name` |
| `channel` | `'email'` or `'sms'` |
| `description` | Optional — passed through |
| `subject` | Email subject line (may contain ACC placeholders) |
| `htmlBody` | Full HTML (may contain `<%= %>`, `<%@ %>`, `%UNSUB%`, etc.) |
| `smsContent` | SMS body text |
| `lastModified` | Timestamp |

---

## User Journey — 4 Phases

### Phase 1: Setup (`TemplateMigrationPage`)

**User action:**
1. Reads instructions: "In AJO, create an Email folder and an SMS folder. Inside each, create one sample template named exactly `email sample` and `sms sample`."
2. Enters those two names in the form.
3. Clicks **Verify & Continue**.

**Backend (`POST /api/templates/setup`):**
- Uses the existing AJO destination connection (same `destination_connections` table as schema migration — no new auth needed).
- Calls `GET https://platform.adobe.io/ajo/content/templates` with AJO bearer token.
- Scans `items[]` for name matching `email sample` → extracts `parentFolderId` → upserts into `template_folder_config` with `channel = 'email'`.
- Same for `sms sample` → `channel = 'sms'`.
- Returns `{ email_folder_id, sms_folder_id }` on success or a clear error if a name wasn't found.

**On success:** UI navigates to Phase 2.

---

### Phase 2: Analysis + Placeholder Review (`TemplateAnalysisPage`)

**Backend (`GET /api/templates/analysis`):**
- Scans ALL `htmlBody` + `smsContent` fields in `acc_deliverytemplate_parsed`.
- Extracts every unique `recipient.*` expression via regex: `<%=\s*recipient\.(\w+)\s*%>`.
- Extracts every unique `targetData.*` expression via regex: `<%=\s*targetData\.(\w+)\s*%>`.
- Returns two deduplicated lists with default AJO mappings from `placeholder_config.py`.

**`placeholder_config.py` (backend/pipeline/):**
```python
RECIPIENT_MAPPINGS = {
    "recipient.firstName":  "profile.person.name.firstName",
    "recipient.lastName":   "profile.person.name.lastName",
    "recipient.email":      "profile.workEmail.address",
    "recipient.phone":      "profile.mobilePhone.number",
    # ... extend as needed
}
# targetData.* — no explicit config needed.
# Default generated programmatically: context.targetData.<fieldname>
```
- Any `recipient.*` field NOT in the config gets a best-guess default: `profile.<fieldname>`.
- Any `targetData.*` field always gets default: `context.targetData.<fieldname>`.

**UI (Analysis page) — two sections:**

_Section 1: recipient.* placeholders_

| ACC Placeholder | Default AJO Mapping | |
|---|---|---|
| `<%= recipient.firstName %>` | `{{profile.person.name.firstName}}` | ✏️ |
| `<%= recipient.customField %>` | `{{profile.customField}}` | ✏️ |

_Section 2: targetData.* placeholders_

| ACC Placeholder | Default AJO Mapping | |
|---|---|---|
| `<%= targetData.manageSubscriptionURL %>` | `{{context.targetData.manageSubscriptionURL}}` | ✏️ |
| `<%= targetData.orderId %>` | `{{context.targetData.orderId}}` | ✏️ |

- Clicking the pencil opens an inline text field; user types their preferred AJO path and saves.
- Everything else (`<%@ %>`, `<%if`, `<%for`, `formatDate()`, etc.) is NOT shown — handled automatically.

**User action:** Reviews mappings, edits if needed, clicks **Confirm & Start Migration**.

**Backend (`POST /api/templates/migrate`):**
- Saves approved mapping as `placeholder_map` JSON into `template_migration_runs`.
- Generates `run_id = str(uuid.uuid4())`.
- Creates one `template_job_items` row per template row in `acc_deliverytemplate_parsed` with `status = PENDING`.
- Kicks off background pipeline.
- Returns `run_id`.

**UI navigates to:** `/migration/template/run/<run_id>`

---

### Phase 3: Migration Run (`TemplateRunPage`)

**Polling:** `GET /api/templates/runs/<run_id>/status` every 2–3 seconds.

**Response shape:**
```json
{
  "status": "RUNNING",
  "email": { "total": 80, "completed": 47, "failed": 3 },
  "sms":   { "total": 40, "completed": 12, "failed": 0 }
}
```

**While running — aggregate progress bars only (no per-template step rows):**
```
Email templates    ████████████░░░░░░░░  47 / 80 done
SMS templates      ██████░░░░░░░░░░░░░░  12 / 40 done
Overall            ████████░░░░░░░░░░░░  59 / 120  (3 failed so far)
```

**When `status = COMPLETED` — switches to summary view:**
- Counts: email created / total, SMS created / total, failed count.
- Collapsible "Show failed templates" section:
  - Columns: `internalName | channel | failed at step | error message`

---

### Phase 4: Handoff to next developer

`template_job_items.enriched_json` is the output contract. Shape:

```json
{
  "sourceId": "6248",
  "internalName": "remktCartAbandonment",
  "channel": "email",
  "name": "[Example] Remarketing Cart Abandonment",
  "description": "",
  "subject": "Guess what? There's an item left in your cart.",
  "convertedHtml": "...AJO-syntax HTML...",
  "convertedSmsBody": null,
  "parentFolderId": "<uuid from template_folder_config>",
  "warnings": [],
  "source": { "origin": "ajo", "metadata": {} }
}
```

`warnings[]` contains entries for anything that could not be auto-converted (e.g. `NL.Require()`, `<%if`, `<%for`). Steps 5+ (duplicate check, POST, verify) are empty pipeline slots in `template_pipeline_steps.py`.

---

## Pipeline Steps

File: `backend/template_pipeline_steps.py`

| # | Step name | Phase | What it does |
|---|---|---|---|
| 1 | `LOAD_RAW` | 1 | Read one row from `acc_deliverytemplate_parsed`, validate required fields present |
| 2 | `CONVERT_PLACEHOLDERS` | 1 | Apply conversion rules to `htmlBody` / `smsContent` / `subject` |
| 3 | `RESOLVE_FOLDER` | 1 | Look up `parentFolderId` from `template_folder_config` by `channel` |
| 4 | `BUILD_ENRICHED` | 1 | Write `enriched_json` to `template_job_items` |
| 5 | `DUPLICATE_CHECK` | 1 | *(stub for next developer)* |
| 6 | `BUILD_PAYLOAD` | 1 | *(stub for next developer)* |
| 7 | `PUSH_TEMPLATE` | 2 | *(stub for next developer)* |
| 8 | `VERIFY` | 2 | *(stub for next developer)* |

All phases run concurrently across templates (templates are independent — unlike schemas there is no relationship-wiring pass).

---

## Placeholder Conversion Rules (Step 2)

| Pattern | Rule | Output |
|---|---|---|
| `<%= recipient.x %>` | Look up in approved `placeholder_map` (user-reviewed) | `{{profile.x}}` or user's mapping |
| `<%= targetData.x %>` | Look up in approved `placeholder_map` (user-reviewed, default: `context.targetData.x`) | `{{context.targetData.x}}` or user's mapping |
| `<%@ include ... %>` | Add to `warnings[]`, keep raw | raw (flagged) |
| `<%if`, `<%for` | Add to `warnings[]`, keep raw | raw (flagged) |
| `formatDate()`, `formatPrice()` | Add to `warnings[]` as `manual_migration` | raw (flagged) |
| `NL.Require()` | Add to `warnings[]` as `server_side_cannot_migrate` | raw (flagged) |
| `%UNSUB%` | Auto-replace | `{{unsubscribeLink}}` |
| `%MIRROR%` | Auto-replace | `{{mirrorPageLink}}` |

Templates with warnings still get `enriched_json` written — the next developer sees `warnings[]` and decides what to do with flagged sections.

---

## Image URL Handling (Step 2 — separate pass from placeholders)

Image references are extracted and validated separately — they are never run through placeholder bracket conversion.

**Extraction targets:**
- `<img src="...">` attributes
- CSS `background-image: url(...)` inline styles
- VML/background fill attributes (if present in email HTML)

**Decision rules:**

| URL type | Action |
|---|---|
| Absolute HTTPS, static, public | Keep as-is |
| Absolute HTTP (not HTTPS) | Add to `warnings[]` as `http_image` |
| Relative URL (e.g. `/res/img/banner.jpg`) | Add to `warnings[]` as `relative_url` |
| Contains ACC expression in URL (e.g. `src="...?id=<%= %>")` | Convert only the `<%= %>` part; keep base URL; add to `warnings[]` as `dynamic_url` |
| Base64 inline (`data:image/...`) | Add to `warnings[]` as `base64_image` |
| Signed/expiring URL (contains `token=`, `expires=`, `X-Amz-Expires=`) | Add to `warnings[]` as `signed_url` |

**No reachability check at this stage** (no outbound HTTP calls during pipeline). URL shape is validated only. Reachability validation is flagged as out of scope for this developer's steps.

---

## Database Tables

### `template_folder_config`
```
id                   integer  PK auto-increment
destination_conn_id  integer  FK → destination_connections.id
channel              text     'email' | 'sms'
folder_name          text     sample template name user typed (e.g. "email sample")
parent_folder_id     text     UUID returned from AJO GET /templates
created_at           timestamp default now()
```
Unique constraint: `(destination_conn_id, channel)` — one folder per channel per AJO connection.

### `template_migration_runs`
```
id                   integer  PK auto-increment
run_id               text     UUID generated by backend on migration start
destination_conn_id  integer  FK → destination_connections.id
status               text     'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
placeholder_map      jsonb    approved recipient.* → profile.* mappings
started_at           timestamp default now()
completed_at         timestamp nullable
```

### `template_job_items`
```
id                   integer  PK auto-increment
run_id               text     FK → template_migration_runs.run_id
source_id            text     ACC sourceId (e.g. "6248")
internal_name        text     e.g. "remktCartAbandonment"
channel              text     'email' | 'sms'
status               text     'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'SKIPPED'
current_step         text     step name, e.g. "BUILD_ENRICHED"
current_step_order   integer
enriched_json        jsonb    written at step 4; consumed by steps 5+ (next developer)
ajo_template_id      text     nullable — written by step 7 after AJO POST
error_step           text     nullable — which step failed
error_message        text     nullable — error detail
created_at           timestamp default now()
updated_at           timestamp default now()
```

### Dashboard queries (no extra tables needed)
```sql
-- Live progress counts
SELECT channel, status, COUNT(*)
FROM template_job_items
WHERE run_id = ?
GROUP BY channel, status;

-- Failed templates for error list
SELECT source_id, internal_name, channel, error_step, error_message
FROM template_job_items
WHERE run_id = ? AND status = 'FAILED';
```

---

## New Files

```
backend/
  template_pipeline_steps.py          step definitions (mirrors pipeline_steps.py)
  pipeline/
    template_runner.py                orchestration (mirrors runner.py)
    template_handlers.py              step 1–4 handlers + stubs for 5–8
    placeholder_config.py             RECIPIENT_MAPPINGS dict
  routes/
    templates.py                      /api/templates/setup, /analysis, /migrate, /runs/<id>/status

frontend_app/src/pages/
  TemplateMigrationPage.tsx           rebuilt: setup form + instructions (Phase 1)
  TemplateAnalysisPage.tsx            placeholder review table (Phase 2)
  TemplateRunPage.tsx                 progress bars + summary dashboard (Phase 3)
```

Routes registered in `backend/main.py` alongside existing routers.

---

## Out of Scope

- Duplicate check against AJO (step 5) — left as stub; depends on whether `source.metadata` round-trips in GET response (needs live API validation by next developer)
- AJO POST and VERIFY (steps 7–8) — next developer's handlers
- Image URL validation / rewriting — not in this feature
- Templates with channel other than `email` or `sms` — skipped with `status = SKIPPED`
