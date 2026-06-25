# **ACC → AJO Template Migration: The Push Flow**

**Your job:** receive template JSON payloads (one per template, already in AJO payload format) and POST each one to Adobe Journey Optimizer as a **Content Template**.

**Not your job (happens upstream):** extracting from ACC, converting Campaign syntax to AJO syntax, resolving images. You receive *finished, push-ready* JSON. Your module is the last mile: authenticate → read payload → POST → record result.

---

## **1\. The big picture**

\[ push-ready JSON payloads, one per template \]  
              │  
              ▼  
(A) GET token from IMS  
              │  
              ▼  
(B) for each template payload:  
      validate  →  POST to AJO  
         │                  │  
       201 ✓             4xx/5xx  
       record id         record error, continue  
              │  
              ▼  
(D) write migration\_report.csv

One ACC delivery template → one AJO content template. No separate publish step needed — a `201` means the template was created successfully. It sits in `DRAFT` status. Here is what that means in plain terms:

* In AJO, a content template only ever has one status: `DRAFT`. There is no "Published" or "Active" status for templates.  
* `DRAFT` does **not** mean the template is incomplete or waiting for approval. It simply means it exists and is saved.  
* The moment the `201` comes back, the template is visible in the AJO UI under Content Management → Content Templates, and marketers can immediately pick it and apply it when building an email or SMS inside a journey or campaign.  
* Think of it like saving a Word document — once saved, anyone with access can open and use it. The word "DRAFT" is just AJO's internal label for the saved state of a content template, not a workflow stage.

---

## **2\. Credentials checklist**

| Credential | What it is | Where to get it |
| ----- | ----- | ----- |
| **Access token** | Short-lived bearer token (\~24h) | Developer Console → your project → Generate access token |
| **API key (Client ID)** | Identifies your integration | Developer Console → your project → Credentials |
| **Client secret** | Used to refresh the token programmatically | Developer Console → your project → Credentials |
| **IMS Org ID** | Your org, ends in `@AdobeOrg` | Developer Console → your project overview |
| **Sandbox name** | Target sandbox — the **name**, not the UUID | AJO UI → sandbox switcher (top right) |
| **Scopes** | Permission scopes for token refresh | Developer Console → Credentials → OAuth Server-to-Server → "Generate access token" panel. Copy the full scope string shown there. Scopes come from which APIs are added to the project — ensure **Adobe Journey Optimizer** and **Adobe Experience Platform** are both added. |

---

## **3\. Authentication**

### **API 1 — Get access token from Adobe IMS**

Since the script should be self-sufficient, it fetches the token automatically at the start of every run using your `client_id`, `client_secret`, and `scopes` — no manual token pasting needed. The token is valid for \~24 hours (`expires_in: 86399`). The script caches it and reuses it for all 100 POSTs. If a `401` is received mid-run (token expired), the script calls this again automatically and retries.

**Request**

POST https://ims-na1.adobelogin.com/ims/token/v3  
Content-Type: application/x-www-form-urlencoded

grant\_type=client\_credentials  
\&client\_id=\<API\_KEY\>  
\&client\_secret=\<CLIENT\_SECRET\>  
\&scope=\<SCOPES\>

As a curl:

curl \-X POST 'https://ims-na1.adobelogin.com/ims/token/v3' \\  
  \-H 'Content-Type: application/x-www-form-urlencoded' \\  
  \-d 'grant\_type=client\_credentials\&client\_id=\<API\_KEY\>\&client\_secret=\<CLIENT\_SECRET\>\&scope=\<SCOPES\>'

**Response — 200 OK**

{  
  "access\_token": "eyJhbGciOiJSUzI1NiIsIng1dSI6...",  
  "token\_type": "bearer",  
  "expires\_in": 86399  
}

| Field | Meaning |
| ----- | ----- |
| `access_token` | The bearer token. Put this in the `Authorization: Bearer` header on every subsequent request. |
| `token_type` | Always `bearer`. |
| `expires_in` | Seconds until expiry — always 86399 (\~24 hours). The script tracks when it fetched the token. When 82800 seconds (23 hours) have passed since then, it fetches a fresh one before continuing — this gives a 1-hour buffer so the token never expires mid-run. The reason to refresh *before* expiry rather than *after* is to avoid a situation where template 95 out of 100 fails with a `401` halfway through, forcing a retry. Proactive refresh keeps the run clean. |

Source: [OAuth Server-to-Server API Reference](https://developer.adobe.com/developer-console/docs/guides/authentication/ServerToServerAuthentication/ims)

**When to re-call:** when you receive a `401` from any AJO call, or when the token is close to expiry.

---

### **Required headers on every AJO request**

After getting the token, every AJO API call (GETs and POSTs) must include these headers:

Authorization:   Bearer \<ACCESS\_TOKEN\>  
x-api-key:       \<API\_KEY\>  
x-gw-ims-org-id: \<IMS\_ORG\_ID\>  
x-sandbox-name:  \<SANDBOX\_NAME\>          ← the name, NOT the UUID  
Content-Type:    application/vnd.adobe.ajo.template.v1+json   ← POST/PUT only  
Accept:          application/json

**Two things that consistently break calls:**

* `Content-Type` must be exactly `application/vnd.adobe.ajo.template.v1+json`. Using `application/json` causes a **`406`** error. The difference: `application/json` is the generic "this is JSON" header used by most APIs. `application/vnd.adobe.ajo.template.v1+json` is AJO-specific — the `vnd` means "vendor", meaning it is a custom format defined by Adobe specifically for AJO template payloads, versioned as `v1`. AJO uses this to know it is receiving a template payload and not just any JSON. Sending `application/json` tells AJO nothing about what kind of data it is, so AJO rejects it.  
* `x-sandbox-name` takes the sandbox **name** (e.g. `shashankn-sandbox`), not the sandbox UUID.

Source: [AJO API Authentication](https://developer.adobe.com/journey-optimizer-apis/references/authentication)

---

## **4\. Input format**

Each template payload is already in AJO POST format — validate it and POST it as-is with auth headers. This is the confirmed real payload shape verified from a live sandbox test.

### **4.1 Email template payload (confirmed working shape)**

{  
  "name": "Cyber Monday Sale \- Header \!\!",  
  "description": "Cyber Monday Sale \- Header Banner\!\!",  
  "templateType": "html",  
  "channels": \["email"\],  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "subType": "HTML",  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "template": {  
    "html": "\<html\>\<body\>Hi {{profile.person.name.firstName}} its a great day to shop\!\!\</body\>\</html\>",  
    "editorContext": {}  
  }  
}

### **4.2 SMS template payload**

{  
  "name": "Send to mobiles \- Order shipped",  
  "description": "Migrated from ACC sms template",  
  "templateType": "content",  
  "channels": \["sms"\],  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "template": {  
    "body": "Hi {{profile.person.name.firstName}}, your order has shipped.",  
    "editorContext": {}  
  }  
}

### **4.3 All fields explained**

| Field | Required | Notes |
| ----- | ----- | ----- |
| `name` | ✅ | Shown in AJO template library. Duplicates are allowed — multiple templates can share the same name. |
| `description` | optional | Use it to trace back to the ACC source. |
| `templateType` | ✅ | Allowed: `html`, `html_primary_page`, `html_sub_page`, `content`. Email → `html`. SMS → `content`. |
| `channels` | ✅ | `["email"]` or `["sms"]`. |
| `source` | ✅ | `origin` must always be `"ajo"`. `metadata` can be left as `{}` or used to store any custom key-value info you want attached to the template — AJO stores it as-is and returns it in GET responses. |
| `subType` | optional | AJO has a `code`\-based channel (used for custom code experiences, not email/SMS). For that channel, `subType` specifies the code format. For email and SMS templates it has no functional effect — AJO simply echoes back `"HTML"` for email in the GET response. Safe to include or omit. |
| `parentFolderId` | ✅ | UUID of the AJO folder to place the template in. Email templates contain the `Email` folder UUID, SMS templates contain the `SMS` folder UUID. Script uses it as-is. |
| `template.html` | ✅ email | AJO-ready HTML. All images must be absolute public URLs. No ACC `<%= %>` syntax. |
| `template.body` | ✅ SMS | SMS text. Max 160 chars per segment. |
| `template.editorContext` | ✅ | Always pass `{}`. |

### **4.4 Input contract — what each payload must already guarantee**

The person providing the payloads is responsible for these. If any are violated, the template goes in the manual bucket — not your push run.

1. Only AJO syntax. No ACC `<%= %>` syntax should remain. AJO uses two syntaxes:  
   * **Handlebars `{{...}}`** for profile attributes — these map to XDM profile fields. Common examples:  
     * `{{profile.person.name.firstName}}` — first name  
     * `{{profile.person.name.lastName}}` — last name  
     * `{{profile.person.name.fullName}}` — full name  
     * `{{profile.personalEmail.address}}` — email address  
     * `{{profile.mobilePhone.number}}` — phone number  
     * `{{profile.homeAddress.city}}` — city  
     * `{{profile.person.birthDate}}` — date of birth  
   * **PQL `{%= ... %}`** for functions and conditionals — e.g. `{%= formatDate(profile.person.birthDate, "dd/MM/yyyy") %}`, `{%#if profile.person.gender = "male" %}Sir{%/if%}`  
2. All image `src` are absolute public HTTPS URLs.  
3. HTML has no unclosed tags.  
4. ACC tracking tokens replaced: `%UNSUB%` → `{{unsubscribeLink}}`, `%MIRROR%` → `{{mirrorPageLink}}`.  
5. `parentFolderId` is present in every payload — the correct UUID for the `Email` or `SMS` folder.

---

## **5\. API 3 — Create a content template (the main push call)**

One call per template. This is the core of the push loop.

**Request**

POST https://platform.adobe.io/ajo/content/templates  
Authorization: Bearer \<ACCESS\_TOKEN\>  
x-api-key: \<API\_KEY\>  
x-gw-ims-org-id: \<IMS\_ORG\_ID\>  
x-sandbox-name: \<SANDBOX\_NAME\>  
Content-Type: application/vnd.adobe.ajo.template.v1+json  
Accept: application/json

**Request body — email:**

{  
  "name": "Cyber Monday Sale \- Header \!\!",  
  "description": "Cyber Monday Sale \- Header Banner\!\!",  
  "templateType": "html",  
  "channels": \["email"\],  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "subType": "HTML",  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "template": {  
    "html": "\<html\>\<body\>Hi {{profile.person.name.firstName}} its a great day to shop\!\!\</body\>\</html\>",  
    "editorContext": {}  
  }  
}

**Request body — SMS:**

{  
  "name": "Send to mobiles \- Order shipped",  
  "description": "Migrated from ACC sms template",  
  "templateType": "content",  
  "channels": \["sms"\],  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "template": {  
    "body": "Hi {{profile.person.name.firstName}}, your order has shipped.",  
    "editorContext": {}  
  }  
}

As a curl:

curl \-X POST 'https://platform.adobe.io/ajo/content/templates' \\  
  \-H 'Authorization: Bearer \<ACCESS\_TOKEN\>' \\  
  \-H 'x-api-key: \<API\_KEY\>' \\  
  \-H 'x-gw-ims-org-id: \<IMS\_ORG\_ID\>' \\  
  \-H 'x-sandbox-name: \<SANDBOX\_NAME\>' \\  
  \-H 'Content-Type: application/vnd.adobe.ajo.template.v1+json' \\  
  \-H 'Accept: application/json' \\  
  \-d '\<payload json\>'

**Response — 201 Created**

{  
  "id": "9b1c3e2a-4d7f-4a1b-bc34-f1e2d3c4b5a6",  
  "name": "Cyber Monday Sale \- Header \!\!",  
  "description": "Cyber Monday Sale \- Header Banner\!\!",  
  "templateType": "html",  
  "channels": \["email"\],  
  "status": "DRAFT",  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "createdAt": "2026-06-23T08:45:00Z",  
  "modifiedAt": "2026-06-23T08:45:00Z",  
  "createdBy": "your-tech-account@techacct.adobe.com"  
}

| Field | What to do with it |
| ----- | ----- |
| `id` | **Store this.** Permanent AJO identifier. Record it in the local database table against the corresponding template row. |
| `status` | Always `DRAFT`. Template is immediately usable. |
| `createdAt` | Timestamp for the migration report. |

Source: [Create Content Template API](https://developer.adobe.com/journey-optimizer-apis/references/content#operation/createTemplate)

---

## **6\. API 4 — Get a template by ID (verification after every POST)**

After every successful `201`, the script immediately calls this to verify the template was actually created in AJO with the correct data. This is not optional — it is a mandatory step after every POST.

**Request**

GET https://platform.adobe.io/ajo/content/templates/{TEMPLATE\_ID}  
Authorization: Bearer \<ACCESS\_TOKEN\>  
x-api-key: \<API\_KEY\>  
x-gw-ims-org-id: \<IMS\_ORG\_ID\>  
x-sandbox-name: \<SANDBOX\_NAME\>  
Accept: application/json

curl \-X GET 'https://platform.adobe.io/ajo/content/templates/9b1c3e2a-4d7f-4a1b-bc34-f1e2d3c4b5a6' \\  
  \-H 'Authorization: Bearer \<ACCESS\_TOKEN\>' \\  
  \-H 'x-api-key: \<API\_KEY\>' \\  
  \-H 'x-gw-ims-org-id: \<IMS\_ORG\_ID\>' \\  
  \-H 'x-sandbox-name: \<SANDBOX\_NAME\>' \\  
  \-H 'Accept: application/json'

**Response — 200 OK**

{  
  "id": "9b1c3e2a-4d7f-4a1b-bc34-f1e2d3c4b5a6",  
  "name": "Cyber Monday Sale \- Header \!\!",  
  "templateType": "html",  
  "channels": \["email"\],  
  "status": "DRAFT",  
  "parentFolderId": "a49dbe03-34e6-4231-aba0-0c255a9f08a1",  
  "source": {  
    "origin": "ajo",  
    "metadata": {}  
  },  
  "template": {  
    "html": "\<html\>\<body\>Hi {{profile.person.name.firstName}} its a great day to shop\!\!\</body\>\</html\>",  
    "editorContext": {}  
  },  
  "createdAt": "2026-06-23T08:45:00Z",  
  "modifiedAt": "2026-06-23T08:45:00Z"  
}

**How `parentFolderId` works in this flow:** The `parentFolderId` UUID for the `Email` and `SMS` folders is provided directly in each payload. The two folder UUIDs were obtained once by creating the `Email` and `SMS` folders in AJO UI and querying the templates API to get their UUIDs.

---

## **7\. Error response shapes**

Yes — whenever a POST fails (template not created), AJO returns one of these error shapes instead of a `201`. Your script reads the `status` code and the `detail` or `message` field from the response body to understand what went wrong, log it, and decide whether to retry or skip. The full handling logic for each status code is in §8.

**4xx Error response** — example: template creation failed because `name` field was missing

{  
  "type": "https://ns.adobe.com/adobecloud/problem/invalid-data",  
  "title": "Bad Request",  
  "status": 400,  
  "detail": "Field 'name' is required and cannot be blank",  
  "instance": "/ajo/content/templates",  
  "report": {  
    "additionalContext": {}  
  }  
}

**401 Unauthorized** — token expired or invalid. Note: this response comes from Adobe IMS (not AJO), so it uses a different shape — `error_code` instead of `status`, and `message` instead of `detail`.

{  
  "error\_code": "401013",  
  "message": "Oauth token is not valid"  
}

---

## **8\. Full error handling table**

| HTTP | Meaning | What your code does |
| ----- | ----- | ----- |
| `201` | Created | Extract `id` and write it to the local database table. Done. |
| `400` | Bad payload / missing field | Log the `detail` field from the error body. Mark `failed`. Continue to next template. |
| `401` | Token expired or invalid | Call IMS token endpoint (§3 API 1). Retry the same POST once with the new token. |
| `403` | Insufficient permissions | Stop the run. Fix the product profile permissions. |
| `406` | Wrong `Content-Type` or `Accept` header | Fix headers — this is a config bug affecting all calls. Stop and fix before continuing. |
| `409` | Template name already exists | Duplicates are allowed in this flow so this should not occur. If it does, treat it as an error — log it, mark `failed` in the report, and continue to the next template. |
| `413` | Payload too large | HTML is too big. Mark `manual` — needs image compression or HTML trimming before retry. Do not auto-retry. |
| `429` | Rate limited | Read the `Retry-After` header value (seconds). Wait that long, then retry with exponential backoff. Processing 100 templates in groups of 20–25 with pauses between groups should prevent this. |
| `500/503` | AJO server error | Retry once after 3s. If it fails again, mark `failed` and continue. |

---

## **9\. The complete push flow — step by step**

### **Phase A — Setup (once per run)**

**Step 1 — Get token** (API 1\) Script calls IMS with `client_id`, `client_secret`, `scopes`. Caches `access_token` and `fetch_time`. Sets a refresh trigger at `fetch_time + 82800s`.

**Step 2 — Load progress file** Reads `progress.json` if it exists (from a previous partial run). Builds a set of template names already marked `created` to skip on re-run.

---

### **Phase B — Batched push loop**

Process all 100 templates in **groups of 20–25**. After each group, `sleep(2–3 seconds)` to stay within AJO rate limits.

For each template payload:

**Step 3 — Skip if already done** If template is in the `created` set from `progress.json` → skip.

**Step 4 — Validate required fields**

* `name` must be present and non-empty.  
* `templateType` must be one of: `html`, `html_primary_page`, `html_sub_page`, `content`.  
* `channels` must be `["email"]` or `["sms"]`.  
* `template.html` must be present for email. `template.body` must be present for SMS.  
* `parentFolderId` must be present and non-empty.

If any check fails → `skipped (invalid input)`, continue.

**Step 5 — POST** (API 3 — §5) POST the payload JSON as-is. Auth headers from §3.

**Step 6 — Handle response** Per the table in §8.

**Step 7 — Verify creation** (API 4 — §6) Immediately after a `201`, call `GET /ajo/content/templates/{id}` using the `id` from the POST response. Confirm the response returns `200 OK` with the correct `name`, `channels`, and `status: "DRAFT"`. If the GET fails or returns unexpected data → mark `verification_failed` in the report and flag for manual review.

**Step 8 — Write to progress.json and local DB immediately**

{  
  "name": "Cyber Monday Sale \- Header \!\!",  
  "channel": "email",  
  "ajoTemplateId": "9b1c3e2a-4d7f-4a1b-bc34-f1e2d3c4b5a6",  
  "status": "created",  
  "verified": true,  
  "errorMessage": null,  
  "timestamp": "2026-06-23T08:45:00Z"  
}

**Step 9 — Throttle** After every 20–25 templates, `sleep(2)`.

---

### **Phase C — Report**

**Step 10 — Write migration\_report.csv**

One row per template:

name,channel,templateType,ajoTemplateId,status,verified,errorMessage  
Cyber Monday Sale \- Header \!\!,email,html,9b1c3e2a-...,created,true,  
Email delivery (re-marketing),email,html,3a2b1c0d-...,created,true,  
Send to mobiles,sms,content,,failed,false,Field 'template.body' is missing

Add a summary line: `Total: 98 created / 1 failed / 1 skipped`.

Hand the `failed` and `skipped` rows back to the upstream team for manual review.

---

## **10\. Notes on specific fields and gotchas**

### **templateType: html vs content for email**

* `html` — sets only the body. Subject is added by the marketer when using the template in a journey/campaign. Simplest migration path. Deprecated since March 2025 but still fully functional via API.  
* `content` — modern type, allows subject line inside the template. More complex internal structure.

The confirmed sandbox payload uses `html` — stick with it unless you need subjects inside the template.

### **SMS templateType**

`text` is **not** a valid value (despite appearing in some older docs). Use `templateType: "content"` with `channels: ["sms"]`. Confirm the body field name (`body`) with one test POST before running the SMS batch.

### **Images**

Externally hosted images at public absolute URLs go straight into HTML as `<img src="https://...">`. No AEM Assets upload needed. AJO renders any reachable URL directly.

### **Retry-After on 429**

The `429` response includes a `Retry-After` header specifying how many seconds to wait. Always read and respect this value — don't hardcode a wait time.

---

## **11\. Quick reference**

**Endpoint summary**

| Call | Method | URL |
| ----- | ----- | ----- |
| Get token | POST | `https://ims-na1.adobelogin.com/ims/token/v3` |
| List templates | GET | `https://platform.adobe.io/ajo/content/templates` |
| Create template | POST | `https://platform.adobe.io/ajo/content/templates` |
| Get template by ID | GET | `https://platform.adobe.io/ajo/content/templates/{id}` |
| Update template | PUT | `https://platform.adobe.io/ajo/content/templates/{id}` |
| Delete template | DELETE | `https://platform.adobe.io/ajo/content/templates/{id}` |

**Personalization syntax**

| What | Syntax |
| ----- | ----- |
| Profile attribute | `{{profile.person.name.firstName}}` |
| Format function | `{%= formatDate(profile.birthDate, "dd/MM/yyyy") %}` |
| Conditional | `{%#if profile.gender = "male" %}Sir{%else%}Ma'am{%/if%}` |
| Fallback value | `{%= profile.person.name.firstName ?: "there" %}` |
| Unsubscribe link | `{{unsubscribeLink}}` |
| Mirror page link | `{{mirrorPageLink}}` |

**Documentation**

* Content Templates API (createTemplate): https://developer.adobe.com/journey-optimizer-apis/references/content\#operation/createTemplate  
* API authentication (OAuth Server-to-Server): https://developer.adobe.com/journey-optimizer-apis/references/authentication  
* OAuth Server-to-Server token API reference: https://developer.adobe.com/developer-console/docs/guides/authentication/ServerToServerAuthentication/ims  
* OAuth Server-to-Server implementation guide: https://developer.adobe.com/developer-console/docs/guides/authentication/ServerToServerAuthentication/implementation  
* Get started with content templates: https://experienceleague.adobe.com/en/docs/journey-optimizer/using/content-management/content-templates/content-templates  
* Personalization syntax (Handlebars \+ PQL): https://experienceleague.adobe.com/en/docs/journey-optimizer/using/content-management/personalization/personalization-syntax  
* Helper functions (formatDate, if, each, fallback): https://experienceleague.adobe.com/en/docs/journey-optimizer/using/content-management/personalization/functions/helpers.html  
* Journey Optimizer API overview: https://developer.adobe.com/journey-optimizer-apis/

