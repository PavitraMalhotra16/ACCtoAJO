# Design: DB Column Auto-Creation, Error Status Display, and Resume Failed Schema Flow

**Date:** 2026-06-19  
**Status:** Approved

---

## Overview

Three related improvements to the ACC2AJO migration tool:

1. **DB Column Auto-Creation** — automatically add missing columns to the DB when the schema is out of sync with the ORM model.
2. **Error Status Display Fix** — the Add Schema window must show the true pipeline outcome (including failure reason) instead of always showing "extracted enriched JSON."
3. **Resume Failed Schema Flow** — failed schemas are pre-selected in the Add Schema window with the Migrate button immediately enabled, so the user can retry from where the pipeline stopped.

---

## Issue 1: DB Column Auto-Creation

### Problem
`DestinationConnection.tenant_id` (and potentially other columns added to the ORM model after initial deployment) may not exist in the live SQLite DB if the user never ran a migration. This causes `OperationalError: no such column` at runtime, which can silently abort the pipeline mid-step.

### Solution

**New function:** `ensure_schema_columns()` in `backend/db.py`

- Uses `sqlalchemy.inspect(engine)` to get actual columns per table.
- Diffs against each ORM model's `__table__.columns`.
- Issues `ALTER TABLE ... ADD COLUMN` (with type, nullable, and server_default if present) for any missing columns.
- Scoped to: `DestinationConnection`, `SourceConnection`. Does not touch job/schema tables.

**At startup:** Called once in `main.py` (lifespan or startup event) before the server begins accepting requests. Uses the sync engine for this one-time check.

**Lazy fallback:** In `backend/pipeline/handlers.py`, `fetch_tenant_id()` wraps the DB read in a try/except for `sqlalchemy.exc.OperationalError`. If the error message contains `"no such column"` or `"column does not exist"`, it calls `ensure_schema_columns()` and retries once. If it fails again, it re-raises.

### Files Changed
- `backend/db.py` — add `ensure_schema_columns()`
- `backend/main.py` — call `ensure_schema_columns()` at startup
- `backend/pipeline/handlers.py` — lazy fallback in `fetch_tenant_id()`

---

## Issue 2: Error Status Display Fix

### Problem
The Add Schema window queries `ConvertedSchema` rows, which only reflect extraction status. When a pipeline job fails mid-way (e.g., at `FETCH_TENANT_ID`), the `SchemaJobItem` record holds the failure, but the Add Schema window never reads it — so it shows "extracted enriched JSON" as if everything is fine.

### Solution

**Backend:** The schema list endpoint (in `backend/routes/schemas.py` or equivalent) is augmented with a LEFT JOIN (or subquery) to fetch the latest `SchemaJobItem` per schema, ordered by `created_at DESC`, excluding QUEUED status. Two new fields added to each schema entry in the response:
- `job_status`: `"FAILED"` | `"COMPLETED"` | `"RUNNING"` | `null`
- `job_error`: error message string or `null`

**Frontend:** The Add Schema window schema list renders a status badge per row:
- `FAILED` → red badge with truncated `job_error` text; full message visible on hover.
- `COMPLETED` → green badge.
- `null` (never migrated) → no badge.

### Files Changed
- `backend/routes/schemas.py` (or the relevant list endpoint) — join with `SchemaJobItem`
- Frontend Add Schema window component — render `job_status` / `job_error` badges

---

## Issue 3: Resume Failed Schema Flow

### Problem
When a schema's pipeline job fails, after a browser refresh the user lands on the Add Schema window. The Migrate button is disabled until the user manually selects a schema. There is no indication of which schemas failed, and no easy way to retry only those schemas without re-selecting them.

### Solution

**On load:** When the schema list loads, any schema with `job_status = "FAILED"` is automatically pre-checked and its row is visually highlighted (light red background + error badge from Issue 2).

**Migrate button state:** Enabled if:
- At least one schema is manually selected by the user, OR
- At least one failed schema is pre-checked (loaded state)

This means the Migrate button is immediately active on page load when failures exist.

**On click:** Pre-selected failed schemas are included in the migration payload alongside any user-selected new schemas. The backend's existing resume-from-snapshot logic in `backend/routes/migrate.py` (lines 79–105) picks up each failed schema from its last successful step snapshot.

**User control:** The user can deselect any pre-checked failed schema. They can also mix new schemas with failed retries in a single Migrate action.

### Files Changed
- Frontend Add Schema window component — pre-check failed schemas, update Migrate button enabled logic
- `backend/routes/migrate.py` — no changes needed (resume logic already exists)

---

## Data Flow Summary

```
App startup
  └── ensure_schema_columns()
        └── inspect DB columns vs ORM model
        └── ALTER TABLE for any missing columns

Browser refresh → Add Schema window opens
  └── GET /api/schemas (or equivalent)
        └── Returns ConvertedSchema + latest SchemaJobItem per schema
        └── { job_status, job_error } per row

Frontend renders schema list
  └── Failed schemas: pre-checked + red badge + error text
  └── Migrate button: enabled (failed pre-checks satisfy condition)

User clicks Migrate (or accepts pre-selection)
  └── POST /api/migrate/start with failed schema IDs
        └── routes/migrate.py finds last FAILED job + snapshot
        └── Resumes pipeline from last successful step
        └── fetch_tenant_id: lazy fallback if column still missing
```

---

## Out of Scope
- Alembic or any versioned migration framework
- Dropping or modifying existing columns
- Auto-retry without user confirmation
- Any changes to Phase 3 (AEP API integration)
