# ACC → AJO Migration Tool — Design Spec
**Date:** 2026-06-15
**Status:** Approved

---

## 1. Overview

A local-first migration workbench that guides engineers through moving data and configuration from Adobe Campaign Classic (ACC) to Adobe Journey Optimizer (AJO) / Adobe Experience Platform (AEP).

The tool collects source and destination configuration, discovers what exists in ACC, maps ACC fields to AEP/XDM fields, validates readiness, and executes extraction → transformation → load pipelines.

---

## 2. Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite) + TypeScript + TailwindCSS + Zustand |
| Backend | FastAPI (Python 3.11) |
| Database | SQLite (local, AES-256 encrypted credentials via `cryptography`) |
| Containerization | Docker Compose (two services: frontend, backend) |
| ACC connectivity | `zeep` (SOAP), `httpx` (REST) |
| AEP connectivity | `httpx` (REST) |
| DB migrations | Alembic |

**Deployment model:** Local-first (`localhost`), Docker Compose from day one so it can be hosted later without a rewrite.

---

## 3. Project Structure

```
ACC2AJO/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── api/
│   │   └── store/
│   ├── Dockerfile
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── acc/
│   │   │   ├── aep/
│   │   │   └── ims/
│   │   ├── core/
│   │   └── db/
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
└── .env.example
```

---

## 4. Data Model

### `projects`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| name | TEXT | |
| description | TEXT | |
| customer_name | TEXT | |
| environment | TEXT | poc / dev / stage / prod |
| migration_scope | JSON | toggles: profiles, consent, schemas, templates, campaigns, workflows, typologies, webapps, history, integrations |
| default_timezone | TEXT | |
| default_locale | TEXT | |
| naming_prefix | TEXT | |
| output_format | TEXT | json / csv / parquet / xml |
| status | TEXT | draft / configured / discovered / mapped / validated / executing / complete |
| created_at | DATETIME | |
| updated_at | DATETIME | |

### `source_configs`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| instance_name | TEXT | |
| base_url | TEXT | |
| soap_endpoint | TEXT | auto-derived from base_url |
| environment | TEXT | dev / stage / prod |
| version_build | TEXT | optional |
| region_hosting | TEXT | optional |
| rest_api_enabled | TEXT | yes / no / unknown |
| db_access | TEXT | yes / no |
| sftp_access | TEXT | yes / no |
| vpn_required | BOOLEAN | |
| ip_allowlist_required | BOOLEAN | |
| proxy_host | TEXT | |
| proxy_port | INTEGER | |
| wsdl_discovery_enabled | BOOLEAN | |
| extraction_method | TEXT | api / db / file |

### `source_credentials`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| auth_method | TEXT | session_token / technical_account |
| operator_login | TEXT | |
| operator_password_enc | BLOB | AES-256 encrypted |
| client_id | TEXT | technical account only |
| client_secret_enc | BLOB | AES-256 encrypted |
| technical_account_id | TEXT | `<id>@techacct.adobe.com` |
| ims_org_id | TEXT | |
| scope | TEXT | |
| private_key_enc | BLOB | AES-256 encrypted, optional |

### `destination_configs`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| ims_org_id | TEXT | `XXXXXXXX@AdobeOrg` |
| org_display_name | TEXT | |
| region | TEXT | NA / EMEA / APAC |
| sandbox_name | TEXT | |
| sandbox_type | TEXT | dev / stage / prod |
| aep_available | BOOLEAN | |
| ajo_available | BOOLEAN | |
| schema_permissions | TEXT | yes / no / unknown |
| dataset_permissions | TEXT | yes / no / unknown |
| ingestion_mode | TEXT | batch / streaming |

### `destination_credentials`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| client_id | TEXT | |
| client_secret_enc | BLOB | AES-256 encrypted |
| technical_account_id | TEXT | |
| ims_org_id | TEXT | |
| scope | TEXT | AEP scopes |
| token_endpoint | TEXT | default: ims-na1.adobelogin.com/ims/token/v3 |
| tenant_id | TEXT | optional, fetched from Schema Registry |

### `discovery_results`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| discovered_at | DATETIME | |
| schema_name | TEXT | e.g. nms:recipient |
| namespace | TEXT | |
| label | TEXT | |
| physical_table | TEXT | |
| primary_key | TEXT | |
| delta_field | TEXT | |
| row_count | INTEGER | |
| field_list | JSON | array of {name, type, required, label} |
| links | JSON | array of {target_schema, join_field} |
| object_type | TEXT | data / metadata |
| entity_group | TEXT | profile / consent / template / campaign / workflow / etc. |
| active | BOOLEAN | |

### `field_mappings`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| source_schema | TEXT | |
| source_field | TEXT | |
| source_type | TEXT | |
| target_schema_id | TEXT | AEP schema $id |
| target_field_path | TEXT | dot-notation XDM path |
| target_namespace | TEXT | for identity fields |
| transform_rule | TEXT | none / hash / map / custom |
| transform_expression | TEXT | optional expression |
| is_primary_identity | BOOLEAN | |
| is_required | BOOLEAN | |
| status | TEXT | draft / validated / skipped |

### `migration_jobs`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| job_type | TEXT | discover / extract / load / full |
| status | TEXT | queued / running / completed / failed |
| config_snapshot | JSON | copy of config at run time |
| started_at | DATETIME | |
| completed_at | DATETIME | |
| records_extracted | INTEGER | |
| records_loaded | INTEGER | |
| records_failed | INTEGER | |

### `job_logs`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| job_id | UUID FK | |
| level | TEXT | info / warn / error |
| message | TEXT | |
| object_name | TEXT | schema or entity involved |
| timestamp | DATETIME | |

---

## 5. Backend Services

### `services/ims/token_manager.py`
- `get_token(project_id, side)` — fetches Bearer token from IMS using stored credentials, caches in memory with TTL, auto-refreshes
- Tokens never written to DB

### `services/acc/adapter.py`
- `connect(project_id)` — builds session using session-token or OAuth S2S
- `test_connection()` → server version + operator rights summary
- `discover_schemas()` → list all schemas via SOAP `xtk:queryDef`
- `get_schema_detail(schema_name)` → field list, PKs, links via `xtk:schema#Get`
- `extract_data(schema, mode, filters, chunk_size)` → paginated `xtk:queryDef#ExecuteQuery`

### `services/aep/adapter.py`
- `test_connection()` → GET sandbox list
- `list_schemas()` → Schema Registry GET all
- `get_schema(schema_id)` → Schema Registry GET by ID
- `list_datasets()` → Catalog Service GET
- `create_dataset(name, schema_ref)` → Catalog POST
- `create_batch(dataset_id, file_path)` → Batch Ingestion API POST
- `get_batch_status(batch_id)` → poll ingestion status

### `services/orchestrator/pipeline.py`
- Runs as FastAPI `BackgroundTasks`
- Steps: `extract → serialize (Parquet/JSONL) → validate payload → load → update job status`
- Writes structured log entries to `job_logs` in real time

---

## 6. API Routes

```
GET  /api/projects                        list all projects
POST /api/projects                        create project
GET  /api/projects/{id}                   get project detail

GET  /api/projects/{id}/source            get source config
PUT  /api/projects/{id}/source            save source config
POST /api/projects/{id}/source/test       test ACC connection

GET  /api/projects/{id}/destination       get destination config
PUT  /api/projects/{id}/destination       save destination config
POST /api/projects/{id}/destination/test  test AEP connection

POST /api/projects/{id}/discover          run ACC schema discovery
GET  /api/projects/{id}/discovery         get cached discovery results

GET  /api/projects/{id}/mappings          get all field mappings
PUT  /api/projects/{id}/mappings          save field mappings

POST /api/projects/{id}/jobs              start a migration job
GET  /api/projects/{id}/jobs              list jobs
GET  /api/projects/{id}/jobs/{job_id}     get job status + summary
GET  /api/projects/{id}/jobs/{job_id}/logs  stream job logs (SSE)
```

---

## 7. Frontend Pages

| Page | Route | Purpose |
|---|---|---|
| Projects | `/` | Card grid, create project |
| Source — Connection | `/project/:id/source/connection` | ACC URL, SOAP endpoint, network settings |
| Source — Authentication | `/project/:id/source/auth` | Auth method toggle, credential fields, permission test |
| Source — Discovery Scope | `/project/:id/source/scope` | Entity group accordions with checkboxes |
| Source — Data Objects | `/project/:id/source/objects` | Filter panel + grid + detail drawer |
| Source — Extraction Rules | `/project/:id/source/rules` | Extract mode, delta field, PII handling |
| Destination — Org & Sandbox | `/project/:id/destination/org` | IMS Org ID, sandbox name/type |
| Destination — Authentication | `/project/:id/destination/auth` | Tech account fields, capability checks |
| Destination — Schemas | `/project/:id/destination/schemas` | Schema grid, bind/use-as-target actions |
| Destination — Datasets | `/project/:id/destination/datasets` | Source→schema→dataset mapping table |
| Destination — Identities | `/project/:id/destination/identities` | Identity namespace mapping grid |
| Destination — Ingestion | `/project/:id/destination/ingestion` | Batch/streaming config tabs |
| Mapping | `/project/:id/mapping` | Split panel: ACC fields | transform rule | AEP field |
| Validation | `/project/:id/validation` | Readiness checklist: pass / warn / fail |
| Execution | `/project/:id/execution` | Run button, live SSE log stream, job status |
| Reports | `/project/:id/reports` | Summary cards, object counts, error table |

---

## 8. Authentication Details

### ACC — Session Token
Fields: `base_url`, `operator_login`, `operator_password`
Flow: POST SOAP `xtk:session#Logon` → `sessionToken` + `securityToken` → sent as headers on all subsequent SOAP calls.

### ACC — Technical Account (v8 OAuth S2S)
Fields: `client_id`, `client_secret`, `technical_account_id`, `ims_org_id`, `scope`
Flow: POST `https://ims-na1.adobelogin.com/ims/token/v3` → Bearer token → used on ACC v8 REST endpoints.

### AJO/AEP — Technical Account (OAuth S2S only)
Fields: `client_id`, `client_secret`, `technical_account_id`, `ims_org_id`, `scope`, `sandbox_name`
Flow: Same IMS token fetch → Bearer + `x-api-key` + `x-gw-ims-org-id` + `x-sandbox-name` headers on every AEP API call.

Credential storage: AES-256 (Fernet) encrypted blobs in SQLite. Encryption key derived from machine-local secret, never stored in DB.

---

## 9. What is Out of Scope (v1)

- Streaming ingestion setup UI (batch only in v1)
- AJO content/template rebuild assistant
- Workflow rebuild recommendations
- Historical log migration
- Multi-user / team access (local single-user only)
- Hosted deployment (Docker-ready but not deployed)
