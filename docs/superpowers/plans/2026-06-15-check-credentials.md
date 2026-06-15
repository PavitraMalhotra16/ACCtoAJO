# Check Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `/check-credentials` page that verifies ACC OAuth credentials (IMS token fetch → Campaign REST probe) and auto-creates a draft Project on success, then navigates to schema extraction.

**Architecture:** New `POST /api/check-credentials` endpoint runs three sequential steps — IMS token, Campaign REST probe, DB write — and returns a `project_id` only on full success. Frontend is a single standalone page with a profiles dropdown (pre-fill from existing projects), a 5-field form, and inline step-by-step status. Routing is wired through react-router-dom v7 (already installed, not yet configured).

**Tech Stack:** FastAPI, SQLAlchemy (SQLite), httpx, cryptography · React 19, react-router-dom v7, TailwindCSS · pytest + TestClient with in-memory SQLite

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/app/api/check_credentials.py` | POST /api/check-credentials · GET /api/check-credentials/profiles |
| Modify | `backend/app/main.py` | Register check_credentials router |
| Create | `backend/tests/test_check_credentials.py` | All backend tests for the new endpoints |
| Modify | `frontend/src/main.tsx` | Wrap app in BrowserRouter |
| Modify | `frontend/src/App.tsx` | Replace placeholder with Routes; add /check-credentials route |
| Create | `frontend/src/pages/CheckCredentials.tsx` | Full standalone page (form, profiles dropdown, status, redirect) |
| Create | `frontend/src/api/checkCredentials.ts` | Typed fetch wrappers for the two new endpoints |

---

## Task 1: Backend skeleton + router registration

**Files:**
- Create: `backend/app/api/check_credentials.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_check_credentials.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_check_credentials.py`:

```python
def test_check_credentials_missing_fields(client):
    resp = client.post("/api/check-credentials", json={})
    assert resp.status_code == 422  # pydantic validation error
```

- [ ] **Step 2: Run test — expect FAIL (404, route doesn't exist yet)**

```
cd backend
pytest tests/test_check_credentials.py::test_check_credentials_missing_fields -v
```

Expected: FAIL — `assert 404 == 422` (route not registered yet)

- [ ] **Step 3: Create the endpoint skeleton**

Create `backend/app/api/check_credentials.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter()

class CheckCredentialsRequest(BaseModel):
    acc_url: str
    client_id: str
    client_secret: str
    ims_org_id: str
    technical_account_id: str = ""

@router.post("/check-credentials")
def check_credentials(payload: CheckCredentialsRequest, db: Session = Depends(get_db)):
    return {"status": "ok"}

@router.get("/check-credentials/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return []
```

- [ ] **Step 4: Register the router**

Edit `backend/app/main.py` — add two lines:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import projects, source, destination, check_credentials  # add check_credentials

app = FastAPI(title="ACC2AJO Migration Tool")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")
app.include_router(source.router, prefix="/api")
app.include_router(destination.router, prefix="/api")
app.include_router(check_credentials.router, prefix="/api")  # add this line
```

- [ ] **Step 5: Run test — expect PASS**

```
cd backend
pytest tests/test_check_credentials.py::test_check_credentials_missing_fields -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```
git add backend/app/api/check_credentials.py backend/app/main.py backend/tests/test_check_credentials.py
git commit -m "feat: add check-credentials endpoint skeleton"
```

---

## Task 2: IMS token fetch step

**Files:**
- Modify: `backend/app/api/check_credentials.py`
- Modify: `backend/tests/test_check_credentials.py`

- [ ] **Step 1: Add failing tests for IMS step**

Append to `backend/tests/test_check_credentials.py`:

```python
from unittest.mock import patch, MagicMock

VALID_PAYLOAD = {
    "acc_url": "https://acc.example.com",
    "client_id": "my-client-id",
    "client_secret": "my-secret",
    "ims_org_id": "AABBCC@AdobeOrg",
    "technical_account_id": "tech@techacct.adobe.com",
}

def _ims_ok():
    """Returns a mock that makes IMS token fetch succeed."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "fake-token-abc123", "expires_in": 3600}
    return mock_resp

def _ims_fail():
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid_client"
    return mock_resp

def test_ims_token_failure_returns_400(client):
    with patch("httpx.post", return_value=_ims_fail()):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "IMS token request failed" in resp.json()["detail"]

def test_no_project_created_on_ims_failure(client):
    from tests.conftest import TestingSession
    from app.models.project import Project
    with patch("httpx.post", return_value=_ims_fail()):
        client.post("/api/check-credentials", json=VALID_PAYLOAD)
    db = TestingSession()
    count = db.query(Project).count()
    db.close()
    assert count == 0
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend
pytest tests/test_check_credentials.py::test_ims_token_failure_returns_400 tests/test_check_credentials.py::test_no_project_created_on_ims_failure -v
```

Expected: FAIL — endpoint currently returns 200 for all inputs

- [ ] **Step 3: Implement IMS token fetch in endpoint**

Replace the `check_credentials` function body in `backend/app/api/check_credentials.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
from app.db.session import get_db

router = APIRouter()

IMS_TOKEN_ENDPOINT = "https://ims-na1.adobelogin.com/ims/token/v3"
IMS_SCOPE = "openid,AdobeID,campaign"

class CheckCredentialsRequest(BaseModel):
    acc_url: str
    client_id: str
    client_secret: str
    ims_org_id: str
    technical_account_id: str = ""

def _fetch_ims_token(client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        IMS_TOKEN_ENDPOINT,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": IMS_SCOPE,
        },
        timeout=15.0,
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"IMS token request failed — check Client ID and Client Secret ({resp.text[:120]})",
        )
    return resp.json()["access_token"]

@router.post("/check-credentials")
def check_credentials(payload: CheckCredentialsRequest, db: Session = Depends(get_db)):
    token = _fetch_ims_token(payload.client_id, payload.client_secret)
    return {"status": "ok", "token_preview": token[:8] + "..."}

@router.get("/check-credentials/profiles")
def list_profiles(db: Session = Depends(get_db)):
    return []
```

- [ ] **Step 4: Run tests — expect PASS**

```
cd backend
pytest tests/test_check_credentials.py::test_ims_token_failure_returns_400 tests/test_check_credentials.py::test_no_project_created_on_ims_failure -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add backend/app/api/check_credentials.py backend/tests/test_check_credentials.py
git commit -m "feat: IMS token fetch step in check-credentials endpoint"
```

---

## Task 3: Campaign REST probe step

**Files:**
- Modify: `backend/app/api/check_credentials.py`
- Modify: `backend/tests/test_check_credentials.py`

- [ ] **Step 1: Add failing tests for Campaign probe**

Append to `backend/tests/test_check_credentials.py`:

```python
def _campaign_ok():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": [], "count": {"value": 0}}
    return mock_resp

def _campaign_status(status_code: int):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = f"error {status_code}"
    return mock_resp

def test_campaign_401_returns_400(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_status(401)):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "product profile" in resp.json()["detail"]

def test_campaign_403_returns_400(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_status(403)):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "Developer Console" in resp.json()["detail"]

def test_campaign_unknown_error_returns_400(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_status(500)):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "500" in resp.json()["detail"]

def test_campaign_timeout_returns_400(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 400
    assert "Could not reach" in resp.json()["detail"]
```

Also add `import httpx` at the top of the test file (after the existing imports).

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend
pytest tests/test_check_credentials.py::test_campaign_401_returns_400 tests/test_check_credentials.py::test_campaign_403_returns_400 -v
```

Expected: FAIL — endpoint returns 200 after IMS success regardless of Campaign response

- [ ] **Step 3: Add `_probe_campaign` function to `check_credentials.py`**

Add this function after `_fetch_ims_token` and update `check_credentials`:

```python
def _probe_campaign(acc_url: str, client_id: str, token: str) -> None:
    url = acc_url.rstrip("/") + "/rest/profileAndServices/profile?_lineCount=1"
    try:
        resp = httpx.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Api-Key": client_id,
            },
            timeout=15.0,
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=400,
            detail="Could not reach Campaign instance — check the URL and network/VPN access",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not reach Campaign instance — check the URL and network/VPN access ({exc})",
        )

    if resp.status_code == 200:
        return
    if resp.status_code == 401:
        raise HTTPException(
            status_code=400,
            detail="Campaign rejected the token — technical account may not be assigned a product profile",
        )
    if resp.status_code == 403:
        raise HTTPException(
            status_code=400,
            detail="Campaign denied access — confirm the Campaign API is added to your Developer Console project",
        )
    raise HTTPException(
        status_code=400,
        detail=f"Campaign returned {resp.status_code}: {resp.text[:120]}",
    )

@router.post("/check-credentials")
def check_credentials(payload: CheckCredentialsRequest, db: Session = Depends(get_db)):
    token = _fetch_ims_token(payload.client_id, payload.client_secret)
    _probe_campaign(payload.acc_url, payload.client_id, token)
    return {"status": "ok"}
```

- [ ] **Step 4: Run all campaign probe tests — expect PASS**

```
cd backend
pytest tests/test_check_credentials.py::test_campaign_401_returns_400 tests/test_check_credentials.py::test_campaign_403_returns_400 tests/test_check_credentials.py::test_campaign_unknown_error_returns_400 tests/test_check_credentials.py::test_campaign_timeout_returns_400 -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```
git add backend/app/api/check_credentials.py backend/tests/test_check_credentials.py
git commit -m "feat: Campaign REST probe step in check-credentials endpoint"
```

---

## Task 4: Auto-create project on success

**Files:**
- Modify: `backend/app/api/check_credentials.py`
- Modify: `backend/tests/test_check_credentials.py`

- [ ] **Step 1: Add failing tests for project creation**

Append to `backend/tests/test_check_credentials.py`:

```python
from app.models.project import Project
from app.models.source import SourceConfig, SourceCredentials

def test_success_creates_project(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_ok()):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "project_id" in body
    assert body["project_created"] is True

def test_success_persists_records(client):
    from tests.conftest import TestingSession
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_ok()):
        resp = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    project_id = resp.json()["project_id"]
    db = TestingSession()
    project = db.query(Project).filter(Project.id == project_id).first()
    assert project is not None
    assert project.status == "configured"
    config = db.query(SourceConfig).filter(SourceConfig.project_id == project_id).first()
    assert config is not None
    assert config.rest_api_enabled == "yes"
    cred = db.query(SourceCredentials).filter(SourceCredentials.source_config_id == config.id).first()
    assert cred is not None
    assert cred.auth_method == "technical_account"
    assert cred.client_id == "my-client-id"
    assert cred.client_secret_enc != b"my-secret"  # must be encrypted
    assert cred.ims_org_id == "AABBCC@AdobeOrg"
    db.close()
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend
pytest tests/test_check_credentials.py::test_success_creates_project tests/test_check_credentials.py::test_success_persists_records -v
```

Expected: FAIL — endpoint returns `{"status": "ok"}` with no `project_id`

- [ ] **Step 3: Add `_create_project` helper and wire it into the endpoint**

Add imports at top of `backend/app/api/check_credentials.py`:

```python
from app.models.project import Project
from app.models.source import SourceConfig, SourceCredentials
from app.core.security import encrypt_value
```

Add helper function after `_probe_campaign`:

```python
def _create_project(payload: CheckCredentialsRequest, db: Session) -> tuple[str, bool]:
    """Create Project + SourceConfig + SourceCredentials. Returns (project_id, created)."""
    # Check for existing project by client_id + ims_org_id
    existing_cred = (
        db.query(SourceCredentials)
        .filter(
            SourceCredentials.client_id == payload.client_id,
            SourceCredentials.ims_org_id == payload.ims_org_id,
        )
        .first()
    )
    if existing_cred:
        existing_cred.client_secret_enc = encrypt_value(payload.client_secret)
        if payload.technical_account_id:
            existing_cred.technical_account_id = payload.technical_account_id
        config = db.query(SourceConfig).filter(
            SourceConfig.id == existing_cred.source_config_id
        ).first()
        db.commit()
        return config.project_id, False

    project = Project(
        name=f"ACC – {payload.ims_org_id}",
        status="configured",
    )
    db.add(project)
    db.flush()  # get project.id

    config = SourceConfig(
        project_id=project.id,
        base_url=payload.acc_url.rstrip("/"),
        soap_endpoint=payload.acc_url.rstrip("/") + "/nl/jsp/soaprouter.jsp",
        rest_api_enabled="yes",
    )
    db.add(config)
    db.flush()  # get config.id

    cred = SourceCredentials(
        source_config_id=config.id,
        auth_method="technical_account",
        client_id=payload.client_id,
        client_secret_enc=encrypt_value(payload.client_secret),
        ims_org_id=payload.ims_org_id,
        technical_account_id=payload.technical_account_id,
        scope=IMS_SCOPE,
    )
    db.add(cred)
    db.commit()
    return project.id, True
```

Update the `check_credentials` endpoint:

```python
@router.post("/check-credentials")
def check_credentials(payload: CheckCredentialsRequest, db: Session = Depends(get_db)):
    token = _fetch_ims_token(payload.client_id, payload.client_secret)
    _probe_campaign(payload.acc_url, payload.client_id, token)
    project_id, created = _create_project(payload, db)
    return {
        "status": "ok",
        "project_id": project_id,
        "project_created": created,
        "message": "Connection established · Login info stored",
    }
```

- [ ] **Step 4: Run tests — expect PASS**

```
cd backend
pytest tests/test_check_credentials.py::test_success_creates_project tests/test_check_credentials.py::test_success_persists_records -v
```

Expected: PASS

- [ ] **Step 5: Run all check-credentials tests to confirm no regressions**

```
cd backend
pytest tests/test_check_credentials.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```
git add backend/app/api/check_credentials.py backend/tests/test_check_credentials.py
git commit -m "feat: auto-create project on successful credential check"
```

---

## Task 5: Idempotency + profiles endpoint

**Files:**
- Modify: `backend/app/api/check_credentials.py`
- Modify: `backend/tests/test_check_credentials.py`

- [ ] **Step 1: Add failing tests**

Append to `backend/tests/test_check_credentials.py`:

```python
def test_idempotent_second_call_returns_same_project_id(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_ok()):
        resp1 = client.post("/api/check-credentials", json=VALID_PAYLOAD)
        resp2 = client.post("/api/check-credentials", json=VALID_PAYLOAD)
    assert resp1.json()["project_id"] == resp2.json()["project_id"]
    assert resp2.json()["project_created"] is False

def test_idempotent_does_not_create_duplicate_projects(client):
    from tests.conftest import TestingSession
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_ok()):
        client.post("/api/check-credentials", json=VALID_PAYLOAD)
        client.post("/api/check-credentials", json=VALID_PAYLOAD)
    db = TestingSession()
    count = db.query(Project).count()
    db.close()
    assert count == 1

def test_profiles_returns_saved_project(client):
    with patch("httpx.post", return_value=_ims_ok()), \
         patch("httpx.get", return_value=_campaign_ok()):
        client.post("/api/check-credentials", json=VALID_PAYLOAD)
    resp = client.get("/api/check-credentials/profiles")
    assert resp.status_code == 200
    profiles = resp.json()
    assert len(profiles) == 1
    assert profiles[0]["ims_org_id"] == "AABBCC@AdobeOrg"
    assert profiles[0]["client_id"] == "my-client-id"
    assert "project_id" in profiles[0]
    assert "project_name" in profiles[0]
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend
pytest tests/test_check_credentials.py::test_idempotent_second_call_returns_same_project_id tests/test_check_credentials.py::test_profiles_returns_saved_project -v
```

Expected: FAIL — idempotency and profiles not yet implemented

Note: `_create_project` already has the idempotency logic (checks existing cred) from Task 4, so idempotency tests may pass. Profiles test will fail.

- [ ] **Step 3: Implement the profiles endpoint**

Replace the `list_profiles` stub in `backend/app/api/check_credentials.py`:

```python
@router.get("/check-credentials/profiles")
def list_profiles(db: Session = Depends(get_db)):
    creds = (
        db.query(SourceCredentials)
        .filter(SourceCredentials.auth_method == "technical_account")
        .filter(SourceCredentials.client_id != "")
        .all()
    )
    result = []
    for cred in creds:
        config = db.query(SourceConfig).filter(SourceConfig.id == cred.source_config_id).first()
        if not config:
            continue
        project = db.query(Project).filter(Project.id == config.project_id).first()
        if not project:
            continue
        result.append({
            "project_id": project.id,
            "project_name": project.name,
            "ims_org_id": cred.ims_org_id,
            "client_id": cred.client_id,
            "acc_url": config.base_url,
            "technical_account_id": cred.technical_account_id,
        })
    return result
```

- [ ] **Step 4: Run all tests — expect PASS**

```
cd backend
pytest tests/test_check_credentials.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite to confirm no regressions**

```
cd backend
pytest -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```
git add backend/app/api/check_credentials.py backend/tests/test_check_credentials.py
git commit -m "feat: profiles endpoint + idempotency for check-credentials"
```

---

## Task 6: Frontend routing setup

**Files:**
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/App.tsx`

react-router-dom v7 is already in `package.json`. No install needed.

- [ ] **Step 1: Wrap app in BrowserRouter**

Replace `frontend/src/main.tsx` entirely:

```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
```

- [ ] **Step 2: Replace App.tsx with a Routes shell**

Replace `frontend/src/App.tsx` entirely:

```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import CheckCredentials from './pages/CheckCredentials'

export default function App() {
  return (
    <Routes>
      <Route path="/check-credentials" element={<CheckCredentials />} />
      <Route path="*" element={<Navigate to="/check-credentials" replace />} />
    </Routes>
  )
}
```

- [ ] **Step 3: Create a minimal placeholder page so the import resolves**

Create `frontend/src/pages/CheckCredentials.tsx`:

```tsx
export default function CheckCredentials() {
  return <div className="p-8 text-white">Check Credentials — coming in Task 8</div>
}
```

- [ ] **Step 4: Verify the dev server starts without errors**

```
cd frontend
npm run dev
```

Open `http://localhost:5173/check-credentials` — expect the placeholder text. No console errors. Ctrl+C to stop.

- [ ] **Step 5: Commit**

```
git add frontend/src/main.tsx frontend/src/App.tsx frontend/src/pages/CheckCredentials.tsx
git commit -m "feat: wire react-router-dom routing, add /check-credentials route"
```

---

## Task 7: Frontend API client

**Files:**
- Create: `frontend/src/api/checkCredentials.ts`

- [ ] **Step 1: Create the API module**

Create `frontend/src/api/checkCredentials.ts`:

```typescript
const BASE = 'http://localhost:8000/api'

export interface CheckCredentialsPayload {
  acc_url: string
  client_id: string
  client_secret: string
  ims_org_id: string
  technical_account_id?: string
}

export interface CheckCredentialsResult {
  status: 'ok'
  project_id: string
  project_created: boolean
  message: string
}

export interface Profile {
  project_id: string
  project_name: string
  ims_org_id: string
  client_id: string
  acc_url: string
  technical_account_id: string
}

export async function checkCredentials(payload: CheckCredentialsPayload): Promise<CheckCredentialsResult> {
  const resp = await fetch(`${BASE}/check-credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const body = await resp.json()
  if (!resp.ok) {
    throw new Error(body.detail ?? 'Unknown error')
  }
  return body as CheckCredentialsResult
}

export async function fetchProfiles(): Promise<Profile[]> {
  const resp = await fetch(`${BASE}/check-credentials/profiles`)
  if (!resp.ok) throw new Error('Failed to load saved profiles')
  return resp.json()
}
```

- [ ] **Step 2: Commit**

```
git add frontend/src/api/checkCredentials.ts
git commit -m "feat: typed API client for check-credentials endpoints"
```

---

## Task 8: Full CheckCredentials page

**Files:**
- Modify: `frontend/src/pages/CheckCredentials.tsx`

Replace the placeholder from Task 6 with the full implementation.

- [ ] **Step 1: Write the full page**

Replace `frontend/src/pages/CheckCredentials.tsx` entirely:

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  checkCredentials,
  fetchProfiles,
  type CheckCredentialsPayload,
  type Profile,
} from '../api/checkCredentials'

type Step =
  | { id: 'idle' }
  | { id: 'ims'; label: 'Fetching IMS token...' }
  | { id: 'campaign'; label: 'Probing Campaign REST endpoint...' }
  | { id: 'done'; projectId: string }
  | { id: 'error'; message: string }

const EMPTY_FORM: CheckCredentialsPayload = {
  acc_url: '',
  client_id: '',
  client_secret: '',
  ims_org_id: '',
  technical_account_id: '',
}

export default function CheckCredentials() {
  const navigate = useNavigate()
  const [form, setForm] = useState<CheckCredentialsPayload>(EMPTY_FORM)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [step, setStep] = useState<Step>({ id: 'idle' })

  useEffect(() => {
    fetchProfiles().then(setProfiles).catch(() => {/* non-fatal */})
  }, [])

  function loadProfile(projectId: string) {
    const p = profiles.find(pr => pr.project_id === projectId)
    if (!p) return
    setForm({
      acc_url: p.acc_url,
      client_id: p.client_id,
      client_secret: '',          // never pre-fill secrets
      ims_org_id: p.ims_org_id,
      technical_account_id: p.technical_account_id,
    })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setStep({ id: 'ims', label: 'Fetching IMS token...' })
    try {
      // Step 1 indicator — the real request is one call that does both steps server-side.
      // We show both indicators with a brief artificial pause so the user sees progress.
      await new Promise(r => setTimeout(r, 400))
      setStep({ id: 'campaign', label: 'Probing Campaign REST endpoint...' })
      const result = await checkCredentials(form)
      setStep({ id: 'done', projectId: result.project_id })
      setTimeout(() => navigate(`/projects/${result.project_id}/schemas`), 2000)
    } catch (err: unknown) {
      setStep({ id: 'error', message: err instanceof Error ? err.message : 'Unknown error' })
    }
  }

  const busy = step.id === 'ims' || step.id === 'campaign'
  const done = step.id === 'done'

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <h1 className="text-2xl font-semibold mb-1">Check Credentials</h1>
        <p className="text-gray-400 text-sm mb-6">
          Verify Adobe Campaign Classic API access before starting a migration project.
        </p>

        {profiles.length > 0 && (
          <div className="mb-5">
            <label className="block text-xs font-medium text-gray-400 mb-1">
              Load saved profile
            </label>
            <select
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm"
              defaultValue=""
              onChange={e => loadProfile(e.target.value)}
              disabled={busy || done}
            >
              <option value="">— select a saved profile —</option>
              {profiles.map(p => (
                <option key={p.project_id} value={p.project_id}>
                  {p.project_name} ({p.ims_org_id})
                </option>
              ))}
            </select>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <Field
            label="ACC Instance URL"
            placeholder="https://myinstance.campaign.adobe.com"
            value={form.acc_url}
            onChange={v => setForm(f => ({ ...f, acc_url: v }))}
            required
            disabled={busy || done}
          />
          <Field
            label="Client ID"
            placeholder="your-client-id"
            value={form.client_id}
            onChange={v => setForm(f => ({ ...f, client_id: v }))}
            required
            disabled={busy || done}
          />
          <Field
            label="Client Secret"
            placeholder="••••••••"
            type="password"
            value={form.client_secret}
            onChange={v => setForm(f => ({ ...f, client_secret: v }))}
            required
            disabled={busy || done}
          />
          <Field
            label="IMS Org ID"
            placeholder="XXXXXXXX@AdobeOrg"
            value={form.ims_org_id}
            onChange={v => setForm(f => ({ ...f, ims_org_id: v }))}
            required
            disabled={busy || done}
            hint="Must end with @AdobeOrg"
          />
          <Field
            label="Technical Account ID"
            placeholder="optional"
            value={form.technical_account_id ?? ''}
            onChange={v => setForm(f => ({ ...f, technical_account_id: v }))}
            disabled={busy || done}
          />

          <button
            type="submit"
            disabled={busy || done}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed rounded px-4 py-2 font-medium transition-colors"
          >
            {busy ? 'Checking...' : 'Check Connection'}
          </button>
        </form>

        <StatusPanel step={step} />
      </div>
    </div>
  )
}

function Field({
  label,
  placeholder,
  value,
  onChange,
  type = 'text',
  required = false,
  disabled = false,
  hint,
}: {
  label: string
  placeholder: string
  value: string
  onChange: (v: string) => void
  type?: string
  required?: boolean
  disabled?: boolean
  hint?: string
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-400 mb-1">
        {label}{required && <span className="text-red-400 ml-1">*</span>}
      </label>
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={e => onChange(e.target.value)}
        required={required}
        disabled={disabled}
        className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm disabled:opacity-50 focus:outline-none focus:border-blue-500"
      />
      {hint && <p className="text-xs text-gray-500 mt-1">{hint}</p>}
    </div>
  )
}

function StatusPanel({ step }: { step: Step }) {
  if (step.id === 'idle') return null

  const lines: { icon: string; text: string; done: boolean }[] = [
    {
      icon: step.id === 'idle' ? '○' : step.id === 'ims' ? '⏳' : '✅',
      text: 'Fetching IMS token...',
      done: step.id !== 'ims' && step.id !== 'idle',
    },
    {
      icon: step.id === 'campaign' ? '⏳' : step.id === 'done' ? '✅' : '○',
      text: 'Probing Campaign REST endpoint...',
      done: step.id === 'done',
    },
  ]

  return (
    <div className="mt-6 rounded border border-gray-700 bg-gray-900 p-4 text-sm space-y-2">
      {lines.map((l, i) => (
        <div key={i} className={`flex gap-2 ${l.done ? 'text-green-400' : 'text-gray-300'}`}>
          <span>{l.icon}</span>
          <span>{l.text}</span>
        </div>
      ))}

      {step.id === 'done' && (
        <>
          <div className="flex gap-2 text-green-400">
            <span>✅</span>
            <span>Connection established</span>
          </div>
          <div className="flex gap-2 text-green-400">
            <span>✅</span>
            <span>Login info stored · Project draft created</span>
          </div>
          <div className="flex gap-2 text-blue-400 pt-1">
            <span>→</span>
            <span>Redirecting to schema extraction in 2s…</span>
          </div>
        </>
      )}

      {step.id === 'error' && (
        <div className="rounded bg-red-950 border border-red-800 px-3 py-2 text-red-300 mt-2">
          {step.message}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Start the dev server and verify the page renders**

```
cd frontend
npm run dev
```

Open `http://localhost:5173/check-credentials`.

Verify:
- Form renders with 5 fields
- If the backend is running and has saved profiles, the dropdown appears
- Submit button is present and labeled "Check Connection"
- No console errors

Ctrl+C to stop.

- [ ] **Step 3: Run TypeScript compile check**

```
cd frontend
npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```
git add frontend/src/pages/CheckCredentials.tsx
git commit -m "feat: CheckCredentials page with form, profiles dropdown, step-by-step status, redirect"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| POST /api/check-credentials | Tasks 1–4 |
| IMS token fetch (step 1) | Task 2 |
| Campaign REST probe GET .../profile?_lineCount=1 (step 2) | Task 3 |
| 401 → "product profile" error message | Task 3 |
| 403 → "Developer Console" error message | Task 3 |
| Timeout/unreachable → "Could not reach" message | Task 3 |
| Auto-create Project + SourceConfig + SourceCredentials | Task 4 |
| client_secret encrypted at rest | Task 4 |
| Idempotency: same client_id+ims_org_id → update, not duplicate | Task 5 |
| GET /api/check-credentials/profiles | Task 5 |
| react-router-dom routing wired | Task 6 |
| Typed API client | Task 7 |
| Profiles dropdown pre-fills form | Task 8 |
| Step-by-step status (⏳ IMS → ⏳ Campaign → ✅ done) | Task 8 |
| Redirect to /projects/{id}/schemas after 2s | Task 8 |
| No DB writes on failure | Task 3 (HTTPException before DB step) + Task 4 test |

**Placeholder scan:** None found.

**Type consistency:**
- `CheckCredentialsPayload` defined in `checkCredentials.ts` Task 7, consumed in `CheckCredentials.tsx` Task 8. ✓
- `Profile` defined in Task 7, consumed in Task 8 `loadProfile`. ✓
- `_create_project` returns `tuple[str, bool]` in Task 4, destructured in `check_credentials` endpoint. ✓
- `Step` discriminated union covers all states used in `StatusPanel`. ✓
