# DB Column Auto-Creation, Error Status Display & Resume Failed Schema Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-create missing PostgreSQL columns on startup and at runtime, display true pipeline failure state in the Add Schema window, and pre-select failed schemas with the Migrate button immediately enabled for one-click resume.

**Architecture:** Three independent changes wired together: (1) a new async `ensure_schema_columns()` in `backend/db.py` called at startup and as a lazy fallback in the pipeline; (2) a display priority fix in `MigrationSelectPage.tsx` so that FAILED pipeline status overrides the "Extracted" green badge; (3) pre-selection of FAILED schemas on load with a button path that bypasses re-extraction and calls `/api/migrate/start` directly.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2 async (asyncpg/PostgreSQL), React 18, TypeScript, Tailwind CSS

---

## File Map

| File | Change |
|------|--------|
| `backend/db.py` | Add `ensure_schema_columns()` async function |
| `backend/main.py` | Call `ensure_schema_columns()` in lifespan after `init_db()` |
| `backend/pipeline/handlers.py` | Lazy fallback in `fetch_tenant_id` — catch ProgrammingError, call `ensure_schema_columns()`, retry |
| `frontend_app/src/pages/MigrationSelectPage.tsx` | Priority fix (FAILED > extracted), pre-select FAILED schemas, update Migrate button logic, add direct-migrate path |
| `frontend_app/src/api/migration.ts` | Export `startMigrationDirect()` function (calls `/api/migrate/start` without extract job) |

---

## Task 1: Add `ensure_schema_columns()` to `backend/db.py`

**Files:**
- Modify: `backend/db.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_db_schema_sync.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_ensure_schema_columns_adds_missing_column():
    """ensure_schema_columns issues ALTER TABLE for a column in ORM but not in DB."""
    existing_cols = {"id", "org_id"}  # tenant_id missing
    model_cols = {"id", "org_id", "tenant_id", "client_id"}

    executed_stmts = []

    async def fake_execute(stmt, *args, **kwargs):
        sql = str(stmt)
        executed_stmts.append(sql)
        if "information_schema" in sql:
            # Return only the existing cols
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(c,) for c in existing_cols]
            return mock_result
        return MagicMock()

    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = fake_execute
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    with patch("db.engine") as mock_engine:
        mock_engine.connect.return_value = mock_conn
        with patch("db.Base") as mock_base:
            mock_table = MagicMock()
            mock_table.name = "destination_connections"
            col_id = MagicMock(); col_id.name = "id"; col_id.primary_key = True
            col_org = MagicMock(); col_org.name = "org_id"; col_org.primary_key = False
            col_tenant = MagicMock(); col_tenant.name = "tenant_id"; col_tenant.primary_key = False
            col_client = MagicMock(); col_client.name = "client_id"; col_client.primary_key = False
            mock_table.columns = [col_id, col_org, col_tenant, col_client]
            mock_class = MagicMock()
            mock_class.__table__ = mock_table
            mock_base.registry.mappers = [MagicMock(class_=mock_class)]

            from db import ensure_schema_columns
            await ensure_schema_columns()

    alter_stmts = [s for s in executed_stmts if "ALTER TABLE" in s.upper()]
    assert len(alter_stmts) >= 1
    assert any("tenant_id" in s for s in alter_stmts)
    assert not any("client_id" in s for s in alter_stmts)  # already exists
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_db_schema_sync.py -v
```

Expected: `ImportError` or `AttributeError: module 'db' has no attribute 'ensure_schema_columns'`

- [ ] **Step 3: Implement `ensure_schema_columns()` in `backend/db.py`**

Add this import at the top of `backend/db.py` (after existing imports):

```python
import logging
from sqlalchemy import text
```

Add this function at the bottom of `backend/db.py`, before `get_db()`:

```python
log = logging.getLogger("acc_backend.db")

# Tables managed by auto-column repair. Only connection tables — not job/schema tables.
_MANAGED_TABLES = {"source_connections", "destination_connections"}


async def ensure_schema_columns() -> None:
    """
    Compare ORM model columns against the live DB for managed tables.
    Issues ALTER TABLE ... ADD COLUMN IF NOT EXISTS for any missing non-PK columns.
    Safe to call multiple times (IF NOT EXISTS is idempotent).
    """
    async with engine.connect() as conn:
        for mapper in Base.registry.mappers:
            table = mapper.class_.__table__
            if table.name not in _MANAGED_TABLES:
                continue

            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = :tname"
                ),
                {"tname": table.name},
            )
            existing = {row[0] for row in result.fetchall()}

            for col in table.columns:
                if col.primary_key or col.name in existing:
                    continue
                col_type = col.type.compile(dialect=conn.dialect)
                nullable = "" if col.nullable is False else ""
                await conn.execute(
                    text(
                        f'ALTER TABLE "{table.name}" '
                        f'ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                    )
                )
                log.warning(
                    "Added missing column %r to table %r", col.name, table.name
                )

        await conn.commit()
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd backend && python -m pytest tests/test_db_schema_sync.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/db.py backend/tests/test_db_schema_sync.py
git commit -m "feat: add ensure_schema_columns() for auto DB column repair"
```

---

## Task 2: Call `ensure_schema_columns()` at app startup

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_startup_schema_sync.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_lifespan_calls_ensure_schema_columns():
    """ensure_schema_columns must be called during app startup."""
    from main import lifespan
    from fastapi import FastAPI

    app = FastAPI()

    with patch("main.init_db", new_callable=AsyncMock) as mock_init, \
         patch("main.ensure_schema_columns", new_callable=AsyncMock) as mock_ensure, \
         patch("main.AsyncSessionLocal") as mock_session_factory:

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=AsyncMock(scalars=lambda: AsyncMock(all=lambda: [])))
        mock_session_factory.return_value = mock_session

        async with lifespan(app):
            pass

        mock_ensure.assert_called_once()
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_startup_schema_sync.py -v
```

Expected: `AssertionError: Expected 'ensure_schema_columns' to have been called once`

- [ ] **Step 3: Update `backend/main.py` lifespan**

Add the import at the top of `main.py` (after `from db import ...`):

```python
from db import UserSession, SchemaJobItem, init_db, AsyncSessionLocal, ensure_schema_columns
```

In the `lifespan` function, add the call immediately after `await init_db()`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_schema_columns()          # <-- add this line
    async with AsyncSessionLocal() as db:
        # ... rest of existing lifespan code unchanged ...
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd backend && python -m pytest tests/test_startup_schema_sync.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_startup_schema_sync.py
git commit -m "feat: call ensure_schema_columns() at app startup"
```

---

## Task 3: Lazy fallback in `fetch_tenant_id`

**Files:**
- Modify: `backend/pipeline/handlers.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_fetch_tenant_id_fallback.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy.exc import ProgrammingError

@pytest.mark.asyncio
async def test_fetch_tenant_id_retries_after_column_missing():
    """On ProgrammingError with 'column', ensure_schema_columns is called and the step retries."""
    ctx = {"org_id": "TESTORG@AdobeOrg"}
    data = {}

    call_count = 0

    async def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate missing column error on first call
            orig = MagicMock()
            orig.args = ["column tenant_id does not exist"]
            raise ProgrammingError("column tenant_id does not exist", orig, orig)
        # Second call succeeds — return a mock dest with tenant_id
        mock_result = AsyncMock()
        mock_dest = MagicMock()
        mock_dest.tenant_id = "_testorg"
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_dest)
        return mock_result

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("pipeline.handlers.AsyncSessionLocal", return_value=mock_session), \
         patch("pipeline.handlers.ensure_schema_columns", new_callable=AsyncMock) as mock_ensure:

        from pipeline.handlers import fetch_tenant_id
        result = await fetch_tenant_id(ctx, data)

    mock_ensure.assert_called_once()
    assert result["tenantId"] == "_testorg"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && python -m pytest tests/test_fetch_tenant_id_fallback.py -v
```

Expected: `AssertionError` — `ensure_schema_columns` not called (fallback not yet implemented)

- [ ] **Step 3: Update `fetch_tenant_id` in `backend/pipeline/handlers.py`**

Add import at the top of `pipeline/handlers.py` (near other db imports):

```python
from sqlalchemy.exc import ProgrammingError
from db import AsyncSessionLocal, DestinationConnection, ensure_schema_columns
```

Replace the `fetch_tenant_id` function (lines 423–442) with:

```python
async def fetch_tenant_id(ctx: dict, data: dict) -> dict:
    """Read tenant ID from DestinationConnection. Auto-repairs missing column once if needed."""
    org_id = ctx["org_id"]

    async def _query_tenant_id() -> str | None:
        async with AsyncSessionLocal() as db:
            dest_result = await db.execute(
                select(DestinationConnection).where(DestinationConnection.org_id == org_id)
            )
            dest = dest_result.scalar_one_or_none()
        return dest.tenant_id if dest and dest.tenant_id else None

    try:
        tenant_id = await _query_tenant_id()
    except ProgrammingError as exc:
        if "column" in str(exc).lower():
            log.warning("Missing DB column detected in fetch_tenant_id — running ensure_schema_columns")
            await ensure_schema_columns()
            tenant_id = await _query_tenant_id()
        else:
            raise

    if not tenant_id:
        tenant_id = _derive_tenant_id(org_id)
        log.warning("tenant_id not on DestinationConnection for %s — derived as %s", org_id, tenant_id)

    data["tenantId"] = tenant_id
    log.info("Tenant ID %r for org %s", tenant_id, org_id)
    return data
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd backend && python -m pytest tests/test_fetch_tenant_id_fallback.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Run all backend tests to check for regressions**

```bash
cd backend && python -m pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/handlers.py backend/tests/test_fetch_tenant_id_fallback.py
git commit -m "feat: lazy DB column repair fallback in fetch_tenant_id pipeline step"
```

---

## Task 4: Fix error status display priority in `MigrationSelectPage.tsx`

**Files:**
- Modify: `frontend_app/src/pages/MigrationSelectPage.tsx`

**Context:** Currently `alreadyExtracted` (green checkmark) takes rendering priority over `inProgress` (FAILED badge). A schema that has been extracted but whose migration job failed shows "Extracted — enriched JSON ready" instead of the failure. The `isLocked` condition also prevents the user from interacting with either type.

- [ ] **Step 1: Update the schema row rendering logic**

In `MigrationSelectPage.tsx`, find the block inside the `filtered.map(s => ...)` render (around line 326). Replace the derived variables and the row JSX with the following:

```tsx
{filtered.map(s => {
  const k = key(s)
  const schemaKey = `${s.namespace}:${s.name}`
  const checked = selected.has(k)
  const alreadyExtracted = extracted.has(schemaKey)
  const inProgress = incomplete[schemaKey]
  const isFailed = inProgress?.status === 'FAILED'

  // FAILED pipeline status takes priority over extracted badge.
  // Extracted-but-not-failed schemas remain locked (can't re-select).
  const isLocked = isFailed ? false : (alreadyExtracted || !!inProgress)

  return (
    <div
      key={k}
      className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 transition-colors ${
        isFailed
          ? checked
            ? 'bg-red-50 border-l-2 border-l-red-400 cursor-pointer'
            : 'bg-red-50/50 cursor-pointer hover:bg-red-50'
          : isLocked
            ? 'bg-gray-50 cursor-default'
            : checked
              ? 'bg-blue-50 border-l-2 border-l-blue-500 cursor-pointer'
              : 'hover:bg-gray-50 cursor-pointer'
      }`}
      onClick={() => { if (!isLocked) toggle(s) }}
    >
      {/* Left icon */}
      {isFailed ? (
        <input
          type="checkbox"
          checked={checked}
          onChange={() => toggle(s)}
          onClick={e => e.stopPropagation()}
          className="mt-0.5 rounded accent-red-500"
        />
      ) : alreadyExtracted ? (
        <svg className="mt-0.5 w-4 h-4 text-green-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
        </svg>
      ) : inProgress ? (
        <div className={`mt-0.5 w-4 h-4 shrink-0 rounded-full border-2 ${inProgress.status === 'FAILED' ? 'border-red-400' : 'border-blue-400'}`} />
      ) : (
        <input
          type="checkbox"
          checked={checked}
          onChange={() => toggle(s)}
          onClick={e => e.stopPropagation()}
          className="mt-0.5 rounded"
        />
      )}

      <div className="min-w-0 flex-1">
        <div className={`text-xs font-mono truncate ${isLocked ? 'text-gray-500' : isFailed ? 'text-red-700' : 'text-blue-700'}`}>
          {s.namespace}:{s.name}
        </div>
        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
          {s.label && <span className="text-xs text-gray-400 truncate">{s.label}</span>}

          {!isFailed && alreadyExtracted && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700 font-medium shrink-0">
              Extracted — enriched JSON ready
            </span>
          )}

          {isFailed && (
            <span
              className="text-xs px-1.5 py-0.5 rounded font-medium shrink-0 bg-red-50 text-red-600"
              title={inProgress?.error_message ?? undefined}
            >
              Failed: {inProgress?.current_step ?? `step ${inProgress?.current_step_order}`}
              {inProgress?.error_message ? ` — ${inProgress.error_message.slice(0, 60)}${inProgress.error_message.length > 60 ? '…' : ''}` : ''}
            </span>
          )}

          {!isFailed && inProgress && (
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${
              inProgress.status === 'FAILED' ? 'bg-red-50 text-red-600' : 'bg-amber-50 text-amber-600'
            }`}>
              {inProgress.status === 'FAILED' ? 'Failed at' : 'Stopped at'}{' '}
              {inProgress.current_step
                ? inProgress.current_step === 'BUILD_PAYLOAD' ? 'Enriched JSON' : 'Extracted schema'
                : `step ${inProgress.current_step_order}`}
            </span>
          )}
        </div>
      </div>
    </div>
  )
})}
```

- [ ] **Step 2: Commit**

```bash
git add frontend_app/src/pages/MigrationSelectPage.tsx
git commit -m "fix: show pipeline FAILED status instead of extracted badge in schema list"
```

---

## Task 5: Pre-select failed schemas and enable Migrate button for resume

**Files:**
- Modify: `frontend_app/src/pages/MigrationSelectPage.tsx`
- Modify: `frontend_app/src/api/migration.ts`

- [ ] **Step 1: Add `startMigrationDirect` to `migration.ts`**

In `frontend_app/src/api/migration.ts`, add this function after `startMigration`:

```ts
export async function startMigrationDirect(): Promise<{ job_id: string; message: string; total: number; queued: number; skipped: number }> {
  let res: Response
  try {
    res = await fetch('/api/migrate/start', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ extract_job_id: null }),
    })
  } catch {
    throw new Error('Backend server is not running — please start it first')
  }
  if (!res.ok) await _safeError(res, 'Failed to start migration')
  return res.json()
}
```

- [ ] **Step 2: Update `MigrationSelectPage.tsx` — import and pre-select**

At the top of `MigrationSelectPage.tsx`, update the import from `migration.ts`:

```tsx
import { startConversion, getExtractedSchemas, getIncompleteSchemas, startMigrationDirect, type IncompleteSchema } from '../api/migration'
```

In the `useEffect`, after building `incompleteMap`, pre-select all FAILED schemas:

```tsx
.then(([schemasData, extractedData, incompleteData]) => {
  const allSchemas = (schemasData.schemas ?? []).filter(
    s => !EXCLUDED_NAMESPACES.has(s.namespace.toLowerCase())
  )
  setSchemas(allSchemas)
  setExtracted(new Set(extractedData.extracted))

  const incompleteMap: Record<string, IncompleteSchema> = {}
  for (const s of incompleteData.schemas) incompleteMap[s.schema_name] = s
  setIncomplete(incompleteMap)

  // Pre-select all FAILED schemas so the user can retry them immediately
  const failedKeys = new Set(
    incompleteData.schemas
      .filter(s => s.status === 'FAILED')
      .map(s => s.schema_name)
  )
  if (failedKeys.size > 0) {
    setSelected(failedKeys)
  }
})
```

- [ ] **Step 3: Update `handleNext` to take the direct-migrate path for failed schemas**

Replace the `handleNext` function in `MigrationSelectPage.tsx`:

```tsx
async function handleNext() {
  const chosen = schemas.filter(s => selected.has(key(s)))
  if (!chosen.length) return
  setStarting(true)
  setError(null)
  try {
    // If every selected schema already has extracted JSON (i.e. all are failed-migration
    // schemas, not new selections), skip re-extraction and go straight to migration.
    const allAlreadyExtracted = chosen.every(s => extracted.has(key(s)))
    if (allAlreadyExtracted) {
      const data = await startMigrationDirect()
      if (data.message === 'all_done') {
        setError('All selected schemas are already fully migrated.')
        setStarting(false)
        return
      }
      navigate(`/migration/run?migrate_job=${data.job_id}`)
      return
    }

    // Normal path: new schemas need extraction first
    const data = await startConversion(chosen)
    if (data.message === 'all_done' || !data.job_id) {
      setError('All selected schemas are already migrated — nothing new to extract.')
      setStarting(false)
      return
    }
    navigate(`/migration/run?extract_job=${data.job_id}`)
  } catch (e: unknown) {
    setError(e instanceof Error ? e.message : 'Failed to start')
    setStarting(false)
  }
}
```

- [ ] **Step 4: Update Migrate button disabled condition**

Find the Migrate button (around line 278). The `disabled` prop currently is:

```tsx
disabled={selected.size === 0 || starting || loading}
```

It should remain the same — pre-selecting failed schemas sets `selected.size > 0`, so the button will already be enabled. No change needed here.

- [ ] **Step 5: Update the header selected-count badge**

The existing badge already shows `{selected.size} selected`. No change needed.

- [ ] **Step 6: Confirm `MigrationRunPage.tsx` already handles `migrate_job`**

`MigrationRunPage.tsx` already reads `migrate_job` from the URL (line 312) and sets `initialPhase = 'migrating'` when it is present (line 315). No code change needed. Just confirm the route works end-to-end in Task 6 manual verification.

- [ ] **Step 7: Commit**

```bash
git add frontend_app/src/pages/MigrationSelectPage.tsx frontend_app/src/api/migration.ts
git commit -m "feat: pre-select failed schemas and enable direct-migrate resume path"
```

---

## Task 6: Manual verification

- [ ] **Step 1: Start the backend**

```bash
cd backend && uvicorn main:app --reload --port 8000
```

Check startup logs for: `"DB ready"` with no column-error warnings (or with `"Added missing column"` if columns were genuinely missing).

- [ ] **Step 2: Open the Add Schema window with a known-failed schema**

1. Navigate to the migration tool in the browser.
2. Ensure at least one schema has a `SchemaJobItem` with `status = 'FAILED'`.
3. Open the Add Schema (MigrationSelectPage) window.
4. Confirm: the failed schema row shows a red background and the error message badge (not "Extracted — enriched JSON ready").
5. Confirm: the failed schema is pre-checked.
6. Confirm: the Migrate button is enabled without any additional selection.

- [ ] **Step 3: Click Migrate and confirm resume**

1. Click the Migrate button with only the pre-selected failed schema.
2. Confirm: navigates to the migration run page.
3. Confirm: the migration job picks up from the last successful step (not step 0).
4. Confirm: the schema reaches COMPLETED status.

- [ ] **Step 4: Simulate missing column**

1. Manually drop the `tenant_id` column from `destination_connections` in psql:
   ```sql
   ALTER TABLE destination_connections DROP COLUMN tenant_id;
   ```
2. Restart the backend.
3. Check logs: `"Added missing column 'tenant_id' to table 'destination_connections'"`.
4. Confirm the column is back:
   ```sql
   \d destination_connections
   ```
