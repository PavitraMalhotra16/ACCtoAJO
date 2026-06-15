# ACC → AJO Migration Tool — Design Spec
**Date:** 2026-06-15
**Status:** Approved (compliance-revised)

---

## 1. Overview

A local-first migration workbench that guides engineers through moving data and configuration from Adobe Campaign Classic (ACC) to Adobe Journey Optimizer (AJO) / Adobe Experience Platform (AEP).

The tool collects source and destination configuration, discovers what exists in ACC via SOAP and package export, maps ACC fields to AEP/XDM fields, validates AJO data-readiness, and executes extraction → transformation → batch-load pipelines.

AJO is modelled as dependent on AEP: schemas, datasets, identities, and profile ingestion all go through AEP first. AJO activation setup (journeys, audiences, channel config) is validated post-load.

---

## 2. Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite) + TypeScript + TailwindCSS + Zustand |
| Backend | FastAPI (Python 3.11) |
| Database | SQLite (local); credentials encrypted at rest via `cryptography` security module (implementation detail defined there) |
| Containerization | Docker Compose (two services: frontend, backend) |
| ACC connectivity | `zeep` (SOAP — primary); `httpx` (REST — optional, only when ACC v8 REST is confirmed enabled) |
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
│   │   │   └── security.py   # credential encryption module
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
| output_format | TEXT | parquet (default) / jsonl / csv |
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
| soap_endpoint | TEXT | auto-derived: `{base_url}/nl/jsp/soaprouter.jsp` |
| environment | TEXT | dev / stage / prod |
| version_build | TEXT | optional |
| region_hosting | TEXT | optional |
| rest_api_enabled | TEXT | yes / no / unknown — controls whether REST path is offered |
| db_access | TEXT | yes / no |
| sftp_access | TEXT | yes / no |
| vpn_required | BOOLEAN | |
| ip_allowlist_required | BOOLEAN | |
| proxy_host | TEXT | |
| proxy_port | INTEGER | |
| wsdl_discovery_enabled | BOOLEAN | |
| extraction_method | TEXT | soap (default) / package_export / db / file |
| package_export_enabled | BOOLEAN | used for metadata/config discovery |

### `source_credentials`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| auth_method | TEXT | session_token / technical_account |
| operator_login | TEXT | session_token method |
| operator_password_enc | BLOB | encrypted |
| client_id | TEXT | technical_account method |
| client_secret_enc | BLOB | encrypted |
| technical_account_id | TEXT | integration metadata only; not sent on API requests |
| ims_org_id | TEXT | |
| scope | TEXT | |
| private_key_enc | BLOB | encrypted, optional |

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
| ingestion_mode | TEXT | batch (v1 default; streaming hidden in UI until v2) |

### `destination_credentials`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| client_id | TEXT | sent as `x-api-key` on AEP requests |
| client_secret_enc | BLOB | encrypted; used only for IMS token fetch |
| technical_account_id | TEXT | integration metadata only; not a required AEP runtime header |
| ims_org_id | TEXT | sent as `x-gw-ims-org-id` on AEP requests |
| scope | TEXT | AEP OAuth scopes |
| token_endpoint | TEXT | default: `https://ims-na1.adobelogin.com/ims/token/v3` |
| tenant_id | TEXT | fetched from Schema Registry `/stats`; required for namespaced tenant resources |

### `discovery_results`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| discovered_at | DATETIME | |
| schema_name | TEXT | e.g. `nms:recipient` |
| namespace | TEXT | |
| label | TEXT | |
| physical_table | TEXT | |
| primary_key | TEXT | |
| delta_field | TEXT | |
| row_count | INTEGER | |
| field_list | JSON | array of `{name, type, required, label}` |
| links | JSON | array of `{target_schema, join_field}` |
| object_type | TEXT | data / metadata |
| entity_group | TEXT | profile / consent / template / campaign / workflow / webapp / integration / etc. |
| discovery_method | TEXT | soap_query / package_export |
| active | BOOLEAN | |

### `field_mappings`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| source_schema | TEXT | |
| source_field | TEXT | |
| source_type | TEXT | |
| target_schema_id | TEXT | AEP schema `$id` |
| target_field_path_dot | TEXT | dot-notation path for UI display |
| target_field_path_ptr | TEXT | JSON Pointer path used in API operations |
| target_namespace | TEXT | for identity fields |
| transform_rule | TEXT | none / hash / map / custom |
| transform_expression | TEXT | optional |
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
- Used for both ACC technical account tokens and all AEP API tokens

### `services/acc/adapter.py`

**Primary source path: SOAP + package export**
**Optional source path: REST (only when `rest_api_enabled = yes`)**

- `connect(project_id)` — session-token path: SOAP `xtk:session#Logon` → `sessionToken` + `securityToken`; technical-account path: IMS OAuth S2S Bearer
- `test_connection()` → validates login, returns server version and operator permission summary
- `discover_schemas_soap()` → paginated SOAP `xtk:queryDef` on `xtk:schema` table
- `get_schema_detail(schema_name)` → SOAP `xtk:schema#Get` → field list, PKs, links, enumerations
- `export_package(entity_type)` → ACC package export for metadata objects (workflows, templates, webapps, forms, JS, custom schemas); primary path for config/metadata discovery
- `extract_data(schema, mode, filters, chunk_size)` → paginated SOAP `xtk:queryDef#ExecuteQuery`; REST used only if explicitly enabled and confirmed by `rest_api_enabled` flag

### `services/aep/adapter.py`

**Connection test is split into two operations:**

`test_connectivity(project_id)`:
- validate Bearer token is accepted
- validate `x-gw-ims-org-id` is recognized
- validate `x-sandbox-name` resolves

`test_capabilities(project_id)`:
- can read Schema Registry? (GET tenant schemas)
- can read Catalog datasets?
- can create a dataset?
- can create a batch?

**Schema Registry operations:**
- `get_tenant_id()` → GET Schema Registry `/stats` endpoint; cache result as `tenant_id` in `destination_credentials`
- `list_schemas(container)` → GET with `Accept: application/vnd.adobe.xed-id+json`; handles pagination (`orderby`, `start`, `limit`); `container` = `global` or `tenant`
- `get_schema(schema_id)` → GET with `Accept: application/vnd.adobe.xed+json;version=1`
- All tenant-namespaced custom resources use `_{tenant_id}` prefix in field paths

**Dataset operations:**
- `list_datasets()` → Catalog Service GET with pagination
- `create_dataset(name, schema_ref, profile_enabled)` → Catalog POST

**Batch ingestion (documented 5-step flow):**
- `create_batch(dataset_id, format)` → POST to Batch Ingestion API; `format` = `parquet` (preferred for large structured loads) or `application/json` (JSONL)
- `upload_batch_file(batch_id, dataset_id, file_path)` → PUT file; files above size threshold use large-file upload path
- `complete_batch(batch_id)` → PATCH signal batch is complete
- `get_batch_status(batch_id)` → poll until `success` or `failed`
- `get_batch_errors(batch_id)` → retrieve per-record diagnostics on failure

**File format rules:**
- Default output: Parquet (preferred by AEP for large structured migration loads)
- JSON output: must be JSONL (one JSON object per line), not a JSON array
- Large files (above AEP documented threshold): use large-file upload path

### `services/orchestrator/pipeline.py`
- Runs as FastAPI `BackgroundTasks`
- Steps: `extract → serialize (Parquet/JSONL) → validate payload shape → create_batch → upload_batch_file → complete_batch → poll status → get_batch_errors if failed → update job status`
- Writes structured log entries to `job_logs` in real time

---

## 6. API Routes

```
GET  /api/projects                              list all projects
POST /api/projects                              create project
GET  /api/projects/{id}                         get project detail

GET  /api/projects/{id}/source                  get source config
PUT  /api/projects/{id}/source                  save source config
POST /api/projects/{id}/source/test             test ACC connection

GET  /api/projects/{id}/destination             get destination config
PUT  /api/projects/{id}/destination             save destination config
POST /api/projects/{id}/destination/test/connect  connectivity test only
POST /api/projects/{id}/destination/test/capabilities  capability checks

POST /api/projects/{id}/discover                run ACC schema + package discovery
GET  /api/projects/{id}/discovery               get cached discovery results

GET  /api/projects/{id}/mappings                get all field mappings
PUT  /api/projects/{id}/mappings                save field mappings

POST /api/projects/{id}/validate                run AJO readiness checklist
GET  /api/projects/{id}/validate                get last validation result

POST /api/projects/{id}/jobs                    start a migration job
GET  /api/projects/{id}/jobs                    list jobs
GET  /api/projects/{id}/jobs/{job_id}           get job status + summary
GET  /api/projects/{id}/jobs/{job_id}/logs      stream job logs (SSE)
```

---

## 7. Frontend Pages

| Page | Route | Purpose |
|---|---|---|
| Projects | `/` | Card grid, create project |
| Source — Connection | `/project/:id/source/connection` | ACC URL, SOAP endpoint, extraction method, network settings |
| Source — Authentication | `/project/:id/source/auth` | Auth method toggle (session / technical account), credential fields, permission test |
| Source — Discovery Scope | `/project/:id/source/scope` | Entity group accordions; package export toggle for metadata objects |
| Source — Data Objects | `/project/:id/source/objects` | Filter panel + grid + detail drawer |
| Source — Extraction Rules | `/project/:id/source/rules` | Extract mode, delta field, PII handling |
| Destination — Org & Sandbox | `/project/:id/destination/org` | IMS Org ID, sandbox name/type |
| Destination — Authentication | `/project/:id/destination/auth` | Adobe Developer Console S2S fields; connectivity + capability test results |
| Destination — Schemas | `/project/:id/destination/schemas` | Schema grid (tenant + global); bind/use-as-target actions |
| Destination — Datasets | `/project/:id/destination/datasets` | Source→schema→dataset mapping table |
| Destination — Identities | `/project/:id/destination/identities` | Identity namespace mapping grid; primary identity selection |
| Destination — Ingestion | `/project/:id/destination/ingestion` | Batch config only (streaming controls hidden/disabled in v1) |
| Mapping | `/project/:id/mapping` | Split panel: ACC field \| transform rule \| AEP field (dot path in UI) |
| Validation | `/project/:id/validation` | AJO readiness checklist: pass / warn / fail per item |
| Execution | `/project/:id/execution` | Run button, live SSE log stream, job status |
| Reports | `/project/:id/reports` | Summary cards, object counts, error table |

---

## 8. Authentication Details

### ACC — Session Token (primary for classic deployments)
Fields: `base_url`, `operator_login`, `operator_password`
Flow: POST SOAP `xtk:session#Logon` → `sessionToken` + `securityToken` → sent as SOAP headers on all subsequent calls.

### ACC — Technical Account (v8 only, optional)
Fields: `client_id`, `client_secret`, `ims_org_id`, `scope`
(`technical_account_id` stored as integration metadata; not required at runtime)
Flow: POST IMS `/ims/token/v3` → Bearer token → used on ACC v8 REST endpoints only when `rest_api_enabled = yes`.

### AJO/AEP — Adobe Developer Console Server-to-Server
Fields: `client_id`, `client_secret`, `ims_org_id`, `scope`, `sandbox_name`
(`technical_account_id` stored as integration metadata; not sent as an AEP API header)
Flow: POST IMS `/ims/token/v3` → Bearer token → every AEP API call includes:
```
Authorization: Bearer <token>
x-api-key: <client_id>
x-gw-ims-org-id: <ims_org_id>
x-sandbox-name: <sandbox_name>
```

Credential storage: credentials encrypted at rest using `core/security.py`. Implementation uses `cryptography` library; exact algorithm and key derivation defined in that module. Encryption key derived from machine-local secret, never stored in DB.

---

## 9. AJO Data-Readiness Validation Checklist

The Validation page runs a checklist engine that checks each item and marks it pass / warn / fail.

| # | Check | Required for AJO |
|---|---|---|
| 1 | Primary identity chosen | Yes |
| 2 | Identity namespace exists in AEP | Yes |
| 3 | Profile schema exists and is profile-enabled | Yes |
| 4 | Event schema exists (if migrating behavioral history) | Conditional |
| 5 | Consent/preference schema designed | Yes |
| 6 | All required datasets created | Yes |
| 7 | Profile-enabled datasets configured | Yes |
| 8 | At least one batch successfully ingested | Yes |
| 9 | AJO data source configuration present | Yes |
| 10 | AJO channel configuration present | Yes |
| 11 | Test profiles available | Recommended |
| 12 | Suppression / consent setup complete | Yes |
| 13 | Tracking / feedback / journey datasets visible | Conditional |
| 14 | Email / domain subdomain status verified (if email in scope) | Yes |

---

## 10. Field Path Representation

| Context | Format | Example |
|---|---|---|
| UI display | Dot notation | `person.name.firstName` |
| Internal storage | Both columns stored | see `field_mappings` table |
| AEP Schema Registry API | JSON Schema `$id` + field path | native schema structures |
| AEP payload construction | JSON Pointer | `/person/name/firstName` |
| Tenant-namespaced custom fields | `_{tenant_id}` prefix | `_acmecorp.loyaltyId` |

---

## 11. What is Out of Scope (v1)

- **Streaming ingestion** — `ingestion_mode` column exists for future use; streaming controls hidden/disabled in all v1 UI; streaming adapter methods marked `# planned: v2`
- AJO content/template rebuild assistant
- Workflow rebuild recommendations
- Historical log migration
- Multi-user / team access (local single-user only)
- Hosted deployment (Docker-ready but not deployed)
