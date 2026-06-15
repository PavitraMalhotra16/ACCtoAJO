# Source & Destination Configuration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete source (ACC) and destination (AJO/AEP) configuration screens with working backend — connection details, credentials (encrypted), and live connection tests for both sides.

**Architecture:** FastAPI backend with SQLAlchemy + SQLite stores configs and encrypted credentials; `services/acc/` and `services/aep/` contain the actual API adapters; `services/ims/` handles OAuth token fetch and caching. React+Vite frontend has tabbed configuration pages that call the backend and show live test results.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, Alembic, `cryptography` (Fernet), `zeep` (SOAP), `httpx`, React 18, Vite, TypeScript, TailwindCSS, React Router v6, Zustand.

---

## File Map

```
backend/
├── app/
│   ├── main.py                          # FastAPI app + CORS
│   ├── api/
│   │   ├── projects.py                  # GET/POST /api/projects
│   │   ├── source.py                    # GET/PUT source config, POST test
│   │   └── destination.py               # GET/PUT dest config, POST test/connect, POST test/capabilities
│   ├── models/
│   │   ├── project.py                   # Project ORM model
│   │   ├── source.py                    # SourceConfig + SourceCredentials ORM
│   │   └── destination.py               # DestinationConfig + DestinationCredentials ORM
│   ├── schemas/
│   │   ├── project.py                   # Pydantic in/out for projects
│   │   ├── source.py                    # Pydantic in/out for source
│   │   └── destination.py               # Pydantic in/out for destination
│   ├── services/
│   │   ├── acc/
│   │   │   └── adapter.py               # connect(), test_connection()
│   │   ├── aep/
│   │   │   └── adapter.py               # test_connectivity(), test_capabilities(), get_tenant_id()
│   │   └── ims/
│   │       └── token_manager.py         # get_token(), in-memory cache
│   ├── core/
│   │   ├── config.py                    # Settings (env vars, DB path)
│   │   └── security.py                  # encrypt_value(), decrypt_value()
│   └── db/
│       ├── session.py                   # engine + get_db()
│       └── base.py                      # Base declarative
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py              # projects + source + destination tables
├── tests/
│   ├── conftest.py                      # in-memory SQLite + test client
│   ├── test_projects.py
│   ├── test_source.py
│   └── test_destination.py
├── requirements.txt
├── Dockerfile
└── alembic.ini

frontend/
├── src/
│   ├── main.tsx
│   ├── App.tsx                          # Router setup
│   ├── api/
│   │   ├── client.ts                    # base fetch wrapper
│   │   ├── projects.ts                  # project CRUD calls
│   │   ├── source.ts                    # source config + test calls
│   │   └── destination.ts               # dest config + test calls
│   ├── store/
│   │   └── index.ts                     # Zustand: active project, nav state
│   ├── components/
│   │   ├── Layout.tsx                   # sidebar + main area shell
│   │   ├── NavSidebar.tsx               # project switcher + section nav
│   │   ├── SectionTabs.tsx              # tab bar within source/destination
│   │   ├── TestResultBadge.tsx          # pass/fail/pending badge
│   │   └── FormField.tsx                # label + input + error
│   └── pages/
│       ├── ProjectsPage.tsx             # project list + create
│       ├── source/
│       │   ├── ConnectionPage.tsx       # ACC URL, SOAP, network
│       │   └── AuthPage.tsx             # auth method, credentials, test
│       └── destination/
│           ├── OrgSandboxPage.tsx       # IMS Org ID, sandbox
│           └── AuthPage.tsx             # Developer Console creds, connectivity + capability tests
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── tsconfig.json
└── Dockerfile

docker-compose.yml
.env.example
```

---

## Task 1: Repo Scaffold

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/Dockerfile`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create `backend/requirements.txt`**

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.30
alembic==1.13.1
pydantic==2.7.1
pydantic-settings==2.2.1
cryptography==42.0.7
zeep==4.2.1
httpx==0.27.0
pytest==8.2.0
pytest-asyncio==0.23.6
httpx==0.27.0
```

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 3: Scaffold frontend with Vite**

```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
npm install react-router-dom zustand
```

- [ ] **Step 4: Create `frontend/tailwind.config.ts`**

```ts
import type { Config } from 'tailwindcss'
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
} satisfies Config
```

- [ ] **Step 5: Create `frontend/vite.config.ts`**

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

- [ ] **Step 6: Create `frontend/Dockerfile`**

```dockerfile
FROM node:20-slim
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]
```

- [ ] **Step 7: Create `docker-compose.yml`**

```yaml
version: '3.9'
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
      - ./data:/data
    env_file: .env

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    volumes:
      - ./frontend:/app
      - /app/node_modules
    depends_on:
      - backend
```

- [ ] **Step 8: Create `.env.example`**

```
DATABASE_URL=sqlite:////data/acc2ajo.db
ENCRYPTION_KEY=changeme-generate-with-python-secrets
```

- [ ] **Step 9: Commit**

```bash
git add .
git commit -m "feat: repo scaffold — backend + frontend + docker-compose"
```

---

## Task 2: Backend Core — DB, Config, Security

**Files:**
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/security.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`

- [ ] **Step 1: Create `backend/app/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Create `backend/app/core/config.py`**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite:////data/acc2ajo.db"
    encryption_key: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
```

- [ ] **Step 3: Create `backend/app/db/session.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Write failing test for security module**

Create `backend/tests/test_security.py`:

```python
from app.core.security import encrypt_value, decrypt_value

def test_encrypt_decrypt_roundtrip():
    plaintext = "super-secret-password"
    token = encrypt_value(plaintext)
    assert token != plaintext.encode()
    assert decrypt_value(token) == plaintext

def test_empty_string():
    token = encrypt_value("")
    assert decrypt_value(token) == ""
```

- [ ] **Step 5: Run test to confirm it fails**

```bash
cd backend
pytest tests/test_security.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 6: Create `backend/app/core/security.py`**

```python
import base64
from cryptography.fernet import Fernet
from app.core.config import settings

def _get_fernet() -> Fernet:
    key = settings.encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set")
    # Fernet requires a 32-byte url-safe base64 key
    padded = key.ljust(32)[:32].encode()
    b64_key = base64.urlsafe_b64encode(padded)
    return Fernet(b64_key)

def encrypt_value(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())

def decrypt_value(ciphertext: bytes) -> str:
    return _get_fernet().decrypt(ciphertext).decode()
```

- [ ] **Step 7: Create `backend/tests/conftest.py`**

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.db.session import get_db
from app.main import app
import os

os.environ["ENCRYPTION_KEY"] = "test-encryption-key-32chars-padded"
os.environ["DATABASE_URL"] = "sqlite://"

TEST_ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=TEST_ENGINE)

def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)

@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 8: Create `backend/app/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import projects, source, destination

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
```

- [ ] **Step 9: Run security tests**

```bash
cd backend
pytest tests/test_security.py -v
```
Expected: 2 PASSED

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/ backend/app/db/ backend/app/main.py backend/tests/
git commit -m "feat: backend core — db session, config, security, test fixtures"
```

---

## Task 3: Database Models + Alembic Migration

**Files:**
- Create: `backend/app/models/project.py`
- Create: `backend/app/models/source.py`
- Create: `backend/app/models/destination.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_initial.py`

- [ ] **Step 1: Create `backend/app/models/project.py`**

```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.orm import relationship
from app.db.base import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(String, default="")
    customer_name = Column(String, default="")
    environment = Column(String, default="dev")  # poc/dev/stage/prod
    migration_scope = Column(JSON, default=dict)
    default_timezone = Column(String, default="UTC")
    default_locale = Column(String, default="en_US")
    naming_prefix = Column(String, default="")
    output_format = Column(String, default="parquet")
    status = Column(String, default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_config = relationship("SourceConfig", back_populates="project", uselist=False)
    destination_config = relationship("DestinationConfig", back_populates="project", uselist=False)
```

- [ ] **Step 2: Create `backend/app/models/source.py`**

```python
import uuid
from sqlalchemy import Column, String, Boolean, Integer, LargeBinary, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base

class SourceConfig(Base):
    __tablename__ = "source_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, unique=True)
    instance_name = Column(String, default="")
    base_url = Column(String, default="")
    soap_endpoint = Column(String, default="")
    environment = Column(String, default="dev")
    version_build = Column(String, default="")
    region_hosting = Column(String, default="")
    rest_api_enabled = Column(String, default="unknown")  # yes/no/unknown
    db_access = Column(String, default="no")
    sftp_access = Column(String, default="no")
    vpn_required = Column(Boolean, default=False)
    ip_allowlist_required = Column(Boolean, default=False)
    proxy_host = Column(String, default="")
    proxy_port = Column(Integer, nullable=True)
    wsdl_discovery_enabled = Column(Boolean, default=True)
    extraction_method = Column(String, default="soap")
    package_export_enabled = Column(Boolean, default=False)

    project = relationship("Project", back_populates="source_config")
    credentials = relationship("SourceCredentials", back_populates="source_config", uselist=False)


class SourceCredentials(Base):
    __tablename__ = "source_credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    source_config_id = Column(String, ForeignKey("source_configs.id"), nullable=False, unique=True)
    auth_method = Column(String, default="session_token")  # session_token / technical_account
    operator_login = Column(String, default="")
    operator_password_enc = Column(LargeBinary, nullable=True)
    client_id = Column(String, default="")
    client_secret_enc = Column(LargeBinary, nullable=True)
    technical_account_id = Column(String, default="")  # metadata only
    ims_org_id = Column(String, default="")
    scope = Column(String, default="")
    private_key_enc = Column(LargeBinary, nullable=True)

    source_config = relationship("SourceConfig", back_populates="credentials")
```

- [ ] **Step 3: Create `backend/app/models/destination.py`**

```python
import uuid
from sqlalchemy import Column, String, Boolean, LargeBinary, ForeignKey
from sqlalchemy.orm import relationship
from app.db.base import Base

class DestinationConfig(Base):
    __tablename__ = "destination_configs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id"), nullable=False, unique=True)
    ims_org_id = Column(String, default="")
    org_display_name = Column(String, default="")
    region = Column(String, default="NA")
    sandbox_name = Column(String, default="")
    sandbox_type = Column(String, default="dev")
    aep_available = Column(Boolean, nullable=True)
    ajo_available = Column(Boolean, nullable=True)
    schema_permissions = Column(String, default="unknown")
    dataset_permissions = Column(String, default="unknown")
    ingestion_mode = Column(String, default="batch")

    project = relationship("Project", back_populates="destination_config")
    credentials = relationship("DestinationCredentials", back_populates="destination_config", uselist=False)


class DestinationCredentials(Base):
    __tablename__ = "destination_credentials"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    destination_config_id = Column(String, ForeignKey("destination_configs.id"), nullable=False, unique=True)
    client_id = Column(String, default="")           # sent as x-api-key
    client_secret_enc = Column(LargeBinary, nullable=True)
    technical_account_id = Column(String, default="")  # metadata only
    ims_org_id = Column(String, default="")           # sent as x-gw-ims-org-id
    scope = Column(String, default="")
    token_endpoint = Column(String, default="https://ims-na1.adobelogin.com/ims/token/v3")
    tenant_id = Column(String, default="")            # fetched from Schema Registry /stats

    destination_config = relationship("DestinationConfig", back_populates="credentials")
```

- [ ] **Step 4: Create `backend/alembic.ini`** (minimal)

```ini
[alembic]
script_location = alembic
sqlalchemy.url = sqlite:////data/acc2ajo.db
```

- [ ] **Step 5: Init Alembic and create migration**

```bash
cd backend
alembic init alembic
```

Edit `alembic/env.py` — replace the `target_metadata = None` line:

```python
from app.db.base import Base
from app.models import project, source, destination  # noqa: F401
target_metadata = Base.metadata
```

Then generate migration:

```bash
alembic revision --autogenerate -m "initial"
alembic upgrade head
```

- [ ] **Step 6: Write model tests**

Create `backend/tests/test_models.py`:

```python
from app.models.project import Project
from app.models.source import SourceConfig, SourceCredentials
from app.models.destination import DestinationConfig, DestinationCredentials

def test_project_defaults(setup_db):
    from tests.conftest import TestingSession
    db = TestingSession()
    p = Project(name="Test Project")
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.id is not None
    assert p.status == "draft"
    assert p.output_format == "parquet"
    db.close()
```

- [ ] **Step 7: Run model tests**

```bash
pytest tests/test_models.py -v
```
Expected: 1 PASSED

- [ ] **Step 8: Create `backend/app/models/__init__.py`** (empty)

```python
```

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/ backend/alembic/ backend/alembic.ini backend/tests/test_models.py
git commit -m "feat: ORM models and Alembic migration for projects, source, destination"
```

---

## Task 4: IMS Token Manager

**Files:**
- Create: `backend/app/services/ims/token_manager.py`
- Create: `backend/tests/test_token_manager.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_token_manager.py`:

```python
import time
import pytest
from unittest.mock import patch, MagicMock
from app.services.ims.token_manager import TokenManager

@pytest.fixture
def manager():
    return TokenManager()

def test_fetch_token_calls_ims(manager):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok123", "expires_in": 3600}

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        token = manager.get_token(
            client_id="cid",
            client_secret="csecret",
            token_endpoint="https://ims.example.com/token",
            scope="openid",
        )
    assert token == "tok123"
    assert mock_post.called

def test_token_is_cached(manager):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok_cached", "expires_in": 3600}

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        t1 = manager.get_token("cid", "cs", "https://ims/token", "openid")
        t2 = manager.get_token("cid", "cs", "https://ims/token", "openid")

    assert t1 == t2
    assert mock_post.call_count == 1  # fetched once, served from cache

def test_expired_token_is_refreshed(manager):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.side_effect = [
        {"access_token": "tok_old", "expires_in": 1},
        {"access_token": "tok_new", "expires_in": 3600},
    ]

    with patch("httpx.post", return_value=mock_resp):
        t1 = manager.get_token("cid", "cs", "https://ims/token", "openid")
        # Simulate expiry by backdating cache
        cache_key = ("cid", "https://ims/token", "openid")
        manager._cache[cache_key] = ("tok_old", time.time() - 10)
        t2 = manager.get_token("cid", "cs", "https://ims/token", "openid")

    assert t1 == "tok_old"
    assert t2 == "tok_new"

def test_ims_error_raises(manager):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="IMS token fetch failed"):
            manager.get_token("bad", "creds", "https://ims/token", "openid")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_token_manager.py -v
```
Expected: `ImportError` — module doesn't exist yet

- [ ] **Step 3: Create `backend/app/services/ims/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `backend/app/services/ims/token_manager.py`**

```python
import time
import httpx
from typing import Tuple

class TokenManager:
    # Cache key: (client_id, token_endpoint, scope) → (token, expiry_timestamp)
    _cache: dict[tuple, Tuple[str, float]] = {}

    def get_token(
        self,
        client_id: str,
        client_secret: str,
        token_endpoint: str,
        scope: str,
    ) -> str:
        cache_key = (client_id, token_endpoint, scope)
        if cache_key in self._cache:
            token, expires_at = self._cache[cache_key]
            if time.time() < expires_at - 60:  # 60s buffer before expiry
                return token

        response = httpx.post(
            token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": scope,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"IMS token fetch failed: {response.text}")

        data = response.json()
        token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._cache[cache_key] = (token, time.time() + expires_in)
        return token


# Singleton used by adapters
token_manager = TokenManager()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_token_manager.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ims/ backend/tests/test_token_manager.py
git commit -m "feat: IMS token manager with in-memory cache and auto-refresh"
```

---

## Task 5: Projects API

**Files:**
- Create: `backend/app/schemas/project.py`
- Create: `backend/app/api/projects.py`
- Create: `backend/tests/test_projects.py`

- [ ] **Step 1: Create `backend/app/schemas/project.py`**

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    customer_name: str = ""
    environment: str = "dev"
    migration_scope: Dict[str, Any] = {}
    default_timezone: str = "UTC"
    default_locale: str = "en_US"
    naming_prefix: str = ""
    output_format: str = "parquet"

class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    customer_name: str
    environment: str
    migration_scope: Dict[str, Any]
    default_timezone: str
    default_locale: str
    naming_prefix: str
    output_format: str
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_projects.py`:

```python
def test_list_projects_empty(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json() == []

def test_create_project(client):
    resp = client.post("/api/projects", json={"name": "My Migration"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Migration"
    assert data["status"] == "draft"
    assert "id" in data

def test_get_project(client):
    created = client.post("/api/projects", json={"name": "P1"}).json()
    resp = client.get(f"/api/projects/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "P1"

def test_get_nonexistent_project(client):
    resp = client.get("/api/projects/does-not-exist")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run to confirm failure**

```bash
pytest tests/test_projects.py -v
```
Expected: errors because router not created yet

- [ ] **Step 4: Create `backend/app/api/__init__.py`** (empty)

```python
```

- [ ] **Step 5: Create `backend/app/api/projects.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectOut

router = APIRouter()

@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).all()

@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project

@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_projects.py -v
```
Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/project.py backend/app/api/ backend/tests/test_projects.py
git commit -m "feat: projects CRUD API"
```

---

## Task 6: Source Config API (connection details)

**Files:**
- Create: `backend/app/schemas/source.py`
- Create: `backend/app/api/source.py`
- Create: `backend/tests/test_source.py`

- [ ] **Step 1: Create `backend/app/schemas/source.py`**

```python
from pydantic import BaseModel, field_validator
from typing import Optional

class SourceConfigIn(BaseModel):
    instance_name: str = ""
    base_url: str = ""
    environment: str = "dev"
    version_build: str = ""
    region_hosting: str = ""
    rest_api_enabled: str = "unknown"
    db_access: str = "no"
    sftp_access: str = "no"
    vpn_required: bool = False
    ip_allowlist_required: bool = False
    proxy_host: str = ""
    proxy_port: Optional[int] = None
    wsdl_discovery_enabled: bool = True
    extraction_method: str = "soap"
    package_export_enabled: bool = False

    @field_validator("base_url")
    @classmethod
    def derive_soap_endpoint(cls, v):
        return v  # stored as-is; soap_endpoint derived in service layer

class SourceConfigOut(SourceConfigIn):
    id: str
    project_id: str
    soap_endpoint: str

    class Config:
        from_attributes = True

class SourceCredentialsIn(BaseModel):
    auth_method: str = "session_token"
    operator_login: str = ""
    operator_password: str = ""          # plaintext in, encrypted before storage
    client_id: str = ""
    client_secret: str = ""              # plaintext in, encrypted before storage
    technical_account_id: str = ""
    ims_org_id: str = ""
    scope: str = ""
    private_key: str = ""                # plaintext in, encrypted before storage

class SourceCredentialsOut(BaseModel):
    id: str
    auth_method: str
    operator_login: str
    client_id: str
    technical_account_id: str
    ims_org_id: str
    scope: str
    # passwords/secrets never returned

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_source.py`:

```python
import pytest

@pytest.fixture
def project_id(client):
    resp = client.post("/api/projects", json={"name": "Src Test Project"})
    return resp.json()["id"]

def test_get_source_config_not_found(client, project_id):
    resp = client.get(f"/api/projects/{project_id}/source")
    assert resp.status_code == 404

def test_save_source_config(client, project_id):
    resp = client.put(f"/api/projects/{project_id}/source", json={
        "instance_name": "ACC Prod",
        "base_url": "https://acc.example.com",
        "environment": "prod",
        "vpn_required": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["instance_name"] == "ACC Prod"
    assert data["soap_endpoint"] == "https://acc.example.com/nl/jsp/soaprouter.jsp"

def test_update_source_config(client, project_id):
    client.put(f"/api/projects/{project_id}/source", json={"base_url": "https://v1.example.com"})
    resp = client.put(f"/api/projects/{project_id}/source", json={"base_url": "https://v2.example.com"})
    assert resp.status_code == 200
    assert resp.json()["soap_endpoint"] == "https://v2.example.com/nl/jsp/soaprouter.jsp"

def test_save_source_credentials(client, project_id):
    client.put(f"/api/projects/{project_id}/source", json={"base_url": "https://acc.example.com"})
    resp = client.put(f"/api/projects/{project_id}/source/credentials", json={
        "auth_method": "session_token",
        "operator_login": "tech_user",
        "operator_password": "secret123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["operator_login"] == "tech_user"
    assert "operator_password" not in data  # never returned

def test_credentials_password_not_stored_plaintext(client, project_id):
    from tests.conftest import TestingSession
    from app.models.source import SourceCredentials
    client.put(f"/api/projects/{project_id}/source", json={"base_url": "https://acc.example.com"})
    client.put(f"/api/projects/{project_id}/source/credentials", json={
        "auth_method": "session_token",
        "operator_login": "user",
        "operator_password": "plaintext_pw",
    })
    db = TestingSession()
    cred = db.query(SourceCredentials).first()
    assert cred.operator_password_enc != b"plaintext_pw"
    assert cred.operator_password_enc is not None
    db.close()
```

- [ ] **Step 3: Run to confirm failure**

```bash
pytest tests/test_source.py -v
```
Expected: errors — router not defined

- [ ] **Step 4: Create `backend/app/api/source.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.project import Project
from app.models.source import SourceConfig, SourceCredentials
from app.schemas.source import SourceConfigIn, SourceConfigOut, SourceCredentialsIn, SourceCredentialsOut
from app.core.security import encrypt_value, decrypt_value

router = APIRouter()

def _get_project_or_404(project_id: str, db: Session) -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p

@router.get("/projects/{project_id}/source", response_model=SourceConfigOut)
def get_source_config(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(SourceConfig).filter(SourceConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Source config not found")
    return config

@router.put("/projects/{project_id}/source", response_model=SourceConfigOut)
def save_source_config(project_id: str, payload: SourceConfigIn, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(SourceConfig).filter(SourceConfig.project_id == project_id).first()
    data = payload.model_dump()
    base_url = data.get("base_url", "").rstrip("/")
    soap_endpoint = f"{base_url}/nl/jsp/soaprouter.jsp" if base_url else ""

    if config:
        for k, v in data.items():
            setattr(config, k, v)
        config.soap_endpoint = soap_endpoint
    else:
        config = SourceConfig(**data, project_id=project_id, soap_endpoint=soap_endpoint)
        db.add(config)

    db.commit()
    db.refresh(config)
    return config

@router.put("/projects/{project_id}/source/credentials", response_model=SourceCredentialsOut)
def save_source_credentials(project_id: str, payload: SourceCredentialsIn, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(SourceConfig).filter(SourceConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=400, detail="Save source config before credentials")

    cred = db.query(SourceCredentials).filter(SourceCredentials.source_config_id == config.id).first()
    data = payload.model_dump()

    enc_password = encrypt_value(data.pop("operator_password")) if data.get("operator_password") else None
    enc_secret = encrypt_value(data.pop("client_secret")) if data.get("client_secret") else None
    enc_key = encrypt_value(data.pop("private_key")) if data.get("private_key") else None

    if cred:
        for k, v in data.items():
            setattr(cred, k, v)
        if enc_password:
            cred.operator_password_enc = enc_password
        if enc_secret:
            cred.client_secret_enc = enc_secret
        if enc_key:
            cred.private_key_enc = enc_key
    else:
        cred = SourceCredentials(
            **data,
            source_config_id=config.id,
            operator_password_enc=enc_password,
            client_secret_enc=enc_secret,
            private_key_enc=enc_key,
        )
        db.add(cred)

    db.commit()
    db.refresh(cred)
    return cred
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_source.py -v
```
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/source.py backend/app/api/source.py backend/tests/test_source.py
git commit -m "feat: source config and credentials API with encryption"
```

---

## Task 7: ACC Adapter — test_connection

**Files:**
- Create: `backend/app/services/acc/__init__.py`
- Create: `backend/app/services/acc/adapter.py`
- Create: `backend/tests/test_acc_adapter.py`
- Modify: `backend/app/api/source.py` — add POST `/source/test`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_acc_adapter.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from app.services.acc.adapter import ACCAdapter

@pytest.fixture
def session_token_creds():
    return {
        "auth_method": "session_token",
        "base_url": "https://acc.example.com",
        "operator_login": "admin",
        "operator_password": "pass",
    }

def test_session_token_connect_success(session_token_creds):
    mock_service = MagicMock()
    mock_service.Logon.return_value = MagicMock(
        sessionToken="tok123",
        securityToken="sec456",
    )
    with patch("zeep.Client", return_value=MagicMock(service=mock_service)):
        adapter = ACCAdapter(session_token_creds)
        result = adapter.test_connection()
    assert result["status"] == "ok"
    assert "session_token" in result

def test_session_token_connect_failure(session_token_creds):
    with patch("zeep.Client", side_effect=Exception("Connection refused")):
        adapter = ACCAdapter(session_token_creds)
        result = adapter.test_connection()
    assert result["status"] == "error"
    assert "Connection refused" in result["message"]

def test_soap_endpoint_derived_from_base_url(session_token_creds):
    adapter = ACCAdapter(session_token_creds)
    assert adapter.soap_endpoint == "https://acc.example.com/nl/jsp/soaprouter.jsp"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_acc_adapter.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `backend/app/services/acc/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `backend/app/services/acc/adapter.py`**

```python
from typing import Any
import zeep


class ACCAdapter:
    def __init__(self, config: dict[str, Any]):
        self.auth_method = config.get("auth_method", "session_token")
        self.base_url = config.get("base_url", "").rstrip("/")
        self.soap_endpoint = f"{self.base_url}/nl/jsp/soaprouter.jsp"
        self.operator_login = config.get("operator_login", "")
        self.operator_password = config.get("operator_password", "")
        # technical account fields (optional path)
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.token_endpoint = config.get("token_endpoint", "")
        self.scope = config.get("scope", "")
        self._session_token: str | None = None
        self._security_token: str | None = None

    def test_connection(self) -> dict[str, Any]:
        if self.auth_method == "session_token":
            return self._test_session_token()
        return self._test_technical_account()

    def _test_session_token(self) -> dict[str, Any]:
        try:
            wsdl = f"{self.base_url}/nl/jsp/schemawsdl.jsp?schema=xtk:session"
            client = zeep.Client(wsdl)
            resp = client.service.Logon(
                strLogin=self.operator_login,
                strPassword=self.operator_password,
                elemParameters=None,
            )
            self._session_token = resp.sessionToken
            self._security_token = resp.securityToken
            return {
                "status": "ok",
                "auth_method": "session_token",
                "session_token": self._session_token[:8] + "...",  # truncated for UI
                "message": "Connected successfully",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _test_technical_account(self) -> dict[str, Any]:
        # REST path — only used when rest_api_enabled=yes
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
```

- [ ] **Step 5: Add test endpoint to `backend/app/api/source.py`**

Add this import at the top:

```python
from app.services.acc.adapter import ACCAdapter
from app.core.security import decrypt_value
```

Add this route:

```python
@router.post("/projects/{project_id}/source/test")
def test_source_connection(project_id: str, db: Session = Depends(get_db)):
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
        "client_id": cred.client_id,
        "client_secret": decrypt_value(cred.client_secret_enc) if cred.client_secret_enc else "",
        "token_endpoint": "https://ims-na1.adobelogin.com/ims/token/v3",
        "scope": cred.scope,
    }
    adapter = ACCAdapter(adapter_config)
    return adapter.test_connection()
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/acc/ backend/app/api/source.py backend/tests/test_acc_adapter.py
git commit -m "feat: ACC adapter with session-token and technical-account test_connection"
```

---

## Task 8: Destination Config API

**Files:**
- Create: `backend/app/schemas/destination.py`
- Create: `backend/app/api/destination.py`
- Create: `backend/tests/test_destination.py`

- [ ] **Step 1: Create `backend/app/schemas/destination.py`**

```python
from pydantic import BaseModel
from typing import Optional

class DestinationConfigIn(BaseModel):
    ims_org_id: str = ""
    org_display_name: str = ""
    region: str = "NA"
    sandbox_name: str = ""
    sandbox_type: str = "dev"
    aep_available: Optional[bool] = None
    ajo_available: Optional[bool] = None
    schema_permissions: str = "unknown"
    dataset_permissions: str = "unknown"
    ingestion_mode: str = "batch"

class DestinationConfigOut(DestinationConfigIn):
    id: str
    project_id: str

    class Config:
        from_attributes = True

class DestinationCredentialsIn(BaseModel):
    client_id: str = ""
    client_secret: str = ""             # plaintext in, encrypted before storage
    technical_account_id: str = ""      # metadata only
    ims_org_id: str = ""
    scope: str = ""
    token_endpoint: str = "https://ims-na1.adobelogin.com/ims/token/v3"

class DestinationCredentialsOut(BaseModel):
    id: str
    client_id: str
    technical_account_id: str
    ims_org_id: str
    scope: str
    token_endpoint: str
    tenant_id: str

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Write failing tests**

Create `backend/tests/test_destination.py`:

```python
import pytest

@pytest.fixture
def project_id(client):
    return client.post("/api/projects", json={"name": "Dest Test"}).json()["id"]

def test_get_destination_not_found(client, project_id):
    assert client.get(f"/api/projects/{project_id}/destination").status_code == 404

def test_save_destination_config(client, project_id):
    resp = client.put(f"/api/projects/{project_id}/destination", json={
        "ims_org_id": "ABC123@AdobeOrg",
        "sandbox_name": "dev1",
        "sandbox_type": "dev",
        "region": "NA",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ims_org_id"] == "ABC123@AdobeOrg"
    assert data["sandbox_name"] == "dev1"
    assert data["ingestion_mode"] == "batch"

def test_save_destination_credentials(client, project_id):
    client.put(f"/api/projects/{project_id}/destination", json={"ims_org_id": "ABC@AdobeOrg"})
    resp = client.put(f"/api/projects/{project_id}/destination/credentials", json={
        "client_id": "my_client_id",
        "client_secret": "super_secret",
        "ims_org_id": "ABC@AdobeOrg",
        "scope": "openid,AdobeID",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["client_id"] == "my_client_id"
    assert "client_secret" not in data

def test_destination_secret_not_stored_plaintext(client, project_id):
    from tests.conftest import TestingSession
    from app.models.destination import DestinationCredentials
    client.put(f"/api/projects/{project_id}/destination", json={"ims_org_id": "X@AdobeOrg"})
    client.put(f"/api/projects/{project_id}/destination/credentials", json={
        "client_id": "cid",
        "client_secret": "plain_secret",
        "ims_org_id": "X@AdobeOrg",
    })
    db = TestingSession()
    cred = db.query(DestinationCredentials).first()
    assert cred.client_secret_enc != b"plain_secret"
    assert cred.client_secret_enc is not None
    db.close()
```

- [ ] **Step 3: Run to confirm failure**

```bash
pytest tests/test_destination.py -v
```
Expected: errors — router not created

- [ ] **Step 4: Create `backend/app/api/destination.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.project import Project
from app.models.destination import DestinationConfig, DestinationCredentials
from app.schemas.destination import (
    DestinationConfigIn, DestinationConfigOut,
    DestinationCredentialsIn, DestinationCredentialsOut,
)
from app.core.security import encrypt_value

router = APIRouter()

def _get_project_or_404(project_id: str, db: Session) -> Project:
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p

@router.get("/projects/{project_id}/destination", response_model=DestinationConfigOut)
def get_destination_config(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(DestinationConfig).filter(DestinationConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Destination config not found")
    return config

@router.put("/projects/{project_id}/destination", response_model=DestinationConfigOut)
def save_destination_config(project_id: str, payload: DestinationConfigIn, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(DestinationConfig).filter(DestinationConfig.project_id == project_id).first()
    data = payload.model_dump()
    if config:
        for k, v in data.items():
            setattr(config, k, v)
    else:
        config = DestinationConfig(**data, project_id=project_id)
        db.add(config)
    db.commit()
    db.refresh(config)
    return config

@router.put("/projects/{project_id}/destination/credentials", response_model=DestinationCredentialsOut)
def save_destination_credentials(project_id: str, payload: DestinationCredentialsIn, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    config = db.query(DestinationConfig).filter(DestinationConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=400, detail="Save destination config before credentials")

    cred = db.query(DestinationCredentials).filter(
        DestinationCredentials.destination_config_id == config.id
    ).first()
    data = payload.model_dump()
    enc_secret = encrypt_value(data.pop("client_secret")) if data.get("client_secret") else None

    if cred:
        for k, v in data.items():
            setattr(cred, k, v)
        if enc_secret:
            cred.client_secret_enc = enc_secret
    else:
        cred = DestinationCredentials(
            **data,
            destination_config_id=config.id,
            client_secret_enc=enc_secret,
        )
        db.add(cred)
    db.commit()
    db.refresh(cred)
    return cred
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_destination.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/destination.py backend/app/api/destination.py backend/tests/test_destination.py
git commit -m "feat: destination config and credentials API with encryption"
```

---

## Task 9: AEP Adapter — connectivity + capability tests

**Files:**
- Create: `backend/app/services/aep/__init__.py`
- Create: `backend/app/services/aep/adapter.py`
- Create: `backend/tests/test_aep_adapter.py`
- Modify: `backend/app/api/destination.py` — add POST `/destination/test/connect` and `/destination/test/capabilities`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_aep_adapter.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from app.services.aep.adapter import AEPAdapter

@pytest.fixture
def adapter():
    return AEPAdapter({
        "bearer_token": "tok123",
        "client_id": "cid",
        "ims_org_id": "ABC@AdobeOrg",
        "sandbox_name": "dev1",
    })

def _mock_resp(status: int, body: dict):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    return m

def test_connectivity_ok(adapter):
    with patch("httpx.get", return_value=_mock_resp(200, {"sandboxes": []})):
        result = adapter.test_connectivity()
    assert result["status"] == "ok"

def test_connectivity_bad_token(adapter):
    with patch("httpx.get", return_value=_mock_resp(401, {"error": "unauthorized"})):
        result = adapter.test_connectivity()
    assert result["status"] == "error"
    assert "401" in result["message"]

def test_capabilities_all_pass(adapter):
    with patch("httpx.get", return_value=_mock_resp(200, {"results": []})), \
         patch("httpx.post", return_value=_mock_resp(201, {"id": "batch1"})):
        result = adapter.test_capabilities()
    assert result["schema_registry"] in ("ok", "error")
    assert "catalog" in result

def test_get_tenant_id(adapter):
    with patch("httpx.get", return_value=_mock_resp(200, {"tenantId": "_acmecorp"})):
        tid = adapter.get_tenant_id()
    assert tid == "_acmecorp"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_aep_adapter.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Create `backend/app/services/aep/__init__.py`** (empty)

```python
```

- [ ] **Step 4: Create `backend/app/services/aep/adapter.py`**

```python
from typing import Any
import httpx

AEP_BASE = "https://platform.adobe.io"

class AEPAdapter:
    def __init__(self, config: dict[str, Any]):
        self.bearer_token = config.get("bearer_token", "")
        self.client_id = config.get("client_id", "")
        self.ims_org_id = config.get("ims_org_id", "")
        self.sandbox_name = config.get("sandbox_name", "")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.bearer_token}",
            "x-api-key": self.client_id,
            "x-gw-ims-org-id": self.ims_org_id,
            "x-sandbox-name": self.sandbox_name,
            "Content-Type": "application/json",
        }

    def test_connectivity(self) -> dict[str, Any]:
        """Validates token, org ID, and sandbox header are accepted."""
        try:
            resp = httpx.get(
                f"{AEP_BASE}/data/foundation/sandbox-management/sandboxes",
                headers=self._headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                return {"status": "ok", "message": "Connectivity verified"}
            return {"status": "error", "message": f"{resp.status_code}: {resp.text[:200]}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def test_capabilities(self) -> dict[str, Any]:
        """Checks read access to Schema Registry and Catalog."""
        results: dict[str, str] = {}

        # Schema Registry read
        try:
            schema_headers = {**self._headers(), "Accept": "application/vnd.adobe.xed-id+json"}
            resp = httpx.get(
                f"{AEP_BASE}/data/foundation/schemaregistry/tenant/schemas",
                headers=schema_headers,
                params={"limit": 1},
                timeout=10,
            )
            results["schema_registry"] = "ok" if resp.status_code == 200 else f"error:{resp.status_code}"
        except Exception as exc:
            results["schema_registry"] = f"error:{exc}"

        # Catalog / dataset read
        try:
            resp = httpx.get(
                f"{AEP_BASE}/data/foundation/catalog/datasets",
                headers=self._headers(),
                params={"limit": 1},
                timeout=10,
            )
            results["catalog"] = "ok" if resp.status_code == 200 else f"error:{resp.status_code}"
        except Exception as exc:
            results["catalog"] = f"error:{exc}"

        return results

    def get_tenant_id(self) -> str:
        """Fetches tenant ID from Schema Registry /stats."""
        schema_headers = {**self._headers(), "Accept": "application/vnd.adobe.xed+json"}
        resp = httpx.get(
            f"{AEP_BASE}/data/foundation/schemaregistry/stats",
            headers=schema_headers,
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to fetch tenant ID: {resp.status_code}")
        return resp.json().get("tenantId", "")
```

- [ ] **Step 5: Add test endpoints to `backend/app/api/destination.py`**

Add these imports:

```python
from app.services.aep.adapter import AEPAdapter
from app.services.ims.token_manager import token_manager
from app.core.security import decrypt_value
```

Add these routes:

```python
def _build_aep_adapter(project_id: str, db: Session) -> AEPAdapter:
    config = db.query(DestinationConfig).filter(DestinationConfig.project_id == project_id).first()
    if not config:
        raise HTTPException(status_code=400, detail="Destination config not saved yet")
    cred = db.query(DestinationCredentials).filter(
        DestinationCredentials.destination_config_id == config.id
    ).first()
    if not cred:
        raise HTTPException(status_code=400, detail="Destination credentials not saved yet")

    client_secret = decrypt_value(cred.client_secret_enc) if cred.client_secret_enc else ""
    token = token_manager.get_token(
        client_id=cred.client_id,
        client_secret=client_secret,
        token_endpoint=cred.token_endpoint,
        scope=cred.scope,
    )
    return AEPAdapter({
        "bearer_token": token,
        "client_id": cred.client_id,
        "ims_org_id": config.ims_org_id,
        "sandbox_name": config.sandbox_name,
    })

@router.post("/projects/{project_id}/destination/test/connect")
def test_destination_connectivity(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    adapter = _build_aep_adapter(project_id, db)
    return adapter.test_connectivity()

@router.post("/projects/{project_id}/destination/test/capabilities")
def test_destination_capabilities(project_id: str, db: Session = Depends(get_db)):
    _get_project_or_404(project_id, db)
    adapter = _build_aep_adapter(project_id, db)
    return adapter.test_capabilities()
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/aep/ backend/app/api/destination.py backend/tests/test_aep_adapter.py
git commit -m "feat: AEP adapter — connectivity + capability tests, tenant ID fetch"
```

---

## Task 10: Frontend — Layout + Router + API Client

**Files:**
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/source.ts`
- Create: `frontend/src/api/destination.ts`
- Create: `frontend/src/store/index.ts`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/NavSidebar.tsx`
- Create: `frontend/src/components/FormField.tsx`
- Create: `frontend/src/components/TestResultBadge.tsx`

- [ ] **Step 1: Update `frontend/src/main.tsx`**

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

- [ ] **Step 2: Add Tailwind directives to `frontend/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 3: Create `frontend/src/api/client.ts`**

```ts
const BASE = '/api'

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
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
```

- [ ] **Step 4: Create `frontend/src/api/projects.ts`**

```ts
import { apiFetch } from './client'

export interface Project {
  id: string
  name: string
  description: string
  customer_name: string
  environment: string
  status: string
  created_at: string
}

export const listProjects = () => apiFetch<Project[]>('/projects')
export const createProject = (data: Partial<Project>) =>
  apiFetch<Project>('/projects', { method: 'POST', body: JSON.stringify(data) })
export const getProject = (id: string) => apiFetch<Project>(`/projects/${id}`)
```

- [ ] **Step 5: Create `frontend/src/api/source.ts`**

```ts
import { apiFetch } from './client'

export interface SourceConfig {
  id: string
  project_id: string
  instance_name: string
  base_url: string
  soap_endpoint: string
  environment: string
  version_build: string
  rest_api_enabled: string
  db_access: string
  sftp_access: string
  vpn_required: boolean
  ip_allowlist_required: boolean
  proxy_host: string
  proxy_port: number | null
  wsdl_discovery_enabled: boolean
  extraction_method: string
  package_export_enabled: boolean
}

export interface SourceCredentials {
  auth_method: string
  operator_login: string
  operator_password?: string
  client_id?: string
  client_secret?: string
  technical_account_id?: string
  ims_org_id?: string
  scope?: string
  private_key?: string
}

export const getSourceConfig = (pid: string) =>
  apiFetch<SourceConfig>(`/projects/${pid}/source`)
export const saveSourceConfig = (pid: string, data: Partial<SourceConfig>) =>
  apiFetch<SourceConfig>(`/projects/${pid}/source`, { method: 'PUT', body: JSON.stringify(data) })
export const saveSourceCredentials = (pid: string, data: SourceCredentials) =>
  apiFetch(`/projects/${pid}/source/credentials`, { method: 'PUT', body: JSON.stringify(data) })
export const testSourceConnection = (pid: string) =>
  apiFetch<{ status: string; message: string }>(`/projects/${pid}/source/test`, { method: 'POST' })
```

- [ ] **Step 6: Create `frontend/src/api/destination.ts`**

```ts
import { apiFetch } from './client'

export interface DestinationConfig {
  id: string
  project_id: string
  ims_org_id: string
  org_display_name: string
  region: string
  sandbox_name: string
  sandbox_type: string
  aep_available: boolean | null
  ajo_available: boolean | null
  schema_permissions: string
  dataset_permissions: string
  ingestion_mode: string
}

export interface DestinationCredentials {
  client_id: string
  client_secret?: string
  technical_account_id?: string
  ims_org_id: string
  scope: string
  token_endpoint?: string
}

export const getDestinationConfig = (pid: string) =>
  apiFetch<DestinationConfig>(`/projects/${pid}/destination`)
export const saveDestinationConfig = (pid: string, data: Partial<DestinationConfig>) =>
  apiFetch<DestinationConfig>(`/projects/${pid}/destination`, { method: 'PUT', body: JSON.stringify(data) })
export const saveDestinationCredentials = (pid: string, data: DestinationCredentials) =>
  apiFetch(`/projects/${pid}/destination/credentials`, { method: 'PUT', body: JSON.stringify(data) })
export const testDestinationConnect = (pid: string) =>
  apiFetch<{ status: string; message: string }>(`/projects/${pid}/destination/test/connect`, { method: 'POST' })
export const testDestinationCapabilities = (pid: string) =>
  apiFetch<Record<string, string>>(`/projects/${pid}/destination/test/capabilities`, { method: 'POST' })
```

- [ ] **Step 7: Create `frontend/src/store/index.ts`**

```ts
import { create } from 'zustand'

interface AppState {
  activeProjectId: string | null
  setActiveProject: (id: string) => void
}

export const useAppStore = create<AppState>((set) => ({
  activeProjectId: null,
  setActiveProject: (id) => set({ activeProjectId: id }),
}))
```

- [ ] **Step 8: Create `frontend/src/components/FormField.tsx`**

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

- [ ] **Step 9: Create `frontend/src/components/TestResultBadge.tsx`**

```tsx
interface TestResultBadgeProps {
  status: 'idle' | 'loading' | 'ok' | 'error'
  message?: string
}

export function TestResultBadge({ status, message }: TestResultBadgeProps) {
  const styles = {
    idle: 'bg-gray-100 text-gray-600',
    loading: 'bg-blue-100 text-blue-700',
    ok: 'bg-green-100 text-green-700',
    error: 'bg-red-100 text-red-700',
  }
  const labels = { idle: '—', loading: 'Testing…', ok: '✓ Connected', error: '✗ Failed' }

  return (
    <div className={`rounded px-3 py-2 text-sm ${styles[status]}`}>
      <span className="font-semibold">{labels[status]}</span>
      {message && <span className="ml-2">{message}</span>}
    </div>
  )
}
```

- [ ] **Step 10: Create `frontend/src/components/NavSidebar.tsx`**

```tsx
import { Link, useParams } from 'react-router-dom'

const sourceLinks = [
  { label: 'Connection', to: 'source/connection' },
  { label: 'Authentication', to: 'source/auth' },
]
const destLinks = [
  { label: 'Org & Sandbox', to: 'destination/org' },
  { label: 'Authentication', to: 'destination/auth' },
]

export function NavSidebar() {
  const { id } = useParams()
  const base = id ? `/project/${id}` : ''

  return (
    <nav className="w-56 shrink-0 bg-gray-50 border-r border-gray-200 p-4 flex flex-col gap-6">
      <div>
        <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Source (ACC)</p>
        {sourceLinks.map((l) => (
          <Link key={l.to} to={`${base}/${l.to}`}
            className="block py-1.5 px-2 rounded text-sm text-gray-700 hover:bg-gray-200">
            {l.label}
          </Link>
        ))}
      </div>
      <div>
        <p className="text-xs font-semibold uppercase text-gray-400 mb-2">Destination (AJO/AEP)</p>
        {destLinks.map((l) => (
          <Link key={l.to} to={`${base}/${l.to}`}
            className="block py-1.5 px-2 rounded text-sm text-gray-700 hover:bg-gray-200">
            {l.label}
          </Link>
        ))}
      </div>
    </nav>
  )
}
```

- [ ] **Step 11: Create `frontend/src/components/Layout.tsx`**

```tsx
import { Outlet, Link } from 'react-router-dom'
import { NavSidebar } from './NavSidebar'

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-gray-900 text-white px-6 py-3 flex items-center gap-4">
        <Link to="/" className="font-bold text-lg tracking-tight">ACC → AJO</Link>
        <span className="text-gray-400 text-sm">Migration Workbench</span>
      </header>
      <div className="flex flex-1">
        <NavSidebar />
        <main className="flex-1 p-8 bg-white overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
```

- [ ] **Step 12: Create `frontend/src/App.tsx`**

```tsx
import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProjectsPage } from './pages/ProjectsPage'
import { SourceConnectionPage } from './pages/source/ConnectionPage'
import { SourceAuthPage } from './pages/source/AuthPage'
import { DestinationOrgPage } from './pages/destination/OrgSandboxPage'
import { DestinationAuthPage } from './pages/destination/AuthPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProjectsPage />} />
      <Route path="/project/:id" element={<Layout />}>
        <Route index element={<Navigate to="source/connection" replace />} />
        <Route path="source/connection" element={<SourceConnectionPage />} />
        <Route path="source/auth" element={<SourceAuthPage />} />
        <Route path="destination/org" element={<DestinationOrgPage />} />
        <Route path="destination/auth" element={<DestinationAuthPage />} />
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 13: Commit**

```bash
git add frontend/src/
git commit -m "feat: frontend scaffold — router, API client, layout, nav, shared components"
```

---

## Task 11: Frontend — Projects Page

**Files:**
- Create: `frontend/src/pages/ProjectsPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/ProjectsPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProjects, createProject, Project } from '../api/projects'
import { useAppStore } from '../store'

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const setActiveProject = useAppStore((s) => s.setActiveProject)

  useEffect(() => {
    listProjects().then(setProjects).catch(console.error)
  }, [])

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    setError('')
    try {
      const p = await createProject({ name: name.trim() })
      setActiveProject(p.id)
      navigate(`/project/${p.id}/source/connection`)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto py-12">
      <h1 className="text-2xl font-bold text-gray-900 mb-8">Migration Projects</h1>

      <form onSubmit={handleCreate} className="flex gap-3 mb-10">
        <input
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="New project name…"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button
          type="submit"
          disabled={creating}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {creating ? 'Creating…' : 'Create Project'}
        </button>
      </form>
      {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

      {projects.length === 0 ? (
        <p className="text-gray-400 text-sm">No projects yet. Create one above.</p>
      ) : (
        <div className="flex flex-col gap-3">
          {projects.map((p) => (
            <button
              key={p.id}
              onClick={() => { setActiveProject(p.id); navigate(`/project/${p.id}/source/connection`) }}
              className="text-left border border-gray-200 rounded-lg p-4 hover:border-blue-400 hover:shadow-sm transition"
            >
              <p className="font-semibold text-gray-900">{p.name}</p>
              <p className="text-xs text-gray-400 mt-1">{p.environment} · {p.status} · {new Date(p.created_at).toLocaleDateString()}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Start dev servers and verify page renders**

```bash
# Terminal 1
cd backend && uvicorn app.main:app --reload

# Terminal 2
cd frontend && npm run dev
```

Open `http://localhost:5173` — should show the Projects page with a create form.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx
git commit -m "feat: projects page — list + create + navigate to source config"
```

---

## Task 12: Frontend — Source Connection Page

**Files:**
- Create: `frontend/src/pages/source/ConnectionPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/source/ConnectionPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getSourceConfig, saveSourceConfig, SourceConfig } from '../../api/source'
import { FormField } from '../../components/FormField'

const EMPTY: Partial<SourceConfig> = {
  instance_name: '', base_url: '', environment: 'dev',
  version_build: '', rest_api_enabled: 'unknown',
  db_access: 'no', sftp_access: 'no',
  vpn_required: false, ip_allowlist_required: false,
  proxy_host: '', wsdl_discovery_enabled: true,
  extraction_method: 'soap', package_export_enabled: false,
}

export function SourceConnectionPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [form, setForm] = useState<Partial<SourceConfig>>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!projectId) return
    getSourceConfig(projectId).then(setForm).catch(() => {})
  }, [projectId])

  function set(field: keyof SourceConfig, value: any) {
    setSaved(false)
    setForm((f) => ({ ...f, [field]: value }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!projectId) return
    setSaving(true); setError('')
    try {
      const saved = await saveSourceConfig(projectId, form)
      setForm(saved)
      setSaved(true)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Source — Connection</h2>
      <p className="text-sm text-gray-500 mb-6">Adobe Campaign Classic instance details</p>

      <form onSubmit={handleSave} className="flex flex-col gap-5">
        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Instance Details</legend>
          <FormField label="Instance Name">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.instance_name ?? ''} onChange={(e) => set('instance_name', e.target.value)} placeholder="e.g. ACC Production" />
          </FormField>
          <FormField label="Base URL">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.base_url ?? ''} onChange={(e) => set('base_url', e.target.value)} placeholder="https://acc.company.com" />
          </FormField>
          {form.base_url && (
            <p className="text-xs text-gray-400">SOAP endpoint: <code className="bg-gray-100 px-1 rounded">{form.base_url.replace(/\/$/, '')}/nl/jsp/soaprouter.jsp</code></p>
          )}
          <FormField label="Environment">
            <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.environment ?? 'dev'} onChange={(e) => set('environment', e.target.value)}>
              <option value="poc">POC</option>
              <option value="dev">Dev</option>
              <option value="stage">Stage</option>
              <option value="prod">Prod</option>
            </select>
          </FormField>
          <FormField label="Version / Build (optional)">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.version_build ?? ''} onChange={(e) => set('version_build', e.target.value)} placeholder="e.g. v8" />
          </FormField>
        </fieldset>

        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">API Connectivity</legend>
          <FormField label="REST API Available?">
            <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.rest_api_enabled ?? 'unknown'} onChange={(e) => set('rest_api_enabled', e.target.value)}>
              <option value="yes">Yes</option>
              <option value="no">No</option>
              <option value="unknown">Unknown</option>
            </select>
          </FormField>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.wsdl_discovery_enabled ?? true} onChange={(e) => set('wsdl_discovery_enabled', e.target.checked)} />
              Enable WSDL Discovery
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.package_export_enabled ?? false} onChange={(e) => set('package_export_enabled', e.target.checked)} />
              Package Export (metadata)
            </label>
          </div>
        </fieldset>

        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Network</legend>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.vpn_required ?? false} onChange={(e) => set('vpn_required', e.target.checked)} />
              VPN Required
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.ip_allowlist_required ?? false} onChange={(e) => set('ip_allowlist_required', e.target.checked)} />
              IP Allowlist Required
            </label>
          </div>
          <FormField label="Proxy Host (optional)">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.proxy_host ?? ''} onChange={(e) => set('proxy_host', e.target.value)} placeholder="proxy.company.com" />
          </FormField>
        </fieldset>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex items-center gap-4">
          <button type="submit" disabled={saving} className="bg-blue-600 text-white px-5 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saved && <span className="text-sm text-green-600">Saved</span>}
        </div>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Navigate to a project → Source → Connection. Fill in a base URL and confirm the SOAP endpoint preview appears below it. Save and reload — config should persist.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/source/ConnectionPage.tsx
git commit -m "feat: source connection page — ACC URL, SOAP endpoint preview, network settings"
```

---

## Task 13: Frontend — Source Auth Page

**Files:**
- Create: `frontend/src/pages/source/AuthPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/source/AuthPage.tsx`**

```tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { saveSourceCredentials, testSourceConnection } from '../../api/source'
import { FormField } from '../../components/FormField'
import { TestResultBadge } from '../../components/TestResultBadge'

type AuthMethod = 'session_token' | 'technical_account'

export function SourceAuthPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [method, setMethod] = useState<AuthMethod>('session_token')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [techAccountId, setTechAccountId] = useState('')
  const [imsOrg, setImsOrg] = useState('')
  const [scope, setScope] = useState('')
  const [saving, setSaving] = useState(false)
  const [testStatus, setTestStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [testMessage, setTestMessage] = useState('')
  const [error, setError] = useState('')

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!projectId) return
    setSaving(true); setError('')
    try {
      await saveSourceCredentials(projectId, {
        auth_method: method,
        operator_login: login,
        operator_password: password,
        client_id: clientId,
        client_secret: clientSecret,
        technical_account_id: techAccountId,
        ims_org_id: imsOrg,
        scope,
      })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    if (!projectId) return
    setTestStatus('loading'); setTestMessage('')
    try {
      const result = await testSourceConnection(projectId)
      setTestStatus(result.status === 'ok' ? 'ok' : 'error')
      setTestMessage(result.message)
    } catch (err: any) {
      setTestStatus('error')
      setTestMessage(err.message)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Source — Authentication</h2>
      <p className="text-sm text-gray-500 mb-6">How the tool authenticates into ACC</p>

      <form onSubmit={handleSave} className="flex flex-col gap-5">
        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Auth Method</legend>
          <div className="flex gap-6">
            {(['session_token', 'technical_account'] as AuthMethod[]).map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="radio" name="auth_method" value={m} checked={method === m} onChange={() => setMethod(m)} />
                {m === 'session_token' ? 'Username / Password (Session Token)' : 'Technical Account (v8 OAuth S2S)'}
              </label>
            ))}
          </div>
        </fieldset>

        {method === 'session_token' && (
          <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
            <legend className="text-sm font-semibold text-gray-700 px-1">Credentials</legend>
            <FormField label="Operator Login">
              <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={login} onChange={(e) => setLogin(e.target.value)} placeholder="tech_migration" />
            </FormField>
            <FormField label="Password">
              <input type="password" className="border border-gray-300 rounded px-3 py-2 text-sm" value={password} onChange={(e) => setPassword(e.target.value)} />
            </FormField>
          </fieldset>
        )}

        {method === 'technical_account' && (
          <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
            <legend className="text-sm font-semibold text-gray-700 px-1">Adobe Developer Console Credentials</legend>
            <FormField label="Client ID">
              <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={clientId} onChange={(e) => setClientId(e.target.value)} />
            </FormField>
            <FormField label="Client Secret">
              <input type="password" className="border border-gray-300 rounded px-3 py-2 text-sm" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
            </FormField>
            <FormField label="Technical Account ID (metadata)">
              <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={techAccountId} onChange={(e) => setTechAccountId(e.target.value)} placeholder="abc@techacct.adobe.com" />
            </FormField>
            <FormField label="IMS Org ID">
              <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={imsOrg} onChange={(e) => setImsOrg(e.target.value)} placeholder="XXXXXX@AdobeOrg" />
            </FormField>
            <FormField label="Scope">
              <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="ent_campaign_sdk" />
            </FormField>
          </fieldset>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-4 flex-wrap">
          <button type="submit" disabled={saving} className="bg-blue-600 text-white px-5 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save Credentials'}
          </button>
          <button type="button" onClick={handleTest} disabled={testStatus === 'loading'} className="border border-gray-300 px-5 py-2 rounded text-sm font-medium hover:bg-gray-50 disabled:opacity-50">
            Test Connection
          </button>
          <TestResultBadge status={testStatus} message={testMessage} />
        </div>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Navigate to Source → Authentication. Switch between methods — fields should swap. Save credentials, then click Test Connection — badge should update.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/source/AuthPage.tsx
git commit -m "feat: source auth page — method toggle, credential fields, live connection test"
```

---

## Task 14: Frontend — Destination Org & Sandbox Page

**Files:**
- Create: `frontend/src/pages/destination/OrgSandboxPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/destination/OrgSandboxPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getDestinationConfig, saveDestinationConfig, DestinationConfig } from '../../api/destination'
import { FormField } from '../../components/FormField'

const EMPTY: Partial<DestinationConfig> = {
  ims_org_id: '', org_display_name: '', region: 'NA',
  sandbox_name: '', sandbox_type: 'dev',
  ingestion_mode: 'batch',
}

export function DestinationOrgPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [form, setForm] = useState<Partial<DestinationConfig>>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!projectId) return
    getDestinationConfig(projectId).then(setForm).catch(() => {})
  }, [projectId])

  function set(field: keyof DestinationConfig, value: any) {
    setSaved(false)
    setForm((f) => ({ ...f, [field]: value }))
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!projectId) return
    setSaving(true); setError('')
    try {
      const result = await saveDestinationConfig(projectId, form)
      setForm(result); setSaved(true)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Destination — Org & Sandbox</h2>
      <p className="text-sm text-gray-500 mb-6">Target Adobe Experience Platform environment</p>

      <form onSubmit={handleSave} className="flex flex-col gap-5">
        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Organization</legend>
          <FormField label="IMS Org ID">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.ims_org_id ?? ''} onChange={(e) => set('ims_org_id', e.target.value)} placeholder="XXXXXXXX@AdobeOrg" />
          </FormField>
          <FormField label="Org Display Name (optional)">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.org_display_name ?? ''} onChange={(e) => set('org_display_name', e.target.value)} />
          </FormField>
          <FormField label="Region">
            <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.region ?? 'NA'} onChange={(e) => set('region', e.target.value)}>
              <option value="NA">NA</option>
              <option value="EMEA">EMEA</option>
              <option value="APAC">APAC</option>
            </select>
          </FormField>
        </fieldset>

        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Sandbox</legend>
          <FormField label="Sandbox Name">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.sandbox_name ?? ''} onChange={(e) => set('sandbox_name', e.target.value)} placeholder="dev1" />
          </FormField>
          <FormField label="Sandbox Type">
            <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={form.sandbox_type ?? 'dev'} onChange={(e) => set('sandbox_type', e.target.value)}>
              <option value="dev">Development</option>
              <option value="stage">Stage</option>
              <option value="prod">Production</option>
            </select>
          </FormField>
        </fieldset>

        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex items-center gap-4">
          <button type="submit" disabled={saving} className="bg-blue-600 text-white px-5 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saved && <span className="text-sm text-green-600">Saved</span>}
        </div>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Navigate to Destination → Org & Sandbox. Fill in IMS Org ID and sandbox name. Save — values persist on reload.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/destination/OrgSandboxPage.tsx
git commit -m "feat: destination org and sandbox config page"
```

---

## Task 15: Frontend — Destination Auth Page

**Files:**
- Create: `frontend/src/pages/destination/AuthPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/destination/AuthPage.tsx`**

```tsx
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { saveDestinationCredentials, testDestinationConnect, testDestinationCapabilities } from '../../api/destination'
import { FormField } from '../../components/FormField'
import { TestResultBadge } from '../../components/TestResultBadge'

export function DestinationAuthPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [techAccountId, setTechAccountId] = useState('')
  const [imsOrg, setImsOrg] = useState('')
  const [scope, setScope] = useState('openid,AdobeID,read_organizations,additional_info.projectedProductContext')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [connectStatus, setConnectStatus] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [connectMsg, setConnectMsg] = useState('')
  const [capabilities, setCapabilities] = useState<Record<string, string> | null>(null)
  const [capLoading, setCapLoading] = useState(false)

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!projectId) return
    setSaving(true); setError('')
    try {
      await saveDestinationCredentials(projectId, {
        client_id: clientId,
        client_secret: clientSecret,
        technical_account_id: techAccountId,
        ims_org_id: imsOrg,
        scope,
      })
    } catch (err: any) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleTestConnect() {
    if (!projectId) return
    setConnectStatus('loading'); setConnectMsg('')
    try {
      const r = await testDestinationConnect(projectId)
      setConnectStatus(r.status === 'ok' ? 'ok' : 'error')
      setConnectMsg(r.message)
    } catch (err: any) {
      setConnectStatus('error'); setConnectMsg(err.message)
    }
  }

  async function handleTestCapabilities() {
    if (!projectId) return
    setCapLoading(true); setCapabilities(null)
    try {
      const r = await testDestinationCapabilities(projectId)
      setCapabilities(r)
    } catch (err: any) {
      setCapabilities({ error: err.message })
    } finally {
      setCapLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h2 className="text-xl font-bold text-gray-900 mb-1">Destination — Authentication</h2>
      <p className="text-sm text-gray-500 mb-2">Adobe Developer Console server-to-server credentials</p>
      <p className="text-xs text-gray-400 mb-6">Technical Account ID is stored as metadata only and is not sent on AEP API requests.</p>

      <form onSubmit={handleSave} className="flex flex-col gap-5">
        <fieldset className="border border-gray-200 rounded-lg p-4 flex flex-col gap-4">
          <legend className="text-sm font-semibold text-gray-700 px-1">Credentials</legend>
          <FormField label="Client ID">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={clientId} onChange={(e) => setClientId(e.target.value)} />
          </FormField>
          <FormField label="Client Secret">
            <input type="password" className="border border-gray-300 rounded px-3 py-2 text-sm" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} />
          </FormField>
          <FormField label="Technical Account ID (metadata)">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={techAccountId} onChange={(e) => setTechAccountId(e.target.value)} placeholder="abc@techacct.adobe.com" />
          </FormField>
          <FormField label="IMS Org ID">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={imsOrg} onChange={(e) => setImsOrg(e.target.value)} placeholder="XXXXXX@AdobeOrg" />
          </FormField>
          <FormField label="Scopes">
            <input className="border border-gray-300 rounded px-3 py-2 text-sm" value={scope} onChange={(e) => setScope(e.target.value)} />
          </FormField>
        </fieldset>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex items-center gap-4 flex-wrap">
          <button type="submit" disabled={saving} className="bg-blue-600 text-white px-5 py-2 rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {saving ? 'Saving…' : 'Save Credentials'}
          </button>
          <button type="button" onClick={handleTestConnect} disabled={connectStatus === 'loading'} className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 disabled:opacity-50">
            Test Connectivity
          </button>
          <TestResultBadge status={connectStatus} message={connectMsg} />
        </div>
      </form>

      <div className="mt-6 border-t border-gray-100 pt-6">
        <div className="flex items-center gap-4 mb-4">
          <button onClick={handleTestCapabilities} disabled={capLoading} className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 disabled:opacity-50">
            {capLoading ? 'Checking…' : 'Test API Capabilities'}
          </button>
          <span className="text-xs text-gray-400">Checks Schema Registry + Catalog access</span>
        </div>
        {capabilities && (
          <div className="flex flex-col gap-2">
            {Object.entries(capabilities).map(([key, val]) => (
              <div key={key} className="flex items-center gap-3 text-sm">
                <span className={`w-2 h-2 rounded-full ${val === 'ok' ? 'bg-green-500' : 'bg-red-400'}`} />
                <span className="font-medium capitalize">{key.replace(/_/g, ' ')}</span>
                <span className="text-gray-400">{val}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify in browser**

Navigate to Destination → Authentication. Fill in credentials and save. Click Test Connectivity — badge updates. Click Test API Capabilities — capability dots appear.

- [ ] **Step 3: Run full backend test suite one final time**

```bash
cd backend && pytest tests/ -v
```
Expected: all PASSED

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/destination/AuthPage.tsx
git commit -m "feat: destination auth page — credentials, connectivity test, capability checks"
```

- [ ] **Step 5: Push branch**

```bash
git push origin aditi
```

---

## Self-Review

**Spec coverage check:**
- ✅ Source connection details (URL, SOAP, network, extraction method, package export)
- ✅ Source credentials (session token + technical account, encrypted storage)
- ✅ ACC test_connection (both auth paths)
- ✅ Destination org/sandbox config
- ✅ Destination credentials (Developer Console S2S, encrypted)
- ✅ `technical_account_id` stored as metadata only — not sent as AEP header
- ✅ AEP test split: connectivity + capabilities separately
- ✅ Streaming hidden (ingestion_mode defaults batch, no streaming UI)
- ✅ Credentials never returned in API responses
- ✅ Encryption via security module (not hardcoded Fernet wording)
- ✅ SOAP endpoint auto-derived from base_url

**Placeholder scan:** None found — all steps contain actual code and commands.

**Type consistency:** All API response types used in frontend match backend Pydantic `Out` schema field names. `SourceConfig.soap_endpoint` derived server-side and returned in `SourceConfigOut`. `DestinationCredentialsOut.tenant_id` defaults to `""` until fetched.
