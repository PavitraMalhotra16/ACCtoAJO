# ACC Source Connect & Schema Browse — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-screen UI that lets a user enter ACC credentials, authenticate via SOAP, then browse schemas by namespace.

**Architecture:** FastAPI backend owns all SOAP calls and credential decryption. React frontend collects credentials once, persists them to SQLite via the existing project/source model, then calls two backend endpoints (test + schemas). Schema data flows through React context from the fetch on Screen 2 to the filter on Screen 3.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, zeep (SOAP), httpx, xml.etree.ElementTree, React 18, Vite, TypeScript, TailwindCSS, React Router v7, no Zustand needed.

---

## File Map

```
backend/
  app/
    services/acc/adapter.py       MODIFY — extract _logon(), add get_schemas()
    api/source.py                 MODIFY — add GET /projects/:id/source/schemas
  tests/
    test_acc_adapter.py           MODIFY — add get_schemas tests
    test_source.py                MODIFY — add schemas endpoint test

frontend/src/
  main.tsx                        MODIFY — add BrowserRouter
  App.tsx                         REPLACE — router + ConnectionProvider
  context/
    ConnectionContext.tsx         CREATE — projectId + schemas state
  api/
    sourceApi.ts                  CREATE — typed fetch wrappers (5 calls)
  components/
    FormField.tsx                 CREATE — label + input + error message
    StatusBadge.tsx               CREATE — idle|loading|ok|error badge
  pages/
    ConnectPage.tsx               CREATE — Screen 1: form + sequential save + test
    NamespacePage.tsx             CREATE — Screen 2: fetch schemas, namespace tiles
    SchemaViewPage.tsx            CREATE — Screen 3: filter + table
```

---

## Task 1: Refactor ACCAdapter — extract `_logon()`, add `get_schemas()`

**Files:**
- Modify: `backend/app/services/acc/adapter.py`
- Modify: `backend/tests/test_acc_adapter.py`

### Why this first

`get_schemas()` needs to call `_logon()` internally. Extracting it from the existing `_test_session_token()` removes duplication and gives `get_schemas()` a clean foundation.

- [ ] **Step 1: Add failing tests for `get_schemas()`**

Open `backend/tests/test_acc_adapter.py` and append these tests:

```python
def test_get_schemas_returns_list(session_token_creds):
    mock_service = MagicMock()
    mock_service.Logon.return_value = MagicMock(
        sessionToken="tok123",
        securityToken="sec456",
    )

    soap_xml = """<?xml version='1.0'?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV='http://schemas.xmlsoap.org/soap/envelope/'>
  <SOAP-ENV:Body>
    <ExecuteQueryResponse xmlns='urn:xtk:queryDef'>
      <pdomOutput>
        <collection>
          <schema name='recipient' namespace='nms' label='Recipients' pkSequence='iRecipientId'/>
          <schema name='delivery' namespace='nms' label='Deliveries' pkSequence='iDeliveryId'/>
          <schema name='operator' namespace='xtk' label='Operators' pkSequence='iOperatorId'/>
        </collection>
      </pdomOutput>
    </ExecuteQueryResponse>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 200
    mock_http_resp.text = soap_xml

    with patch("zeep.Client", return_value=MagicMock(service=mock_service)), \
         patch("httpx.post", return_value=mock_http_resp):
        adapter = ACCAdapter(session_token_creds)
        schemas = adapter.get_schemas()

    assert len(schemas) == 3
    assert schemas[0] == {
        "name": "nms:recipient",
        "namespace": "nms",
        "label": "Recipients",
        "primary_key": "iRecipientId",
    }
    nms_schemas = [s for s in schemas if s["namespace"] == "nms"]
    assert len(nms_schemas) == 2


def test_get_schemas_logon_failure_raises(session_token_creds):
    with patch("zeep.Client", side_effect=Exception("Cannot connect")):
        adapter = ACCAdapter(session_token_creds)
        with pytest.raises(Exception, match="Cannot connect"):
            adapter.get_schemas()


def test_get_schemas_soap_error_raises(session_token_creds):
    mock_service = MagicMock()
    mock_service.Logon.return_value = MagicMock(
        sessionToken="tok123",
        securityToken="sec456",
    )
    mock_http_resp = MagicMock()
    mock_http_resp.status_code = 500
    mock_http_resp.text = "Internal Server Error"

    with patch("zeep.Client", return_value=MagicMock(service=mock_service)), \
         patch("httpx.post", return_value=mock_http_resp):
        adapter = ACCAdapter(session_token_creds)
        with pytest.raises(RuntimeError, match="Schema fetch failed: 500"):
            adapter.get_schemas()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_acc_adapter.py::test_get_schemas_returns_list tests/test_acc_adapter.py::test_get_schemas_logon_failure_raises tests/test_acc_adapter.py::test_get_schemas_soap_error_raises -v
```

Expected: `AttributeError` — `ACCAdapter has no attribute 'get_schemas'`

- [ ] **Step 3: Rewrite `backend/app/services/acc/adapter.py`**

Replace the entire file:

```python
from typing import Any
from xml.etree import ElementTree as ET
import httpx
import zeep


class ACCAdapter:
    def __init__(self, config: dict[str, Any]):
        self.auth_method = config.get("auth_method", "session_token")
        self.base_url = config.get("base_url", "").rstrip("/")
        self.soap_endpoint = f"{self.base_url}/nl/jsp/soaprouter.jsp"
        self.operator_login = config.get("operator_login", "")
        self.operator_password = config.get("operator_password", "")
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.token_endpoint = config.get("token_endpoint", "")
        self.scope = config.get("scope", "")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test_connection(self) -> dict[str, Any]:
        if self.auth_method == "session_token":
            return self._test_session_token()
        return self._test_technical_account()

    def get_schemas(self) -> list[dict[str, str]]:
        """Logon then enumerate xtk:schema via raw SOAP. Returns list of schema dicts."""
        session_token, _ = self._logon()
        return self._fetch_schemas(session_token)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _logon(self) -> tuple[str, str]:
        """Returns (session_token, security_token). Raises on failure."""
        wsdl = f"{self.base_url}/nl/jsp/schemawsdl.jsp?schema=xtk:session"
        client = zeep.Client(wsdl)
        resp = client.service.Logon(
            strLogin=self.operator_login,
            strPassword=self.operator_password,
            elemParameters=None,
        )
        return resp.sessionToken, resp.securityToken

    def _test_session_token(self) -> dict[str, Any]:
        try:
            session_token, _ = self._logon()
            return {
                "status": "ok",
                "auth_method": "session_token",
                "session_token": session_token[:8] + "...",
                "message": "Connected successfully",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _test_technical_account(self) -> dict[str, Any]:
        try:
            from app.services.ims.token_manager import token_manager
            token = token_manager.get_token(
                client_id=self.client_id,
                client_secret=self.client_secret,
                token_endpoint=self.token_endpoint,
                scope=self.scope,
            )
            return {
                "status": "ok",
                "auth_method": "technical_account",
                "token_preview": token[:8] + "...",
                "message": "IMS token obtained successfully",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _fetch_schemas(self, session_token: str) -> list[dict[str, str]]:
        envelope = f"""<?xml version='1.0' encoding='UTF-8'?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV='http://schemas.xmlsoap.org/soap/envelope/'>
  <SOAP-ENV:Body>
    <ExecuteQuery xmlns='urn:xtk:queryDef'>
      <sessiontoken>{session_token}</sessiontoken>
      <entity>
        <queryDef schema='xtk:schema' operation='select' lineCount='9999'>
          <select>
            <node expr='@name'/>
            <node expr='@namespace'/>
            <node expr='@label'/>
            <node expr='@pkSequence'/>
          </select>
        </queryDef>
      </entity>
    </ExecuteQuery>
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>"""

        resp = httpx.post(
            self.soap_endpoint,
            content=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": "xtk:queryDef#ExecuteQuery",
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Schema fetch failed: {resp.status_code}")

        root = ET.fromstring(resp.text)
        schemas = []
        for el in root.iter("schema"):
            name = el.get("name", "")
            namespace = el.get("namespace", "")
            if not name or not namespace:
                continue
            schemas.append({
                "name": f"{namespace}:{name}",
                "namespace": namespace,
                "label": el.get("label", name),
                "primary_key": el.get("pkSequence", ""),
            })
        return schemas
```

- [ ] **Step 4: Run all adapter tests**

```bash
cd backend
pytest tests/test_acc_adapter.py -v
```

Expected: all PASSED (including the 3 original tests + 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/acc/adapter.py backend/tests/test_acc_adapter.py
git commit -m "feat: ACCAdapter — extract _logon(), add get_schemas() via raw SOAP"
```

---

## Task 2: Add `GET /projects/:id/source/schemas` route

**Files:**
- Modify: `backend/app/api/source.py`
- Modify: `backend/tests/test_source.py`

- [ ] **Step 1: Add failing test**

Open `backend/tests/test_source.py` and append:

```python
def test_get_schemas_no_config(client, project_id):
    resp = client.get(f"/api/projects/{project_id}/source/schemas")
    assert resp.status_code == 400
    assert "Source config" in resp.json()["detail"]


def test_get_schemas_no_credentials(client, project_id):
    client.put(f"/api/projects/{project_id}/source", json={"base_url": "http://localhost:8080"})
    resp = client.get(f"/api/projects/{project_id}/source/schemas")
    assert resp.status_code == 400
    assert "credentials" in resp.json()["detail"]


def test_get_schemas_calls_adapter(client, project_id):
    from unittest.mock import patch, MagicMock
    client.put(f"/api/projects/{project_id}/source", json={"base_url": "http://localhost:8080"})
    client.put(f"/api/projects/{project_id}/source/credentials", json={
        "auth_method": "session_token",
        "operator_login": "admin",
        "operator_password": "secret",
    })

    mock_schemas = [
        {"name": "nms:recipient", "namespace": "nms", "label": "Recipients", "primary_key": "iRecipientId"}
    ]

    with patch("app.api.source.ACCAdapter") as MockAdapter:
        MockAdapter.return_value.get_schemas.return_value = mock_schemas
        resp = client.get(f"/api/projects/{project_id}/source/schemas")

    assert resp.status_code == 200
    data = resp.json()
    assert "schemas" in data
    assert data["schemas"] == mock_schemas
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_source.py::test_get_schemas_no_config tests/test_source.py::test_get_schemas_no_credentials tests/test_source.py::test_get_schemas_calls_adapter -v
```

Expected: FAILED — route does not exist yet (404 responses)

- [ ] **Step 3: Add route to `backend/app/api/source.py`**

Append this route at the end of the file:

```python
@router.get("/projects/{project_id}/source/schemas")
def get_source_schemas(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(SourceConfig).filter(SourceConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=400, detail="Source config not saved yet")
    cred = db.query(SourceCredentials).filter(SourceCredentials.source_config_id == config.id).first()
    if not cred:
        raise HTTPException(status_code=400, detail="Source credentials not saved yet")

    adapter_config = {
        "auth_method": cred.auth_method,
        "base_url": config.base_url,
        "operator_login": cred.operator_login,
        "operator_password": decrypt_value(cred.operator_password_enc) if cred.operator_password_enc else "",
    }
    adapter = ACCAdapter(adapter_config)
    schemas = adapter.get_schemas()
    return {"schemas": schemas}
```

- [ ] **Step 4: Run all source tests**

```bash
cd backend
pytest tests/test_source.py -v
```

Expected: all PASSED

- [ ] **Step 5: Run full test suite**

```bash
cd backend
pytest tests/ -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/source.py backend/tests/test_source.py
git commit -m "feat: GET /projects/:id/source/schemas endpoint"
```

---

## Task 3: Frontend — setup (main.tsx, App.tsx, context, API, components)

**Files:**
- Modify: `frontend/src/main.tsx`
- Replace: `frontend/src/App.tsx`
- Create: `frontend/src/context/ConnectionContext.tsx`
- Create: `frontend/src/api/sourceApi.ts`
- Create: `frontend/src/components/FormField.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`

- [ ] **Step 1: Check vite.config.ts has API proxy**

Read `frontend/vite.config.ts`. It must contain:

```ts
server: {
  proxy: {
    '/api': 'http://localhost:8000',
  },
},
```

If it does not, replace the file with:

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

- [ ] **Step 2: Check Tailwind directives exist in `frontend/src/index.css`**

Read `frontend/src/index.css`. The first three lines must be:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

If they are not present, prepend them to the file.

- [ ] **Step 3: Replace `frontend/src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
)
```

- [ ] **Step 4: Create `frontend/src/context/ConnectionContext.tsx`**

```tsx
import { createContext, useContext, useState } from 'react'

export interface Schema {
  name: string
  namespace: string
  label: string
  primary_key: string
}

interface ConnectionState {
  projectId: string | null
  schemas: Schema[]
  setProjectId: (id: string) => void
  setSchemas: (schemas: Schema[]) => void
}

const ConnectionContext = createContext<ConnectionState | null>(null)

export function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const [projectId, setProjectId] = useState<string | null>(null)
  const [schemas, setSchemas] = useState<Schema[]>([])

  return (
    <ConnectionContext.Provider value={{ projectId, schemas, setProjectId, setSchemas }}>
      {children}
    </ConnectionContext.Provider>
  )
}

export function useConnection(): ConnectionState {
  const ctx = useContext(ConnectionContext)
  if (!ctx) throw new Error('useConnection must be used inside ConnectionProvider')
  return ctx
}
```

- [ ] **Step 5: Create `frontend/src/api/sourceApi.ts`**

```ts
import type { Schema } from '../context/ConnectionContext'

const BASE = '/api'

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail ?? `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

export const createProject = (name: string) =>
  apiFetch<{ id: string }>('/projects', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })

export const saveSourceConfig = (pid: string, baseUrl: string) =>
  apiFetch(`/projects/${pid}/source`, {
    method: 'PUT',
    body: JSON.stringify({ base_url: baseUrl }),
  })

export const saveCredentials = (pid: string, login: string, password: string) =>
  apiFetch(`/projects/${pid}/source/credentials`, {
    method: 'PUT',
    body: JSON.stringify({
      auth_method: 'session_token',
      operator_login: login,
      operator_password: password,
    }),
  })

export const testConnection = (pid: string) =>
  apiFetch<{ status: string; message: string }>(`/projects/${pid}/source/test`, {
    method: 'POST',
  })

export const getSchemas = (pid: string) =>
  apiFetch<{ schemas: Schema[] }>(`/projects/${pid}/source/schemas`)
```

- [ ] **Step 6: Create `frontend/src/components/FormField.tsx`**

```tsx
interface FormFieldProps {
  label: string
  error?: string
  children: React.ReactNode
}

export function FormField({ label, error, children }: FormFieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-gray-700">{label}</label>
      {children}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
```

- [ ] **Step 7: Create `frontend/src/components/StatusBadge.tsx`**

```tsx
export type BadgeStatus = 'idle' | 'loading' | 'ok' | 'error'

interface StatusBadgeProps {
  status: BadgeStatus
  message?: string
}

const styles: Record<BadgeStatus, string> = {
  idle: 'bg-gray-100 text-gray-500',
  loading: 'bg-blue-100 text-blue-700',
  ok: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
}

const labels: Record<BadgeStatus, string> = {
  idle: 'Not tested',
  loading: 'Connecting…',
  ok: '✓ Connected',
  error: '✗ Failed',
}

export function StatusBadge({ status, message }: StatusBadgeProps) {
  return (
    <div className={`rounded-md px-3 py-2 text-sm ${styles[status]}`}>
      <span className="font-semibold">{labels[status]}</span>
      {message && <span className="ml-2 text-xs">{message}</span>}
    </div>
  )
}
```

- [ ] **Step 8: Replace `frontend/src/App.tsx`**

```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { ConnectionProvider } from './context/ConnectionContext'
import { ConnectPage } from './pages/ConnectPage'
import { NamespacePage } from './pages/NamespacePage'
import { SchemaViewPage } from './pages/SchemaViewPage'

export default function App() {
  return (
    <ConnectionProvider>
      <div className="min-h-screen bg-gray-50">
        <Routes>
          <Route path="/" element={<ConnectPage />} />
          <Route path="/project/:id/namespaces" element={<NamespacePage />} />
          <Route path="/project/:id/schemas/:namespace" element={<SchemaViewPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </ConnectionProvider>
  )
}
```

- [ ] **Step 9: Commit**

```bash
git add frontend/src/main.tsx frontend/src/App.tsx frontend/src/context/ frontend/src/api/ frontend/src/components/
git commit -m "feat: frontend scaffold — context, API client, shared components"
```

---

## Task 4: Screen 1 — ConnectPage

**Files:**
- Create: `frontend/src/pages/ConnectPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/ConnectPage.tsx`**

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FormField } from '../components/FormField'
import { StatusBadge, type BadgeStatus } from '../components/StatusBadge'
import { useConnection } from '../context/ConnectionContext'
import {
  createProject,
  saveSourceConfig,
  saveCredentials,
  testConnection,
} from '../api/sourceApi'

interface FormState {
  projectName: string
  baseUrl: string
  login: string
  password: string
}

interface Errors {
  projectName?: string
  baseUrl?: string
  login?: string
  password?: string
}

function validate(form: FormState): Errors {
  const errors: Errors = {}
  if (!form.projectName.trim()) errors.projectName = 'Project name is required'
  if (!form.baseUrl.trim()) errors.baseUrl = 'Base URL is required'
  if (!form.login.trim()) errors.login = 'Login is required'
  if (!form.password.trim()) errors.password = 'Password is required'
  return errors
}

export function ConnectPage() {
  const navigate = useNavigate()
  const { setProjectId } = useConnection()

  const [form, setForm] = useState<FormState>({
    projectName: '',
    baseUrl: 'http://localhost:8080',
    login: '',
    password: '',
  })
  const [errors, setErrors] = useState<Errors>({})
  const [status, setStatus] = useState<BadgeStatus>('idle')
  const [statusMessage, setStatusMessage] = useState('')
  const [connectedProjectId, setConnectedProjectId] = useState<string | null>(null)

  function set(field: keyof FormState) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const errs = validate(form)
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }
    setErrors({})
    setStatus('loading')
    setStatusMessage('')

    try {
      const project = await createProject(form.projectName)
      await saveSourceConfig(project.id, form.baseUrl)
      await saveCredentials(project.id, form.login, form.password)
      const result = await testConnection(project.id)

      if (result.status === 'ok') {
        setProjectId(project.id)
        setConnectedProjectId(project.id)
        setStatus('ok')
        setStatusMessage(result.message)
      } else {
        setStatus('error')
        setStatusMessage(result.message)
      }
    } catch (err: unknown) {
      setStatus('error')
      setStatusMessage(err instanceof Error ? err.message : 'Unknown error')
    }
  }

  const inputClass =
    'rounded-md border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl bg-white p-8 shadow-sm border border-gray-200">
        <h1 className="mb-1 text-xl font-semibold text-gray-900">Connect to ACC</h1>
        <p className="mb-6 text-sm text-gray-500">
          Enter your Adobe Campaign Classic credentials.
        </p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FormField label="Project Name" error={errors.projectName}>
            <input
              className={inputClass}
              value={form.projectName}
              onChange={set('projectName')}
              placeholder="My Migration Project"
            />
          </FormField>

          <FormField label="Base URL" error={errors.baseUrl}>
            <input
              className={inputClass}
              value={form.baseUrl}
              onChange={set('baseUrl')}
              placeholder="http://localhost:8080"
            />
            {form.baseUrl && (
              <p className="text-xs text-gray-400">
                SOAP: {form.baseUrl.replace(/\/$/, '')}/nl/jsp/soaprouter.jsp
              </p>
            )}
          </FormField>

          <FormField label="Operator Login" error={errors.login}>
            <input
              className={inputClass}
              value={form.login}
              onChange={set('login')}
              placeholder="admin"
              autoComplete="username"
            />
          </FormField>

          <FormField label="Password" error={errors.password}>
            <input
              className={inputClass}
              type="password"
              value={form.password}
              onChange={set('password')}
              autoComplete="current-password"
            />
          </FormField>

          <button
            type="submit"
            disabled={status === 'loading'}
            className="mt-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {status === 'loading' ? 'Connecting…' : 'Connect'}
          </button>
        </form>

        {status !== 'idle' && (
          <div className="mt-4">
            <StatusBadge status={status} message={statusMessage} />
          </div>
        )}

        {status === 'ok' && connectedProjectId && (
          <button
            onClick={() => navigate(`/project/${connectedProjectId}/namespaces`)}
            className="mt-4 w-full rounded-md border border-blue-600 px-4 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50"
          >
            Browse Schemas →
          </button>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/ConnectPage.tsx
git commit -m "feat: ConnectPage — project create, save config/creds, test connection"
```

---

## Task 5: Screen 2 — NamespacePage

**Files:**
- Create: `frontend/src/pages/NamespacePage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/NamespacePage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useConnection } from '../context/ConnectionContext'
import { getSchemas } from '../api/sourceApi'

export function NamespacePage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { schemas, setSchemas } = useConnection()

  const [loading, setLoading] = useState(schemas.length === 0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id || schemas.length > 0) return
    setLoading(true)
    getSchemas(id)
      .then((data) => {
        setSchemas(data.schemas)
        setLoading(false)
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Failed to load schemas')
        setLoading(false)
      })
  }, [id])

  const namespaces = [...new Set(schemas.map((s) => s.namespace))].sort()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-gray-500">Loading schemas…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="rounded-md bg-red-50 p-4 text-sm text-red-700">
          <strong>Error:</strong> {error}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl p-8">
      <button
        onClick={() => navigate('/')}
        className="mb-6 text-sm text-gray-500 hover:text-gray-700"
      >
        ← Back
      </button>
      <h1 className="mb-1 text-xl font-semibold text-gray-900">Select a Namespace</h1>
      <p className="mb-6 text-sm text-gray-500">
        {schemas.length} schemas across {namespaces.length} namespaces
      </p>

      <div className="grid grid-cols-3 gap-3">
        {namespaces.map((ns) => {
          const count = schemas.filter((s) => s.namespace === ns).length
          return (
            <button
              key={ns}
              onClick={() => navigate(`/project/${id}/schemas/${ns}`)}
              className="rounded-lg border border-gray-200 bg-white p-4 text-left hover:border-blue-400 hover:shadow-sm transition-all"
            >
              <p className="font-mono text-base font-semibold text-gray-900">{ns}</p>
              <p className="mt-1 text-xs text-gray-400">{count} schema{count !== 1 ? 's' : ''}</p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/NamespacePage.tsx
git commit -m "feat: NamespacePage — fetch schemas, group by namespace, render tiles"
```

---

## Task 6: Screen 3 — SchemaViewPage

**Files:**
- Create: `frontend/src/pages/SchemaViewPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/SchemaViewPage.tsx`**

```tsx
import { useNavigate, useParams } from 'react-router-dom'
import { useConnection } from '../context/ConnectionContext'

export function SchemaViewPage() {
  const { id, namespace } = useParams<{ id: string; namespace: string }>()
  const navigate = useNavigate()
  const { schemas } = useConnection()

  const filtered = schemas.filter((s) => s.namespace === namespace)

  return (
    <div className="mx-auto max-w-4xl p-8">
      <button
        onClick={() => navigate(`/project/${id}/namespaces`)}
        className="mb-6 text-sm text-gray-500 hover:text-gray-700"
      >
        ← Namespaces
      </button>

      <h1 className="mb-1 text-xl font-semibold text-gray-900">
        <span className="font-mono">{namespace}</span> schemas
      </h1>
      <p className="mb-6 text-sm text-gray-500">{filtered.length} schemas</p>

      {filtered.length === 0 ? (
        <p className="text-sm text-gray-400">No schemas found for this namespace.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 font-medium text-gray-600">Schema Name</th>
                <th className="px-4 py-3 font-medium text-gray-600">Label</th>
                <th className="px-4 py-3 font-medium text-gray-600">Primary Key</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((schema) => (
                <tr key={schema.name} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-mono text-gray-900">{schema.name}</td>
                  <td className="px-4 py-3 text-gray-700">{schema.label || '—'}</td>
                  <td className="px-4 py-3 font-mono text-gray-500 text-xs">
                    {schema.primary_key || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/SchemaViewPage.tsx
git commit -m "feat: SchemaViewPage — filter schemas by namespace, render table"
```

---

## Task 7: Smoke test — run frontend + backend together

- [ ] **Step 1: Start backend**

```bash
cd backend
pip install -r requirements.txt   # if not already installed
DATABASE_URL=sqlite:////tmp/acc2ajo-dev.db ENCRYPTION_KEY=devkey12345678901234567890123 uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Expected: `Uvicorn running on http://0.0.0.0:8000`

- [ ] **Step 2: Start frontend (separate terminal)**

```bash
cd frontend
npm install   # if not already installed
npm run dev
```

Expected: `Local: http://localhost:5173/`

- [ ] **Step 3: Open browser at `http://localhost:5173`**

Expected: ConnectPage renders with 4 fields (Project Name, Base URL, Operator Login, Password). Base URL pre-filled with `http://localhost:8080`. No console errors.

- [ ] **Step 4: Submit the form with test credentials**

Fill in:
- Project Name: `Test`
- Base URL: `http://localhost:8080` (your ACC instance)
- Operator Login: your ACC operator login
- Password: your ACC password

Click **Connect**.

Expected: StatusBadge transitions to "Connecting…" then either "✓ Connected" (if ACC is reachable) or "✗ Failed" with the SOAP error message. On success, "Browse Schemas →" button appears.

- [ ] **Step 5: Navigate to namespaces**

Click **Browse Schemas →**.

Expected: NamespacePage shows namespace tiles (e.g. `nms`, `xtk`, `nl`). Total schema count shown.

- [ ] **Step 6: Click a namespace**

Click e.g. `nms`.

Expected: SchemaViewPage shows table with schema name, label, and primary key columns. Rows populate from the SOAP response.

- [ ] **Step 7: Final commit if any adjustments were made**

```bash
git add -A
git commit -m "fix: smoke test adjustments"
```

---

## Self-Review

**Spec coverage:**
- ✓ Screen 1: Connection form with project name, base URL, login, password
- ✓ Sequential: create project → save config → save credentials → test connection
- ✓ Screen 2: Namespace tiles from schema list
- ✓ Screen 3: Schema table filtered by namespace
- ✓ Passwords encrypted at rest via existing `encrypt_value`
- ✓ Passwords never returned to frontend
- ✓ Credentials not stored in context (only projectId + schemas)
- ✓ SOAP endpoint auto-derived from base URL
- ✓ Default base URL `http://localhost:8080`

**Placeholder scan:** None found — all steps have complete code.

**Type consistency:**
- `Schema` interface defined in `ConnectionContext.tsx`, imported in `sourceApi.ts` and used in all pages ✓
- `BadgeStatus` type exported from `StatusBadge.tsx`, imported in `ConnectPage.tsx` ✓
- `useConnection()` returns `ConnectionState` with `projectId`, `schemas`, `setProjectId`, `setSchemas` — all used correctly across pages ✓
- `apiFetch` used only inside `sourceApi.ts`; pages import named functions ✓
