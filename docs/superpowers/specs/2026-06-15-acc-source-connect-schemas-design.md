# ACC Source — Connect & Schema Browse: Design Spec

**Date:** 2026-06-15
**Scope:** Minimal 3-screen flow: login → namespace selector → schema viewer
**Stack:** FastAPI backend (Python), React + Vite + TypeScript frontend, SQLite via existing models

---

## Goal

Let a user enter ACC credentials in a browser, authenticate against an Adobe Campaign Classic SOAP endpoint, then browse schemas by namespace. All connection data is persisted to the existing SQLite DB with passwords encrypted at rest.

---

## Architecture

```
[React UI]
   |  JSON over HTTP
   v
[FastAPI Backend]
   |  SOAP XML
   v
[ACC soaprouter.jsp]  ← http://localhost:8080/nl/jsp/soaprouter.jsp
```

Frontend never calls SOAP directly. Backend owns all SOAP calls and credential decryption.

---

## Screens

### Screen 1 — Connect & Save (`/`)

Fields:
- **Project Name** — string, required
- **Base URL** — string, default `http://localhost:8080`
- **Operator Login** — string, required
- **Password** — password input, required

On submit (sequential):
1. `POST /api/projects` → creates project record, returns `project_id`
2. `PUT /api/projects/:id/source` → saves `base_url`; backend auto-derives `soap_endpoint = base_url + /nl/jsp/soaprouter.jsp`
3. `PUT /api/projects/:id/source/credentials` → saves `operator_login` + encrypted `operator_password`
4. `POST /api/projects/:id/source/test` → backend decrypts password, calls SOAP `Logon`, returns `{ status, message }`

Status badge transitions: idle → testing → ok | error.
On `ok`: "Browse Schemas →" button appears, navigates to `/project/:id/namespaces`.

### Screen 2 — Namespace Selector (`/project/:id/namespaces`)

On mount: calls `GET /api/projects/:id/source/schemas`.

Backend flow:
1. Load `SourceConfig` + `SourceCredentials` from DB
2. Decrypt password
3. SOAP Logon → session token
4. SOAP schema enumeration → full schema list
5. Return `{ schemas: [{ name, namespace, label, primary_key }] }`

Frontend groups schemas by namespace, renders clickable tiles (e.g. `nms`, `xtk`, `nl`).
Clicking a namespace navigates to `/project/:id/schemas/:namespace` and passes schema list via React context.

### Screen 3 — Schema Viewer (`/project/:id/schemas/:namespace`)

Data sourced from React context (already fetched on Screen 2 — no second API call).
Filtered by selected namespace.
Table columns: **Schema Name**, **Label**, **Primary Key**.

---

## API Contract

### Existing endpoints (already built, no changes needed)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/projects` | Create project |
| PUT | `/api/projects/:id/source` | Save base URL |
| PUT | `/api/projects/:id/source/credentials` | Save encrypted credentials |
| POST | `/api/projects/:id/source/test` | SOAP Logon test |

### New endpoint

```
GET /api/projects/:id/source/schemas
Response:
{
  "schemas": [
    {
      "name": "nms:recipient",
      "namespace": "nms",
      "label": "Recipients",
      "primary_key": "iRecipientId"
    }
  ]
}
```

---

## Backend Changes

### `backend/app/services/acc/adapter.py`

Add `get_schemas()` method to `ACCAdapter`:
1. Call `_logon()` → get `session_token` + `security_token`
2. Build SOAP envelope for `xtk:queryDef#ExecuteQuery` on the `xtk:schema` entity
3. Parse XML response → extract `name`, `namespace`, `label`, `pkSequence` (primary key)
4. Return list of dicts

The `_logon()` helper extracts from existing `_test_session_token()` logic to avoid duplication.

### `backend/app/api/source.py`

Add route:
```python
@router.get("/projects/{project_id}/source/schemas")
def get_source_schemas(project_id: str, db: Session = Depends(get_db)):
    # load config + creds from DB
    # decrypt password
    # instantiate ACCAdapter
    # return adapter.get_schemas()
```

---

## Frontend File Map

```
frontend/src/
  App.tsx                           # BrowserRouter + 3 routes
  context/
    ConnectionContext.tsx           # project_id + schemas state, passed via React context
  pages/
    ConnectPage.tsx                 # Screen 1: form + sequential API calls + status badge
    NamespacePage.tsx               # Screen 2: fetch schemas on mount, render namespace tiles
    SchemaViewPage.tsx              # Screen 3: filter schemas from context, render table
  api/
    sourceApi.ts                    # typed fetch wrappers for all 4+1 endpoints
  components/
    FormField.tsx                   # label + input + error message
    StatusBadge.tsx                 # idle | loading | ok | error badge
```

### State model

```ts
// ConnectionContext
interface ConnectionState {
  projectId: string | null
  schemas: Schema[]
  setProjectId: (id: string) => void
  setSchemas: (s: Schema[]) => void
}

interface Schema {
  name: string
  namespace: string
  label: string
  primary_key: string
}
```

Credentials are never stored in context — they live only in the ConnectPage form state and are discarded after the save sequence completes.

---

## Security

- Passwords encrypted with Fernet before DB write (existing `encrypt_value` / `decrypt_value`)
- Passwords never returned to frontend in any API response
- Credentials not stored in React context or localStorage
- SOAP session token kept server-side only (not returned to frontend beyond a truncated preview in test response)

---

## What is explicitly out of scope

- Scope selector (checkbox for which object types to migrate)
- Deep schema field inspection
- Destination (AJO/AEP) configuration
- Project list / project switcher UI
- Error retry logic beyond displaying the error message
