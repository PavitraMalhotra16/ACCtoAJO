# ACC → AJO Migration Tool

Migrates **relational schemas** from Adobe Campaign Classic (ACC) into Adobe Journey Optimizer
(AJO) by creating them in the Adobe Experience Platform (AEP) **Schema Registry**. Standard schemas
are out of scope — this tool handles relational (model-based, `adhoc-v2`) schemas only.

## Run

Use the helper scripts in `scripts/` — they free the port, kill stale instances, and run from
the correct directory, which avoids the cwd / duplicate-process / stuck-socket issues. Each runs
in the foreground (run in its own terminal; Ctrl+C stops).

**Backend** (FastAPI, port **8001**):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1
```

**Frontend** (React + Vite, ~5173, proxies `/api` → `:8001`):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
```

**Stop everything** (wipe stale backend/frontend + free the dev ports):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop-dev.ps1
```

Notes:
- Backend is on **8001** (port 8000 hit a stuck listening socket); `vite.config.ts` proxies to 8001.
  To use 8000 instead: `start-backend.ps1 -Port 8000` and point the proxy back to 8000.
- Backend runs **without `--reload`** on purpose — a reload kills an in-flight background migration
  and can spawn duplicate workers that fight over the port. **Re-run `start-backend.ps1` after any
  backend code change** to pick it up.
- Vite binds `localhost` (IPv6 `::1`) and picks the next free port if 5173 is busy — open the
  `http://localhost:<port>/` it prints, not `127.0.0.1`.

**Backend tests** — from `backend/` (no real DB/network; uses mocks + aiosqlite):
```bash
python -m pytest -q
```

**Frontend type-check** — from `frontend_app/`:
```bash
npx tsc --noEmit      # or: npm run build
```

## Prerequisites
- **PostgreSQL** running with the `acc_ajo` database (backend connects on startup via `DATABASE_URL`).
- **`backend/.env`** must define `ENCRYPTION_KEY` (Fernet key — `core/security.py` raises at import without it)
  and `DATABASE_URL`. See `backend/.env.example`.

## Architecture

Three stages, ACC (source) → AEP/AJO (destination):

1. **Auth** (`routes/auth.py`) — ACC via SOAP logon (classic) or IMS (technical); AJO via OAuth S2S
   (client-credentials). All secrets are Fernet-encrypted in Postgres. AJO access tokens auto-refresh
   (`pipeline/handlers.py:get_valid_access_token`).
2. **Extract & convert** (`routes/conversion.py`, `services/`) — pull ACC schema XML over SOAP, parse to
   JSON (`services/schema_inspector.py`), store as `converted_schemas.raw_json`.
3. **Migration pipeline** (`pipeline_steps.py` + `pipeline/runner.py` + `pipeline/handlers.py`) —
   14 ordered steps, triggered by `routes/migrate.py`. Per-schema progress (`SchemaJobItem`) drives the
   live UI on `MigrationRunPage.tsx`.

### Pipeline steps (`backend/pipeline_steps.py`)
Steps carry a `phase`. The runner runs **PASS 1 (phase 1) concurrently for all schemas, then PASS 2
(phase 2) sequentially** (so relationships are only wired after every schema exists).

| # | Step | Phase | Purpose |
|---|------|-------|---------|
| 1–5 | LOAD_JSON, MAP_TYPES, RESOLVE_IDENTITY, FETCH_TENANT_ID, BUILD_PAYLOAD | 1 | Build the enriched JSON; written to `converted_schemas.enriched_json` right after step 5. |
| 6 | NORMALIZE_INPUT | 1 | Read/validate enriched JSON from the DB as push input. |
| 7 | DUPLICATE_CHECK | 1 | Find the schema in the AEP registry by title. |
| 8 | CREATE_SCHEMA | 1 | Create it (adhoc-v2), or PATCH in missing columns if it exists. |
| 9–12 | PRIMARY_KEY / VERSION / TIMESTAMP / IDENTITY descriptors | 1 | TIMESTAMP only for time-series; IDENTITY only for true person keys. |
| 13 | RELATIONSHIP_DESCRIPTORS | 2 | Wire FK→target links (global reconcile). |
| 14 | VERIFY | 2 | Confirm schema + descriptors via GET. |

Terminal state: `COMPLETED` ("Pushed to AJO"), or the `ALREADY_EXISTS` sentinel ("Already in AJO —
nothing to push") when nothing was missing. Failures are resumable: `routes/migrate.py` resumes from
`current_step_order - 1` (re-runs the failed step), which is safe because handlers are idempotent.

The full push spec is `relational-schema-to-ajo-workflow.md` (source of truth for the API calls).

## Key conventions (the AJO push — `pipeline/handlers.py`, `pipeline/aep_client.py`)
- **No new DB tables for resolution.** Everything reconciles from the **live AEP registry**
  (`GET /tenant/schemas`, `GET /tenant/descriptors`) vs. the desired state in `enriched_json`. Each
  handler creates only what's missing → idempotent reruns/resumes. (A few extra GETs are acceptable.)
- **Schema title = ACC `namespace:name`** (e.g. `cus:recipient`). It's the unique dedup key *and* how
  relationship targets resolve to a `$id`. Do not switch back to `namespace:label`.
- **Description** is always `"This table is about <schema_name>"` (the input JSON has none).
- **Relationships are PASS 2** and deferrable: an `A→B` link auto-creates on the first run where both
  A and B exist in the registry (resolved from all `enriched_json` rows). FKs must be root-level;
  cardinality is normalized to `1:1`/`1:0`/`M:1`/`M:0`.
- **Identity descriptors** only for genuine person keys (`pipeline/namespace_config.json`, spec §8a);
  Identity Service region host is `platform-va7.adobe.io`.
- **Accept headers differ**: schema lists use `xed-*`, descriptor lists use `xdm-*`. `$id` is used raw
  in JSON bodies, URL-encoded only in path params.

## Layout
```
backend/
  main.py                 FastAPI app + lifespan (init_db, mark stuck RUNNING→FAILED on restart)
  db.py                   SQLAlchemy models: source_connections, destination_connections,
                          converted_schemas, user_sessions, schema_job_items, tenant_config
  config.py, core/security.py   settings + Fernet encrypt/decrypt, session resolution
  routes/                 auth, schemas, conversion, migrate
  services/               acc_soap, schema_inspector, schema_preview (SOAP + XML→JSON)
  pipeline/
    runner.py             two-pass orchestration, per-step status updates, enriched_json write
    handlers.py           all 14 step handlers + AEP push helpers
    aep_client.py         Schema Registry + Identity Service HTTP wrappers
    namespace_config.json identity namespace mapping (spec §8a)
  tests/                  pytest (mocked DB/HTTP)
frontend_app/             React + Vite + TS + Tailwind + zustand + react-router
  src/pages/MigrationRunPage.tsx   live step-by-step migration dashboard
relational-schema-to-ajo-workflow.md   the push spec
```

## Notes
- Tests mock the DB (`AsyncSessionLocal`) and AEP calls (`pipeline.handlers.aep_client.*`); they never
  hit Postgres or the network. The real AEP request/response shapes still need a live single-schema
  smoke test to confirm.
- `db.py` auto-adds missing columns on managed tables at startup (`ensure_schema_columns`).
