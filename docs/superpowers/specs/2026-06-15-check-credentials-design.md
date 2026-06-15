# Check Credentials — Design Spec
**Date:** 2026-06-15
**Status:** Approved

---

## 1. Overview

A standalone `/check-credentials` page that lets an admin paste Adobe Campaign Classic (ACC) OAuth credentials, verifies them in two steps (IMS token fetch → Campaign REST probe), and on success auto-creates a draft Project so the user can proceed directly to schema extraction.

This is Step 0 of the migration workflow — it validates that both the IMS side and the Campaign authorization side are correctly configured before any project setup begins.

---

## 2. Scope

**In scope:**
- New backend endpoint: `POST /api/check-credentials`
- New frontend page: `CheckCredentials.tsx` at route `/check-credentials`
- Saved profiles dropdown (loads existing projects with technical_account credentials)
- Auto-create Project + SourceConfig + SourceCredentials on success
- Step-by-step status progression UI
- Redirect to `/projects/{id}/schemas` on success

**Out of scope:**
- SOAP-based connection testing (existing `test_source_connection` covers that)
- Creating a new credential profile store (reuses existing models)

---

## 3. Architecture & Data Flow

### Backend: `POST /api/check-credentials`

**Request body:**
```json
{
  "acc_url": "https://myinstance.campaign.adobe.com",
  "client_id": "...",
  "client_secret": "...",
  "ims_org_id": "XXXXXXXX@AdobeOrg",
  "technical_account_id": "..." // optional
}
```

**Three sequential steps:**

1. **IMS token fetch** — `POST https://ims-na1.adobelogin.com/ims/token/v3`
   - grant_type: `client_credentials`
   - client_id + client_secret + scope: `openid,AdobeID,campaign` (scope is fixed; Campaign API entitlement determines whether the resulting token is accepted by Campaign)
   - Reuses existing `ImsTokenManager.get_token()`
   - Failure → 400 with message "IMS token request failed — check Client ID and Client Secret"

2. **Campaign REST probe** — `GET {acc_url}/rest/profileAndServices/profile?_lineCount=1`
   - Header: `Authorization: Bearer {token}`
   - Header: `X-Api-Key: {client_id}`
   - 200 (any body) → success
   - 401 → 400 "Campaign rejected the token — technical account may not be assigned a product profile"
   - 403 → 400 "Campaign denied access — confirm the Campaign API is added to your Developer Console project"
   - Timeout/unreachable → 400 "Could not reach Campaign instance — check the URL and network/VPN access"
   - Other → 400 "Campaign returned {status_code}: {excerpt}"

3. **Auto-create project** (only after step 2 succeeds)
   - Check for existing project: query `SourceCredentials` where `client_id` matches AND `ims_org_id` matches. If found, update credentials and return existing `project_id`.
   - If not found: create `Project` (name=`ACC – {ims_org_id}`, status=`configured`) + `SourceConfig` (base_url, rest_api_enabled=`yes`) + `SourceCredentials` (client_id, encrypted client_secret, ims_org_id, technical_account_id, auth_method=`technical_account`)
   - Encryption via existing `encrypt_value()`

**Response (success):**
```json
{
  "status": "ok",
  "project_id": "uuid",
  "project_created": true,  // false if existing project was updated
  "message": "Connection established · Login info stored"
}
```

**No DB writes on failure.** A failed check leaves nothing behind.

### Frontend: `GET /api/check-credentials/profiles`

Returns a lightweight list of existing projects that have `auth_method=technical_account` credentials, for the saved profiles dropdown:
```json
[
  { "project_id": "uuid", "project_name": "ACC – org@AdobeOrg", "ims_org_id": "...", "client_id": "..." }
]
```

---

## 4. UI — `CheckCredentials.tsx`

### Form Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| Load saved profile | dropdown | no | Pre-fills form from existing project credentials |
| ACC Instance URL | text | yes | e.g. `https://myinstance.campaign.adobe.com` |
| Client ID | text | yes | |
| Client Secret | password | yes | Masked; shown as `••••••••` when loaded from profile |
| IMS Org ID | text | yes | Validated for `@AdobeOrg` suffix |
| Technical Account ID | text | no | Stored as metadata |

### Status Progression (inline below submit button)

```
⏳ Fetching IMS token...
⏳ Probing Campaign REST endpoint...
✅ Connection established
✅ Login info stored · Project draft created
   → Redirecting to schema extraction in 2s...
```

Each line appears as the previous step resolves. Steps run sequentially (no parallel calls — each depends on the previous result).

On failure, a red banner replaces the spinner with the exact error message. The form remains editable.

### Navigation

- Accessible from the main app nav as "Check Credentials" (or "Quick Connect")
- On success: `setTimeout(() => navigate('/projects/{id}/schemas'), 2000)`
- No project context required to load the page

---

## 5. Error Handling

| Failure | Backend HTTP | UI message |
|---|---|---|
| Bad client_id / secret | 400 | "IMS token request failed — check Client ID and Client Secret" |
| Campaign 401 | 400 | "Campaign rejected the token — technical account may not be assigned a product profile" |
| Campaign 403 | 400 | "Campaign denied access — confirm the Campaign API is added to your Developer Console project" |
| Unreachable / timeout | 400 | "Could not reach Campaign instance — check the URL and network/VPN access" |
| Other Campaign error | 400 | "Campaign returned {status_code}: {excerpt}" |

---

## 6. Files Affected

### New files
- `backend/app/api/check_credentials.py` — endpoint + profiles listing
- `frontend/src/pages/CheckCredentials.tsx` — standalone page

### Modified files
- `backend/app/main.py` — register new router
- `frontend/src/App.tsx` — add `/check-credentials` route
- Frontend nav component — add "Check Credentials" link

### Reused (no changes needed)
- `backend/app/services/ims/token_manager.py`
- `backend/app/models/project.py`, `source.py`
- `backend/app/core/security.py` (`encrypt_value`)
- `backend/app/db/session.py`

---

## 7. Campaign REST API Reference

- **Endpoint:** `GET {acc_url}/rest/profileAndServices/profile?_lineCount=1`
- **Auth headers:** `Authorization: Bearer {ims_token}`, `X-Api-Key: {client_id}`
- **Why this endpoint:** Lightest read-only Campaign REST call. A 200 (even empty list) confirms the bearer token is accepted by Campaign and the technical account is recognized as an operator. No writes, no side effects.
- **Requires:** Campaign Classic 21.1+ or Campaign v8 with REST API enabled and Campaign API added to Developer Console project.
