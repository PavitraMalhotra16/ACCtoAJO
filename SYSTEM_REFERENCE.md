# ACC → AJO Migration Tool — Complete System Reference

## Table of Contents
1. [Project Structure](#project-structure)
2. [How to Run](#how-to-run)
3. [Database Tables](#database-tables)
4. [Authentication](#authentication)
5. [Page-by-Page Flow](#page-by-page-flow)
   - [ConfigPage `/`](#configpage-)
   - [MigrationTypePage `/migration/type`](#migrationtypepage-migrationtype)
   - [MigrationSelectPage `/migration/select`](#migrationselectpage-migrationselect)
   - [MigrationRunPage `/migration/run`](#migrationrunpage-migrationrun)
   - [TemplateMigrationPage `/migration/template`](#templatemigrationpage-migrationtemplate)
6. [All API Endpoints](#all-api-endpoints)
7. [Authentication Deep Dive](#authentication-deep-dive)
   - [ACC Classic Auth](#acc-classic-auth-consoleuserpassword)
   - [ACC Technical Auth](#acc-technical-auth-ims-oauth)
   - [AJO Auth](#ajo-auth)
   - [Session Management](#session-management)
   - [_get_acc_conn](#_get_acc_conn)
8. [Schema Dependency Feature](#schema-dependency-feature)
   - [Concept](#concept)
   - [How the Dependency Graph is Built](#how-the-dependency-graph-is-built)
   - [API: GET /api/schemas/dependencies](#api-get-apischemasdependencies)
   - [API: GET /api/acc/schemas/{ns}/{name} — FK Link Info](#api-get-apiaccschemasnsname--fk-link-info)
   - [Frontend: MigrationSelectPage Dependency Behaviour](#frontend-migrationselectpage-dependency-behaviour)
   - [Full End-to-End Flow](#full-end-to-end-flow)
9. [Schema Extraction Flow](#schema-extraction-flow)
10. [Schema Migration Pipeline](#schema-migration-pipeline-14-steps)
11. [Template Extraction Flow](#template-extraction-flow)
12. [Configuration](#configuration)

---

## Project Structure

```
ACCtoAJO/
├── backend/
│   ├── main.py                        # FastAPI app, CORS, router registration, DB init
│   ├── db.py                          # SQLAlchemy ORM models + init_db()
│   ├── config.py                      # Settings (DATABASE_URL, ENCRYPTION_KEY, page sizes)
│   ├── config_placeholder.py          # ACC → AJO field mapping for template transform
│   ├── core/
│   │   └── security.py                # encrypt/decrypt, get_login_from_cookie, get_valid_acc_token
│   ├── routes/
│   │   ├── auth.py                    # /api/acc/connect, /api/ajo/connect, /api/acc/disconnect, status
│   │   ├── schemas.py                 # /api/acc/schemas, /api/acc/schemas/{ns}/{name}
│   │   ├── conversion.py              # /api/convert/start, /api/convert/status, /api/convert/extracted
│   │   ├── templates.py               # /api/templates/count, /api/templates/extract, etc.
│   │   └── migrate.py                 # /api/migrate/start, /api/migrate/status, etc.
│   ├── services/
│   │   ├── acc_soap.py                # SOAP envelope builders + response parsers
│   │   ├── schema_inspector.py        # parse_schema_to_xdm() — XML → JSON
│   │   ├── schema_preview.py          # parse_schema_preview() — for UI field preview
│   │   ├── template_extractor.py      # count_templates, fetch_template_list, fetch_delivery_detail
│   │   └── template_transformer.py    # ACC → AJO field token replacement
│   └── pipeline/
│       ├── runner.py                  # run_migration_job() orchestration
│       ├── handlers.py                # 14 step handler functions
│       └── pipeline_steps.py          # Step definitions + ordering
│
└── frontend_app/
    └── src/
        ├── App.tsx                    # React Router — route definitions + ProtectedRoute
        ├── store/
        │   └── configStore.ts         # Zustand store — accConnected, ajoConnected
        ├── api/
        │   ├── client.ts              # accConnect, ajoConnect, getSchemas, getAccStatus, getAjoStatus
        │   ├── migration.ts           # startConversion, startMigration, getMigrationStatus, etc.
        │   └── templates.ts           # extractTemplates, getTemplateCount, getStoredCount
        ├── components/
        │   ├── AccPanel.tsx           # ACC connection form (classic + technical)
        │   └── AjoPanel.tsx           # AJO connection form
        └── pages/
            ├── ConfigPage.tsx         # Home — connect ACC + AJO, resume active jobs
            ├── MigrationTypePage.tsx  # Choose: Schema or Template migration
            ├── MigrationSelectPage.tsx# Pick schemas, view field previews
            ├── MigrationRunPage.tsx   # Live extraction + push-to-AJO dashboard
            └── TemplateMigrationPage.tsx # Template extraction progress
```

---

## How to Run

```bash
# Backend (from backend/ folder)
uvicorn main:app --reload --port 8000

# Frontend (from frontend_app/ folder)
npm run dev   # starts on http://localhost:5173

# .env required in backend/:
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/acc_ajo
ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

**Never commit `.env`** — contains `ENCRYPTION_KEY` and `DATABASE_URL`.

---

## Database Tables

### `source_connections` — ACC connection
| Column | Type | Notes |
|---|---|---|
| `login_id` | String | Primary identity. Classic: username. Technical: client_id |
| `auth_type` | String | `classic` or `technical` |
| `instance_url` | String | ACC instance base URL |
| `encrypted_password` | Text | Fernet-encrypted password (classic only) — used for auto re-Logon |
| `session_token` | Text | SOAP session token — populated for both classic and technical |
| `security_token` | Text | SOAP security token — populated for both classic and technical |
| `session_expires_at` | DateTime | Classic only — `now + 23h` at login; reset on every auto re-Logon |
| `client_id` | String | OAuth client ID (technical only) |
| `encrypted_credentials` | Text | Fernet-encrypted `"client_id:client_secret"` (technical only) — used for IMS refresh |
| `encrypted_access_token` | Text | Fernet-encrypted IMS Bearer token (technical only) |
| `token_expires_at` | DateTime | IMS token expiry — `now + expires_in` from IMS (technical only) |
| `authenticated` | Boolean | True after successful connect |

### `destination_connections` — AJO connection
| Column | Type | Notes |
|---|---|---|
| `org_id` | String | Adobe Org ID e.g. `65cfe7fc@AdobeOrg` |
| `tenant_id` | String | Derived: `"_" + org_id.split("@")[0].lower()` |
| `client_id` | String | OAuth client ID |
| `sandbox_name` | String | AEP sandbox name |
| `encrypted_credentials` | Text | Fernet-encrypted `"client_id:client_secret"` |
| `encrypted_access_token` | Text | Fernet-encrypted IMS Bearer token |
| `token_expires_at` | DateTime | `now + expires_in` from IMS |
| `authenticated` | Boolean | True after successful connect |

### `user_sessions` — Browser sessions
| Column | Type | Notes |
|---|---|---|
| `id` | String (UUID) | Stored in `acc_session` cookie |
| `login_id` | String | Links to `source_connections.login_id` |
| `expires_at` | DateTime | Rolling 7-day TTL — extended on every valid request |

### `converted_schemas` — Extracted schema JSON
| Column | Type | Notes |
|---|---|---|
| `job_id` | String | Which extraction job created this |
| `login_id` | String | Owning user |
| `schema_name` | String | `namespace:name` e.g. `cus:recipient` |
| `raw_json` | Text | Parsed ACC schema — input to pipeline |
| `enriched_json` | Text | Built payload after step 5 — ready to push to AEP |

### `schema_job_items` — Per-schema migration state
| Column | Type | Notes |
|---|---|---|
| `job_id` | String | Migration job UUID |
| `schema_name` | String | `namespace:name` |
| `status` | String | `QUEUED` → `RUNNING` → `COMPLETED` / `FAILED` |
| `current_step` | String | Step name e.g. `CREATE_SCHEMA` |
| `current_step_order` | Integer | 1–14 |
| `current_snapshot` | Text | JSON dump of pipeline `data` dict — enables resume |
| `identity_is_primary` | Boolean | Set by RESOLVE_IDENTITY step |
| `error_message` | Text | Failure reason if FAILED |
| `fields_added` | Integer | Fields patched into existing AEP schema |
| `completed_at` | DateTime | Set when COMPLETED |

### `acc_deliverytemplate_raw` — Raw template XML from ACC
| Column | Type | Notes |
|---|---|---|
| `login_id` | String | Owning user |
| `source_id` | String | ACC delivery `@id` |
| `batch_id` | String (UUID) | UUID per extract call |
| `raw_xml` | Text | Full raw XML from ACC SOAP |

### `acc_deliverytemplate_parsed` — Parsed template JSON
| Column | Type | Notes |
|---|---|---|
| `login_id` | String | Owning user |
| `source_id` | String | ACC delivery `@id` |
| `batch_id` | String | Same UUID as raw table row |
| `template_data` | Text | JSON: `{ sourceId, internalName, label, channel, subject, htmlBody, textBody }` |

---

## Authentication

### ACC Classic Auth (username + password)
1. Browser `POST /api/acc/connect` with `auth_type: "classic"`, `login`, `password`, `instance_url`
2. Backend calls ACC SOAP `xtk:session#Logon` → gets `session_token` + `security_token`
3. Backend calls ACC SOAP `xtk:session#TestCnx` to validate tokens
4. Saves to `source_connections`: `session_token`, `security_token`, `encrypted_password`, `session_expires_at = now + 23h`
5. Creates `user_sessions` row (7-day rolling TTL)
6. Sets `acc_session` cookie (httponly, 7 days)

**Auto-refresh:** Every subsequent API call goes through `get_valid_acc_token()`. If `session_expires_at <= now + 60s`, it silently re-calls `xtk:session#Logon` using stored `encrypted_password`, updates `session_token`, `security_token`, and `session_expires_at` in DB — completely transparent to the route. User never needs to reconnect.

### ACC Technical Auth (IMS OAuth)
1. Browser `POST /api/acc/connect` with `auth_type: "technical"`, `client_id`, `client_secret`, `scope`, `instance_url`
2. Backend calls Adobe IMS `POST /ims/token/v3` → gets `access_token` + `expires_in` (value is in **seconds** — do not divide by 1000)
3. Saves to `source_connections`: `encrypted_access_token`, `encrypted_credentials`, `token_expires_at = now + expires_in` (no `session_token` or `security_token` — those are only used for classic auth)
4. Creates `user_sessions` row (7-day rolling TTL)
5. Sets `acc_session` cookie (httponly, 7 days)

> **Modern bearer flow:** This tool uses Adobe's recommended server-to-server technical-account pattern. All SOAP calls for technical auth send `Authorization: Bearer <access_token>` in the HTTP header with an empty `sessiontoken` in the SOAP envelope. The helper `acc_soap_headers(conn, token)` returns the correct headers per auth type — routes never branch on `auth_type`.

**Auto-refresh:** Every subsequent API call goes through `get_valid_acc_token()`. If `token_expires_at <= now + 60s`, it silently re-calls IMS `/ims/token/v3` using stored `encrypted_credentials`, updates `encrypted_access_token` and `token_expires_at` in DB — completely transparent to the route.

### AJO Auth
1. Browser `POST /api/ajo/connect` with `org_id`, `client_id`, `client_secret`, `sandbox_name`
2. Backend calls Adobe IMS `POST /ims/token/v3`
3. Saves to `destination_connections`: `encrypted_access_token`, `encrypted_credentials`, `token_expires_at`, `tenant_id`
4. No cookie set — AJO identity is purely DB-side

---

## Page-by-Page Flow

---

### ConfigPage `/`

**File:** `frontend_app/src/pages/ConfigPage.tsx`
**Store:** `useConfigStore` (Zustand) — tracks `accConnected`, `ajoConnected`

#### On page load (useEffect fires once):

```
1. GET /api/acc/status
   Response: { connected: bool, login: string | null }
   If connected → setAccConnected(login) → store: accConnected = true
   If not      → setAccDisconnected()    → store: accConnected = false

2. GET /api/ajo/status
   Response: { connected: bool, org_id: string | null, sandbox_name: string | null }
   If connected → setAjoConnected(org_id, sandbox_name)

3. GET /api/migrate/jobs
   Response: { jobs: [{ job_id, created_at }] }
   If jobs exist:
     GET /api/migrate/status/{job_id}
     Response: { running, queued, ... }
     If running > 0 OR queued > 0:
       navigate('/migration/run?migrate_job={job_id}')   ← auto-resume active job
```

#### User actions:

| Action | Component | API called | Response | Result |
|---|---|---|---|---|
| Fill ACC classic form + Connect | `AccPanel` | `POST /api/acc/connect` | `{ success, authenticated, login }` | `acc_session` cookie set, store updated |
| Fill ACC technical form + Connect | `AccPanel` | `POST /api/acc/connect` | `{ success, authenticated, login, expires_in }` | `acc_session` cookie set, store updated |
| Disconnect ACC | `AccPanel` | `POST /api/acc/disconnect` | `{ success }` | Cookie deleted, store cleared |
| Fill AJO form + Connect | `AjoPanel` | `POST /api/ajo/connect` | `{ success, authenticated, expires_in }` | DB updated, store updated |
| Click "Migrate →" | `ConfigPage` | — | — | `navigate('/migration/type')` |

**Migrate button** is disabled until both `accConnected` and `ajoConnected` are true.

**Redirect:** `/migration/type` on Migrate click, `/migration/run?migrate_job=...` if active job found.

---

### MigrationTypePage `/migration/type`

**File:** `frontend_app/src/pages/MigrationTypePage.tsx`
**Protected:** requires `accConnected && ajoConnected` (enforced by `ProtectedRoute` in `App.tsx`)

No API calls on load. Pure navigation.

| Action | Redirect |
|---|---|
| Click "Schema Migration" | `navigate('/migration/select')` |
| Click "Template Migration" | `navigate('/migration/template')` |
| Click "← Back" | `navigate('/')` |

---

### MigrationSelectPage `/migration/select`

**File:** `frontend_app/src/pages/MigrationSelectPage.tsx`

#### On page load — 5 parallel API calls:

```
1. GET /api/acc/schemas
   Response: { schemas: [{ namespace, name, label }] }
   → Populates the left sidebar schema list (all schemas shown)

2. GET /api/convert/extracted
   Response: { extracted: ["cus:recipient", "cus:company", ...] }
   → Shows "Ready to push" badge on already-extracted schemas

3. GET /api/migrate/incomplete
   Response: { schemas: [{ schema_name, status, current_step, current_step_order, error_message }] }
   → Shows "In progress" badge (locked) or "Failed: step X" badge
   → FAILED independent schemas are auto-selected (pre-checked) for immediate retry

4. GET /api/migrate/completed
   Response: { schemas: ["cus:recipient", ...] }
   → Shows "Pushed to AJO — re-migrate to sync" green badge

5. GET /api/schemas/dependencies
   Response: { dependents_of: { "hdbk:accountProfile": ["hdbk:membership"] },
               dependent_set: ["hdbk:membership"] }
   → Identifies which schemas are dependent (have FK links to other custom schemas)
   → Dependent schemas shown with lock icon, not selectable
   → Independent schemas shown with checkbox + "+N dependents" badge
```

#### Sidebar behaviour:

| Schema type | Visual | Selectable |
|---|---|---|
| Independent (no outgoing FK to custom schemas) | Blue text, checkbox, "+N dependents" badge | Yes |
| Dependent (has FK to another custom schema), parent not selected | Gray text, lock icon, orange "dependent" badge | No |
| Dependent, parent IS selected | Green text, lock icon, green "will migrate" badge | No |

Dependent schemas appear **directly below their parent** in the sidebar (reordered client-side).

#### Badge logic:
```
No badge           → fresh from ACC, never touched
"Ready to push"    → in converted_schemas DB, not yet migrated
"Pushed to AJO"    → status=COMPLETED in schema_job_items (re-selectable)
"In progress"      → status=RUNNING or QUEUED right now (checkbox hidden, locked)
"Failed: step X"   → status=FAILED — pre-selected automatically for retry
"+N dependents"    → independent schema with N dependent schemas linked to it
"dependent"        → this schema has a FK; cannot be selected alone
"will migrate"     → dependent schema whose parent is currently selected
```

#### User interactions:

| Action | API called | Response | Result |
|---|---|---|---|
| Click independent schema (select) | `GET /api/acc/schemas/{ns}/{name}` | `{ namespace, name, attributes, keys, links }` | Right panel shows field preview; dependents turn green in sidebar; dependent schema details auto-fetched |
| Click independent schema (deselect) | — | — | Removed from selection; dependents revert to gray |
| Click dependent schema | — | — | No effect (locked) |
| Click "Select all visible" | `GET /api/acc/schemas/{ns}/{name}` (per independent schema) | Field details | All selectable schemas selected; all their dependents turn green |
| Filter by namespace dropdown | — | — | Sidebar filtered client-side; dependent schemas stay grouped under parent |
| Type in search box | — | — | Sidebar filtered client-side |
| Click "Migrate →" | See below | — | — |

#### Right panel — schema field preview:

When an independent schema is selected:
- Its field table is shown with **PK fields highlighted purple** (dot + purple row)
- Its **FK fields highlighted orange** (dot + orange row, label column shows `→ targetSchema`)
- A summary line above the table shows: `Primary Key: membershipId | FK: accountProfileId → hdbk:accountProfile`
- **Below the independent schema card**, an indented section shows each dependent schema's full field preview (orange border, also with FK highlighting)

This means selecting `hdbk:accountProfile` shows:
```
[hdbk:accountProfile card — expanded with fields]
  ↓ 2 dependent schemas — will migrate automatically
  [hdbk:membership card — orange border, FK field highlighted]
  [hdbk:order card — orange border, FK field highlighted]
```

#### Clicking "Migrate →" → `handleNext()`:

```
expandWithDependents(selected):
  → Takes the user-selected independent schema keys
  → Adds all their dependents automatically
  → Returns full list of SchemaEntry objects to submit

POST /api/convert/start
Body: {
  "schemas": [
    { "namespace": "hdbk", "name": "accountProfile", "label": "Account Profiles" },
    { "namespace": "hdbk", "name": "membership",     "label": "Memberships" },
    { "namespace": "hdbk", "name": "order",          "label": "Orders" }
  ]
}
Response: { "job_id": "abc123", "message": "started", "skipped": [] }

→ navigate('/migration/run?extract_job=abc123')
```

The user only selected `accountProfile` — `membership` and `order` are automatically included because they are dependents. The header badge shows "3 schemas will migrate" even though only 1 was clicked.

**Important:** This always re-extracts from ACC (replaces existing `converted_schemas` rows). This ensures the latest ACC definition is used before the AJO push.

**Redirect:** `/migration/run?extract_job={job_id}`

---

### MigrationRunPage `/migration/run`

**File:** `frontend_app/src/pages/MigrationRunPage.tsx`

URL can contain:
- `?extract_job={id}` — came from MigrationSelectPage, extraction just started
- `?migrate_job={id}` — resuming an in-progress migration from ConfigPage
- `?phase=migrate` — schemas already extracted, skip straight to migration

#### Phase: `extracting`

Entered when URL has `extract_job`. Polls every 2 seconds:

```
GET /api/convert/status/{extract_job_id}
Response: {
  "id": "abc123",
  "status": "running" | "completed",
  "schema_count": 2,
  "success_count": 1,
  "failed_count": 0,
  "current_schema": "cus:company",
  "steps": [
    { "schemaName": "cus:recipient", "status": "success", "error": null },
    { "schemaName": "cus:company",   "status": "running", "error": null }
  ]
}
```

UI shows: progress bar, per-schema spinner → tick/cross.

**When `status === "completed"` → automatically fires:**

```
POST /api/migrate/start
Body: { "extract_job_id": "abc123" }
Response: { "job_id": "mig456", "total": 2, "queued": 2, "skipped": 0, "message": "started" }
```

Special case — `message === "all_done"`:
- All schemas already up to date in AEP
- Jumps to `phase = 'done'` immediately, no migration runs

Otherwise → `phase = 'migrating'`

#### Phase: `migrating`

Polls every 2 seconds:

```
GET /api/migrate/status/{migrate_job_id}
Response: {
  "job_id": "mig456",
  "total": 2,
  "completed": 1,
  "running": 1,
  "queued": 0,
  "failed": 0,
  "schemas": [
    {
      "schema_name": "cus:recipient",
      "status": "COMPLETED",
      "current_step": "VERIFY",
      "current_step_order": 14,
      "fields_added": 0,
      "completed_at": "2026-06-24T10:32:01Z"
    },
    {
      "schema_name": "cus:company",
      "status": "RUNNING",
      "current_step": "CREATE_SCHEMA",
      "current_step_order": 8
    }
  ]
}
```

Also polls `GET /api/migrate/incomplete` in parallel — catches schemas stuck from previous jobs.

**UI cards rendered per schema:**

| Status | Card type | Shows |
|---|---|---|
| `RUNNING` | `InProgressCard` | Step X of 14, step name, 14-segment progress bar (blue = current, green = done) |
| `COMPLETED` | `CompletedCard` | Green tick, "Pushed to AJO" / "Already in AJO" / "Updated — N fields added", duration |
| `FAILED` | `FailedCard` | Red X, step where it failed, error message, red segment in progress bar |
| `QUEUED` | `QueuedCard` | Grey, "Queued" badge |

**When `running === 0 && queued === 0` → `phase = 'done'`**

#### Phase: `done`

Shows banner: "Migration complete — all N schemas pushed to AJO" (green) or "N failed" (yellow).
"Back to home" → `navigate('/')`.

#### Resume path (from ConfigPage)

If URL has `?migrate_job={id}` (no extraction needed):
- Skips extracting phase entirely
- Goes straight to migrating phase, polls the existing job

---

### TemplateMigrationPage `/migration/template`

**File:** `frontend_app/src/pages/TemplateMigrationPage.tsx`

#### On page load — Phase: `counting`

```
GET /api/templates/count
Response: { "total": 31, "stored": 0, "to_migrate": 31 }
```

If `to_migrate === 0` → phase = `nothing` (all templates already extracted, nothing to do).
Otherwise → phase = `extracting`.

#### Phase: `extracting`

Two things run in parallel:

**A — Polling every 2 seconds:**
```
GET /api/templates/stored-count
Response: { "stored": 15 }
→ Updates the live counter shown in UI
```

**B — Extraction loop (runs until done):**
```
Loop:
  POST /api/templates/extract
  Response: {
    "extracted": 100,
    "total_found": 100,
    "skipped": 0,
    "batch_id": "uuid-abc",
    "errors": []
  }
  totalExtracted += extracted

  If total_found === 0: break   ← no more templates in ACC
  If extracted < total_found: break  ← partial page, means we've reached the end
```

Each POST call:
- Uses `COUNT(acc_deliverytemplate_raw)` as the SOAP `startLine` cursor (tracks fetched templates, not parsed)
- Fetches the next batch of `template_page_size` (default 100) templates from ACC
- Per template: skip SOAP if already in raw; skip parsing if already in parsed
- Returns how many were newly processed in this batch

**Single click extracts everything** — user never needs to click again.

#### Phase: `done`

Shows: "Extracted {totalExtracted} templates successfully."
"Back to home" → `navigate('/')`.

---

## All API Endpoints

### Authentication

| Method | Endpoint | Body | Response | Cookie set |
|---|---|---|---|---|
| `POST` | `/api/acc/connect` | `{ auth_type, instance_url, login?, password?, client_id?, client_secret?, scope? }` | `{ success, authenticated, login, expires_in? }` | `acc_session` (7d) |
| `POST` | `/api/acc/disconnect` | — | `{ success }` | Deletes `acc_session` |
| `GET` | `/api/acc/status` | — | `{ connected, login }` | — |
| `POST` | `/api/ajo/connect` | `{ org_id, client_id, client_secret, sandbox_name }` | `{ success, authenticated, expires_in }` | — |
| `GET` | `/api/ajo/status` | — | `{ connected, org_id, sandbox_name }` | — |
| `GET` | `/api/connections/status` | — | `{ sourceAuthenticated, destinationAuthenticated, sourceLoginId, destinationOrgId }` | — |

### Schemas

| Method | Endpoint | Body | Response |
|---|---|---|---|
| `GET` | `/api/acc/schemas` | — | `{ schemas: [{ namespace, name, label }] }` |
| `GET` | `/api/acc/schemas/{namespace}/{name}` | — | `{ namespace, name, label, attributes: [{ name, type, label }], keys: { autoPk, primaryKeys, uniqueKeys }, links: [{ name, targetSchema, sourceField }] }` |
| `GET` | `/api/schemas/dependencies` | — | `{ dependents_of: { "hdbk:accountProfile": ["hdbk:membership"] }, dependent_set: ["hdbk:membership"] }` |

### Schema Extraction (Conversion)

| Method | Endpoint | Body | Response |
|---|---|---|---|
| `POST` | `/api/convert/start` | `{ schemas: [{ namespace, name, label }] }` | `{ job_id, message, skipped }` |
| `POST` | `/api/convert/start-all` | — | `{ job_id, message, total, skipped }` |
| `GET` | `/api/convert/status/{job_id}` | — | `{ id, status, schema_count, success_count, failed_count, current_schema, steps }` |
| `GET` | `/api/convert/extracted` | — | `{ extracted: ["cus:recipient", ...] }` |

### Schema Migration

| Method | Endpoint | Body | Response |
|---|---|---|---|
| `POST` | `/api/migrate/start` | `{ extract_job_id? }` | `{ job_id, total, queued, skipped, message }` |
| `GET` | `/api/migrate/status/{job_id}` | — | `{ job_id, total, completed, running, queued, failed, schemas: [...] }` |
| `GET` | `/api/migrate/jobs` | — | `{ jobs: [{ job_id, created_at }] }` |
| `GET` | `/api/migrate/completed` | — | `{ schemas: ["cus:recipient", ...] }` |
| `GET` | `/api/migrate/incomplete` | — | `{ schemas: [{ schema_name, status, current_step, current_step_order, error_message }] }` |

### Templates

| Method | Endpoint | Body | Response |
|---|---|---|---|
| `GET` | `/api/templates/count` | — | `{ total, stored, to_migrate }` |
| `GET` | `/api/templates/stored-count` | — | `{ stored }` |
| `POST` | `/api/templates/extract` | — | `{ extracted, total_found, skipped, batch_id, errors }` |

**All endpoints require** `Cookie: acc_session={uuid}` (set automatically by browser).

---

## Authentication Deep Dive

### ACC Classic Auth (Console/User+Password)

```
POST /api/acc/connect
Body: { auth_type: "classic", instance_url, login, password }

  STEP 1 → ACC SOAP Logon
    POST {instance_url}/nl/jsp/soaprouter.jsp
    SOAPAction: xtk:session#Logon
    Body: XML with login + password
    Response: session_token + security_token

  STEP 2 → ACC SOAP TestCnx (validate)
    POST {instance_url}/nl/jsp/soaprouter.jsp
    SOAPAction: xtk:session#TestCnx
    Headers: Cookie: __sessiontoken={session_token}
             X-Security-Token: {security_token}

  STEP 3 → Save to source_connections
    login_id           = login (e.g. "pavitram@adobe.com")
    session_token      = raw SOAP token
    security_token     = raw SOAP security token
    encrypted_password = Fernet(password)
    session_expires_at = now + 23h        ← tracks when SOAP session will expire
    auth_type          = "classic"

  STEP 4 → Create user_sessions row + set acc_session cookie (7-day rolling)
```

**Auto-refresh** — `get_valid_acc_token()` called before every SOAP call:
```
If session_expires_at > now + 60s:
    return conn.session_token   ← SOAP session still valid, use it

Else:
    password = decrypt(encrypted_password)
    POST ACC /soaprouter.jsp  xtk:session#Logon  (login_id + password)
    → new session_token + security_token
    UPDATE source_connections SET session_token, security_token, session_expires_at = now + 23h
    return new session_token
```

User never needs to manually reconnect. The 23h window means refresh happens 1 hour before the ACC session actually expires (ACC default session lifetime is 24h).

### ACC Technical Auth (IMS OAuth)

```
POST /api/acc/connect
Body: { auth_type: "technical", instance_url, client_id, client_secret, scope }

  STEP 1 → Adobe IMS
    POST https://ims-na1.adobelogin.com/ims/token/v3
    Body: grant_type=client_credentials, client_id, client_secret, scope
    Response: { access_token, token_type: "bearer", expires_in }

    NOTE: expires_in is in SECONDS (e.g. 86399). Do NOT divide by 1000.
    The ms-division confusion applies to older IMS endpoints, not /ims/token/v3.

  STEP 2 → Save to source_connections  (modern direct bearer — no BearerTokenLogon)
    login_id               = client_id
    auth_type              = "technical"
    client_id              = client_id
    encrypted_credentials  = Fernet("client_id:client_secret")
    encrypted_access_token = Fernet(access_token)
    token_expires_at       = now + expires_in   ← expires_in already in seconds

    NOTE: session_token and security_token are NOT stored for technical auth.
    Every SOAP call passes Authorization: Bearer <access_token> in the HTTP
    header and an empty sessiontoken in the SOAP envelope (via acc_soap_headers).

  STEP 3 → Create user_sessions row + set acc_session cookie (7-day rolling)
```

**Auto-refresh** — `get_valid_acc_token()` called before every SOAP call:
```
If token_expires_at > now + 60s:
    return decrypt(encrypted_access_token)   ← IMS token still valid

Else:
    client_id, client_secret = decrypt(encrypted_credentials).split(":")
    POST IMS /ims/token/v3 → new access_token + expires_in
    UPDATE source_connections SET encrypted_access_token, token_expires_at
    return new access_token
```

Routes then call `acc_soap_headers(conn, token)` which returns:
- Technical: `{ "Authorization": "Bearer <token>" }`
- Classic:   `{ "Cookie": "__sessiontoken=<token>", "X-Security-Token": "<security_token>" }`

No auth-type branching needed in routes or SOAP envelope builders.

### AJO Auth

```
POST /api/ajo/connect
Body: { org_id, client_id, client_secret, sandbox_name }

  STEP 1 → Adobe IMS (identical to technical ACC)
    POST https://ims-na1.adobelogin.com/ims/token/v3
    Response: { access_token, expires_in }

  STEP 2 → Derive tenant_id
    "65cfe7fc52dc1234@AdobeOrg" → "_65cfe7fc52dc1234"

  STEP 3 → Save to destination_connections
    org_id                 = org_id
    tenant_id              = "_65cfe7fc52dc1234"
    client_id              = client_id
    sandbox_name           = sandbox_name
    encrypted_credentials  = Fernet("client_id:client_secret")
    encrypted_access_token = Fernet(access_token)
    token_expires_at       = now + expires_in

  No cookie set — AJO uses no browser session
```

### Session Management

```
acc_session cookie (httponly, 7-day rolling):
  → points to user_sessions.id (UUID)
  → user_sessions.login_id → source_connections.login_id
  → On every valid request: expires_at pushed forward by 7 days
  → If expired or missing → 401, user must reconnect
  → No acc_user fallback (removed — was a security gap)

acc_user cookie: no longer set or used
```

### _get_acc_conn()

Used by every schema-related route. Located in `routes/schemas.py`.

```python
async def _get_acc_conn(acc_session, acc_user, db):
    # Step 1: resolve session cookie → login_id
    login_id = await get_login_from_cookie(acc_session, db, acc_user)
    if not login_id:
        raise HTTPException(401, "Not authenticated")

    # Step 2: fetch source_connections row
    conn = await db.execute(select(SourceConnection).where(...login_id...))
    if not conn or not conn.authenticated:
        raise HTTPException(401, "ACC session not found")

    # Step 3: get valid token (auto-refreshes if expired for technical)
    token = await get_valid_acc_token(conn, db)

    return conn, token
```

Returns `(conn, token)`:
- `conn` → has `instance_url`, `security_token`, `auth_type`
- `token` → valid SOAP session token, same shape for both auth types

Classic: `token = conn.session_token` (re-Logon'd if `session_expires_at` passed)
Technical: `token = decrypt(conn.encrypted_access_token)` (IMS-refreshed if `token_expires_at` passed)

Routes then call `acc_soap_headers(conn, token)` to get the correct HTTP headers:
- Technical returns `Authorization: Bearer <token>` + empty SOAP sessiontoken
- Classic returns `Cookie: __sessiontoken=<token>` + `X-Security-Token`

No auth-type branching needed in SOAP envelope builders.

---

## Schema Dependency Feature

### Concept

ACC schemas can reference each other through **link elements** — XML elements with `type="link"` that define a foreign-key relationship. For example:

```xml
<!-- hdbk:membership has a FK to hdbk:accountProfile -->
<element name="accountProfile" type="link" target="hdbk:accountProfile">
  <join xpath-src="@accountProfileId" xpath-dst="@id"/>
</element>
```

This means:
- `hdbk:accountProfile` is **INDEPENDENT** — it has no FK pointing to other custom schemas. The user selects this from the sidebar.
- `hdbk:membership` is **DEPENDENT** — it has a FK (`accountProfileId`) pointing to `accountProfile`. It cannot be selected alone; it migrates automatically when `accountProfile` is selected.

**Why this matters for migration:** If you migrate `membership` without `accountProfile`, the FK relationship breaks. The tool enforces correctness by grouping them automatically.

---

### How the Dependency Graph is Built

**File called:** `backend/routes/schemas.py` → `get_dependency_graph()`

**Called from:** `frontend_app/src/api/client.ts` → `getSchemaDependencies()` → called on page load in `MigrationSelectPage.tsx`

**Always uses live ACC SOAP** — the DB was considered but rejected because users only extract a subset of schemas. A DB-only approach would miss dependencies for schemas that were never extracted, silently showing dependent schemas as selectable.

```
STEP 1 — Authenticate
  get_login_from_cookie(acc_session, db, acc_user) → login_id
  SELECT source_connections WHERE login_id = ?
  get_valid_acc_token(conn, db) → valid SOAP session token

STEP 2 — Fetch list of all custom schemas
  POST {instance_url}/nl/jsp/soaprouter.jsp
  SOAPAction: xtk:queryDef#ExecuteQuery
  Envelope: build_list_schemas_envelope(token, security_token)

  Filter out system namespaces: xtk, nms, nl, ncm, crm, bur, sfa, ext,
  offer, mkt, wpa, sup, temp, ghost, nav, acs, fda
  → Only custom schemas (e.g. hdbk:*, cus:*) remain

STEP 3 — Fetch srcSchema XML for every custom schema (CONCURRENT)
  asyncio.gather(*[_fetch_links(client, soap_url, token, ns, name) for each schema])

  For each schema, _fetch_links() does:
    POST {instance_url}/nl/jsp/soaprouter.jsp
    Envelope: build_srcschema_get_envelope(token, security_token, namespace, name)
    parse_schema_preview(xml, namespace, name) → (schema_key, links[])

  All N schemas fetched in parallel — one HTTP connection pool, N concurrent requests

STEP 4 — Build dependency graph
  For each (schema_key, links) from results:
    For each link where targetSchema is a custom namespace (not xtk/nms/etc.):
      dependents_of[targetSchema].append(schema_key)
      dependent_set.add(schema_key)

STEP 5 — Return
  {
    "dependents_of": { "hdbk:accountProfile": ["hdbk:membership"], "hdbk:campaign": ["hdbk:response"] },
    "dependent_set": ["hdbk:membership", "hdbk:response"]
  }
```

**Not stored in the database.** Computed fresh on every page load from live ACC SOAP — guarantees all schema relationships are detected regardless of which schemas have been previously extracted.

---

### API: GET /api/schemas/dependencies

**File:** `backend/routes/schemas.py`

**Auth required:** `acc_session` cookie → `_get_acc_conn()`

**ACC SOAP calls made:**
1. `build_list_schemas_envelope` → `xtk:queryDef#ExecuteQuery` — get schema list
2. `build_srcschema_get_envelope` × N — get each schema's XML (concurrent)

**Response:**
```json
{
  "dependents_of": {
    "hdbk:accountProfile": ["hdbk:membership", "hdbk:order"]
  },
  "dependent_set": ["hdbk:membership", "hdbk:order"]
}
```

| Field | Type | Meaning |
|---|---|---|
| `dependents_of` | `Record<string, string[]>` | For each independent schema, list of schemas that FK-link to it |
| `dependent_set` | `string[]` | All schema keys that have at least one outgoing FK to another custom schema |

**Not stored in the database.** Computed fresh on every request from live ACC SOAP — always reflects all schemas regardless of extraction history.

---

### API: GET /api/acc/schemas/{ns}/{name} — FK Link Info

**File:** `backend/routes/schemas.py` → calls `backend/services/schema_preview.py`

`parse_schema_preview()` was updated to also parse link elements from the srcSchema XML.

**What it parses:**
```xml
<element name="accountProfile" type="link" target="hdbk:accountProfile">
  <join xpath-src="@accountProfileId" xpath-dst="@id"/>
</element>
```

**Output added to response:**
```json
{
  "links": [
    {
      "name": "accountProfile",
      "targetSchema": "hdbk:accountProfile",
      "sourceField": "accountProfileId"
    }
  ]
}
```

| Field | Source | Meaning |
|---|---|---|
| `name` | `<element name="">` | Name of the link element |
| `targetSchema` | `<element target="">` | The schema this FK points to |
| `sourceField` | `<join xpath-src="@...">` with `@` stripped | The local field that holds the FK value |

This information is used by the frontend to highlight FK fields in the field preview table.

**Not stored in the database.** Parsed from live SOAP response each time the schema detail is requested.

---

### Frontend: MigrationSelectPage Dependency Behaviour

**File:** `frontend_app/src/pages/MigrationSelectPage.tsx`

**State managed:**
```typescript
dependentsOf: Record<string, string[]>   // { "hdbk:accountProfile": ["hdbk:membership"] }
dependentSet: Set<string>                // { "hdbk:membership", "hdbk:order" }
belongsTo:    Record<string, string[]>   // { "hdbk:membership": ["hdbk:accountProfile"] }
                                         // computed from dependentsOf (reverse map)
```

**Sidebar rendering logic:**
```
For each schema in filtered list:
  isDependent = dependentSet.has(schemaKey)

  If isDependent:
    isActivated = belongsTo[schemaKey].some(parent => selected.has(parent))
    If isActivated  → green background, green lock icon, "will migrate" badge
    If not          → gray background, gray lock icon, "dependent" badge
    No checkbox — not clickable

  If independent:
    Normal checkbox, blue text
    If dependentsOf[key].length > 0 → "+N dependents" blue badge
```

**Sidebar ordering:**
```
For each schema in the base filtered list:
  If it's an independent schema → add to ordered list
    Then immediately add all its dependents that are in the filtered list
  If it's a dependent already inserted → skip (already placed under its parent)

Result: dependents always appear directly below their parent in sidebar
```

**When an independent schema is selected (`toggle()`):**
```
1. Add schema key to selected set
2. Expand its card in the right panel
3. fetchDetail(schemaKey, entry) → GET /api/acc/schemas/{ns}/{name}
   → Returns attributes + keys + links (FK info)
4. fetchDependentsOf(schemaKey):
   For each depKey in dependentsOf[schemaKey]:
     fetchDetail(depKey, depEntry) → prefetch dependent schema details
5. setDepExpanded: auto-expand all dependent cards in right panel
```

**When an independent schema is deselected:**
```
1. Remove schema key from selected set
2. Collapse its card
3. Dependent schemas remain in sidebar but revert to gray (isActivated becomes false)
```

**Right panel rendering:**
```
For each selected independent schema S:
  Show SchemaDetailCard for S (blue border, expanded)
    → Field table with:
       PK fields: purple dot + purple row highlight
       FK fields: orange dot + orange row highlight + label shows "→ targetSchema"
       Summary line: "Primary Key: membershipId | FK: accountProfileId → hdbk:accountProfile"

  If dependentsOf[S].length > 0:
    Show section: "↓ N dependent schemas — will migrate automatically"
    For each dependent D:
      Show SchemaDetailCard for D (orange border, auto-expanded)
        → Same PK + FK highlighting in D's field table
```

**`expandWithDependents()` — used when Migrate is clicked:**
```typescript
function expandWithDependents(keys: Set<string>): SchemaEntry[] {
  const allKeys = new Set(keys)
  for (const k of keys) {
    for (const dep of (dependentsOf[k] ?? [])) allKeys.add(dep)
  }
  return schemas.filter(s => allKeys.has(key(s)))
}
```
Converts user's selection (only independent schemas) into the full list including their dependents, which is then sent to `POST /api/convert/start`.

---

### Full End-to-End Flow

```
USER opens /migration/select
  │
  ├─ GET /api/acc/schemas            → schema list for sidebar
  ├─ GET /api/convert/extracted      → "Ready to push" badges
  ├─ GET /api/migrate/incomplete     → "Failed" / "In progress" badges
  ├─ GET /api/migrate/completed      → "Pushed to AJO" badges
  └─ GET /api/schemas/dependencies   → dependency graph
       │
       └─ Backend: _get_acc_conn() → SOAP token
            │
            ├─ SOAP: build_list_schemas_envelope → all custom schema names
            └─ SOAP × N (concurrent): build_srcschema_get_envelope → each schema XML
                 │
                 └─ parse_schema_preview() → extract <element type="link"> elements
                      │
                      └─ Return { dependents_of, dependent_set }

FRONTEND receives dependency graph:
  dependentSet = { "hdbk:membership", "hdbk:order" }
  dependentsOf = { "hdbk:accountProfile": ["hdbk:membership", "hdbk:order"] }

SIDEBAR renders:
  hdbk:accountProfile  ☑ [+2 dependents]
  hdbk:membership      🔒 [dependent of accountProfile]   ← ordered below parent
  hdbk:order           🔒 [dependent of accountProfile]   ← ordered below parent

USER clicks hdbk:accountProfile checkbox:
  selected = { "hdbk:accountProfile" }
  → GET /api/acc/schemas/hdbk/accountProfile
    Response: { attributes: [...], keys: {...}, links: [] }  ← no FK links
  → GET /api/acc/schemas/hdbk/membership
    Response: { attributes: [...], keys: {...}, links: [{ name: "accountProfile",
                targetSchema: "hdbk:accountProfile", sourceField: "accountProfileId" }] }
  → GET /api/acc/schemas/hdbk/order
    Response: { attributes: [...], keys: {...}, links: [{ name: "accountProfile",
                targetSchema: "hdbk:accountProfile", sourceField: "accountProfileId" }] }

SIDEBAR updates:
  hdbk:accountProfile  ☑ [+2 dependents]          ← blue, selected
  hdbk:membership      🔒 [will migrate]            ← green (parent selected)
  hdbk:order           🔒 [will migrate]            ← green (parent selected)

RIGHT PANEL shows:
  [hdbk:accountProfile — 8 fields]
    Primary Key: id
    ┌─────────────────────────────────────────────┐
    │ Field       Type     Label                   │
    │ ● id        long     ID                      │  ← purple (PK)
    │   firstName string   First Name              │
    │   ...                                        │
    └─────────────────────────────────────────────┘

  ↓ 2 dependent schemas — will migrate automatically
  [hdbk:membership — 15 fields]  (orange border)
    Primary Key: membershipId | FK: accountProfileId → hdbk:accountProfile
    ┌─────────────────────────────────────────────────────────────────┐
    │ Field             Type     Label                                 │
    │ ● membershipId    string   Membership ID                        │  ← purple (PK)
    │ ● accountProfileId long   → hdbk:accountProfile                │  ← orange (FK)
    │   programCode     string   Program Code                         │
    │   ...                                                           │
    └─────────────────────────────────────────────────────────────────┘

  [hdbk:order — 8 fields]  (orange border)
    FK: accountProfileId → hdbk:accountProfile
    ┌──────────────────────────────────────────┐
    │ Field             Type     Label          │
    │ ● accountProfileId long → hdbk:account…  │  ← orange (FK)
    │   ...                                    │
    └──────────────────────────────────────────┘

HEADER badge: "3 schemas will migrate"

USER clicks Migrate →:
  expandWithDependents({ "hdbk:accountProfile" })
  → ["hdbk:accountProfile", "hdbk:membership", "hdbk:order"]

  POST /api/convert/start
  Body: { schemas: [accountProfile, membership, order] }
  → navigate('/migration/run?extract_job=abc123')
```

---

## Schema Extraction Flow

Triggered by `POST /api/convert/start`.

```
For each selected schema:

  1. Build SOAP envelope
     build_srcschema_get_envelope(token, security_token, namespace, name)

  2. Call ACC SOAP
     POST {instance_url}/nl/jsp/soaprouter.jsp
     SOAPAction: xtk:queryDef#ExecuteQuery
     → Returns full schema XML (fields, keys, links, enums)

  3. Parse XML → JSON
     parse_schema_to_xdm(xml)
     → { source, schema, rootElement, attributes, keys, linksAndJoins }

  4. Store in DB
     DELETE FROM converted_schemas WHERE login_id=? AND schema_name=?
     INSERT INTO converted_schemas (job_id, login_id, schema_name, raw_json)
     → Always replaces — fresh extract picks up latest ACC changes
```

Runs in background. Poll `GET /api/convert/status/{job_id}` to track progress.

---

## Schema Migration Pipeline (14 Steps)

Triggered automatically when extraction completes. Runs in background via `run_migration_job()`.

```
PHASE 1 — Enrichment (steps 1–5, concurrent per schema)

  Step 1  LOAD_JSON           Read raw_json from converted_schemas DB
  Step 2  MAP_TYPES           ACC types → XDM types (string/integer/number/boolean/date/datetime)
  Step 3  RESOLVE_IDENTITY    Find identity field + namespace (email→Email, ecid→ECID, etc.)
  Step 4  FETCH_TENANT_ID     Read tenant_id from destination_connections
  Step 5  BUILD_PAYLOAD       Build complete AEP JSON, write enriched_json to DB

PHASE 2 — AEP Push (steps 6–12, concurrent per schema)

  Step 6  NORMALIZE_INPUT     Re-read enriched_json from DB (durable, survives restart)
  Step 7  DUPLICATE_CHECK     GET /tenant/schemas — does it already exist?
  Step 8  CREATE_SCHEMA       POST /tenant/schemas (new) or PATCH (add missing fields)
  Step 9  PRIMARY_KEY_DESCRIPTOR   POST /tenant/descriptors (xdm:descriptorPrimaryKey)
  Step 10 VERSION_DESCRIPTOR       POST /tenant/descriptors (xdm:descriptorVersion)
  Step 11 TIMESTAMP_DESCRIPTOR     POST /tenant/descriptors (time-series only)
  Step 12 IDENTITY_DESCRIPTOR      GET+POST /idnamespace, POST /tenant/descriptors

PHASE 3 — Cross-schema (steps 13–14, sequential)

  Step 13 RELATIONSHIP_DESCRIPTORS  POST relationship descriptors between schemas
  Step 14 VERIFY                    GET schemas + descriptors to confirm landing in AEP
```

**Concurrency:** `_GLOBAL_SEM(10)` across all jobs + `job_sem(3)` per job.

**Resume/retry:** After every step, `current_snapshot` (full `data` dict JSON) is saved to `schema_job_items`. On retry, pipeline resumes from one step before where it failed — no restart from step 1.

**Final status values:**
- `COMPLETED` — newly pushed, all steps passed
- `ALREADY_EXISTS` — found in AEP in step 7, no changes needed
- `UPDATED` — found in AEP, new fields were patched in (`fields_added > 0`)
- `FAILED` — error at some step, `error_message` tells which step and why

---

## Template Extraction Flow

Triggered by `POST /api/templates/extract`.

```
1. Cursor: COUNT(acc_deliverytemplate_raw WHERE login_id=?) → start_line
   (uses raw count — tracks how many templates have been fetched from ACC,
    regardless of whether parsing succeeded)

2. Pre-load skip sets — one query each before the loop:
   already_in_raw    = SELECT source_id FROM acc_deliverytemplate_raw    WHERE login_id=?
   already_in_parsed = SELECT source_id FROM acc_deliverytemplate_parsed WHERE login_id=?
   → Both loaded into Python sets for O(1) per-template lookup (no per-template DB query)

3. Call ACC SOAP — fetch page of templates
   build_list_templates_envelope(token, security_token, page_size=100, start_line)
   SOAPAction: xtk:queryDef#ExecuteQuery on nms:delivery

   Filters applied:
     @isModel = 1              (delivery templates only)
     @builtIn != 1             (exclude system built-ins)
     @internalName != 'notifyWkfToStop'   (exclude specific system template)
     @messageType = 0 OR 1    (email + SMS only)

4. For each template in the page:

   STEP A — Raw extraction (skip if already fetched):
     If source_id NOT in already_in_raw:
       Fetch full delivery detail from ACC SOAP:
         build_get_delivery_envelope(token, security_token, template_id)
         → Returns full XML with content/html/source CDATA
       INSERT acc_deliverytemplate_raw (raw XML)
       already_in_raw.add(source_id)   ← update in-memory set
     Else:
       Skip SOAP call — raw already stored

   STEP B — Parsed extraction (skip if already parsed):
     If source_id NOT in already_in_parsed:
       If detail was just fetched in Step A → use it directly
       Else (raw existed in DB, detail not fetched):
         Load raw_xml from acc_deliverytemplate_raw
         parse_delivery_detail(raw_xml) → re-derive detail from stored XML
       Parse fields:
         subject      → _find(delivery, "subject")
         htmlBody     → _find(content → html → source) CDATA
         textBody     → _find(content → text → source)
         smsContent   → _find(content → sms → source)
       INSERT acc_deliverytemplate_parsed (parsed JSON)
       already_in_parsed.add(source_id)
       COMMIT
     Else:
       skipped += 1   ← already fully processed

5. Return: { extracted, total_found, skipped, batch_id, errors }
```

**Per-template decision matrix:**

| In raw? | In parsed? | Action |
|---|---|---|
| No | No | SOAP fetch → store raw → parse → store parsed |
| No | Yes | (impossible in normal flow — skipped) |
| Yes | No | Skip SOAP, reload raw XML from DB → parse → store parsed |
| Yes | Yes | Skip entirely (`skipped++`) |

**Pagination:** Frontend loops calling `POST /api/templates/extract` until `total_found === 0`. Each call advances by exactly `page_size` templates. The raw row count in DB acts as the cursor so no pagination state needs to be stored separately.

---

## Configuration

### `backend/config.py`

| Key | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:pavitra@localhost:5432/acc_ajo` | DB connection string |
| `ENCRYPTION_KEY` | (required, from .env) | Fernet key for credential encryption |
| `SOAP_TIMEOUT` | `30.0` | Seconds before ACC SOAP call times out |
| `CORS_ORIGINS_RAW` | `http://localhost:3000,http://localhost:5173` | Allowed frontend origins |
| `template_page_size` | `100` | Templates fetched per extraction batch |

### `backend/config_placeholder.py`

Maps ACC `<%=recipient.firstName%>` personalization tokens to AJO profile field equivalents:

```python
FIELD_MAPPING = {
  "recipient.firstName":   "profile.person.name.firstName",
  "recipient.email":       "profile.personalEmail.address",
  "recipient.city":        "profile.homeAddress.city",
  "recipient.country":     "profile.homeAddress.country",
  "targetData.changeType": "context.changeType",
  "targetData.planName":   "context.planName",
  ...
}
```

Used during template transformation to replace ACC tokens with AJO-compatible ones before pushing templates to AJO.

---

## Route Protection

Defined in `App.tsx`:

```tsx
<ProtectedRoute condition={accConnected && ajoConnected}>
  <MigrationTypePage />      // /migration/type
  <MigrationSelectPage />    // /migration/select
  <MigrationRunPage />       // /migration/run
  <TemplateMigrationPage />  // /migration/template
</ProtectedRoute>
```

If `accConnected || ajoConnected` is false → redirected to `/` (ConfigPage).
Connection state lives in Zustand (`useConfigStore`) — set by ConfigPage on load via `GET /api/acc/status` and `GET /api/ajo/status`.

---

## Security Notes

| What | How |
|---|---|
| All passwords, client_secrets, access_tokens | Fernet-encrypted before DB storage |
| SOAP session/security tokens (classic) | Stored plaintext — required for direct SOAP header injection |
| Browser session | `acc_session` cookie: httponly, samesite=lax, 7-day rolling |
| Token auto-refresh (technical) | `encrypted_credentials` used — never exposed to browser |
| `.env` file | Never committed — contains `ENCRYPTION_KEY` and `DATABASE_URL` |
