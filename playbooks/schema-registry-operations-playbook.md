# Schema Registry — Operations Playbook

Basic operations against the Adobe Experience Platform **Schema Registry**:

1. Delete a schema (non-Profile-enabled only)
2. List schemas
3. Display all attributes/details for a given schema
4. Create a dummy schema

> **Approval gate (applies to every operation):** before running any call below, confirm the inputs
> and get **explicit approval** to execute. Treat **Delete (1)** and **Create (4)** with extra care —
> they change state. **List (2)** and **Display (3)** are read-only. Never execute without
> confirmation.
>
> **Credentials — always ask the user directly.** Do NOT fetch or decrypt tokens from the database,
> do NOT reuse tokens from `.env` files, and do NOT attempt to derive credentials from application
> state. Always ask the user to supply: access token, API key (client ID), org ID, and sandbox name
> before proceeding. Tokens expire — a freshly provided token is the only safe input.
>
> **Scope of Delete (1):** these steps apply only to schemas where **Profile is NOT enabled**
> (`meta:immutableTags` does not contain `"union"`). Once a schema is Profile-enabled, AEP makes
> that tag permanent — there is no API to remove it and deletion will be blocked. For those schemas,
> contact Adobe Support or reset the sandbox.

---

## Common setup (needed for every operation)

All calls use the Schema Registry base URL and the same auth headers.

- **Base URL:** `https://platform.adobe.io/data/foundation/schemaregistry`
- **Headers (every call):**

| Input | Header | Notes |
|---|---|---|
| Access token | `Authorization: Bearer {ACCESS_TOKEN}` | Short-lived IMS token; refresh if expired. |
| API key | `x-api-key: {API_KEY}` | From your Developer Console project. |
| Org ID | `x-gw-ims-org-id: {ORG_ID}` | `XXXX@AdobeOrg`. |
| Sandbox | `x-sandbox-name: {SANDBOX_NAME}` | Schemas are isolated per sandbox — make sure this matches. |
| (POST only) | `Content-Type: application/json` | On create. |

- **`$id` rule:** a schema's `$id` looks like
  `https://ns.adobe.com/{TENANT_ID}/schemas/{hash}`. Use it **raw** in request bodies; **URL-encode**
  it when it goes into a path parameter (encode `:` → `%3A` and `/` → `%2F`). Example encoded form:
  `https%3A%2F%2Fns.adobe.com%2F{TENANT_ID}%2Fschemas%2F{hash}`.

---

## 1. Delete a schema (non-Profile-enabled only)

Removes a custom schema from the registry. **Destructive and permanent.**
Only follow these steps for schemas where **Profile is NOT enabled** (UI shows "Not enabled" in the
Enabled for Profile column, and `meta:immutableTags` is absent from the schema's display output).

**Inputs required:**
- Common setup (token, API key, org, sandbox)
- `{$id}` of the schema to delete (URL-encoded for the path)

**Steps:**
1. Run **Operation 2** (list) to find the schema title and copy its `$id`.
2. Run **Operation 3** (display) on the schema and confirm:
   - `"title"` matches what you intend to delete.
   - `meta:immutableTags` is **absent** (no `"union"` tag) — if it is present, stop; see the note
     below.
3. **Get approval to execute** (destructive).
4. URL-encode the `$id`: replace `:` → `%3A` and `/` → `%2F`.
5. Run the delete:

```bash
curl -X DELETE \
  'https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas/{URL_ENCODED_$id}' \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}'
```

**Expected result:** `204 No Content` on success.

**If you get `400 XDM-1547` (Breaking Change Violation):**
This means the schema is tied to the Profile union even if the UI shows "Not enabled". The error
body will list blocking dataset IDs. There is no API workaround — the `meta:immutableTags: ["union"]`
field is truly immutable. Options:
- Contact Adobe Support to force-delete.
- Reset the sandbox (if it is a throwaway dev sandbox).

**Notes / gotchas:**
- Deletion is permanent and scoped to the sandbox in `x-sandbox-name`.
- Use `Content-Type: application/json` for PATCH calls against this API — `application/json-patch+json`
  returns `415 Unsupported Media Type`.

---

## 2. List schemas

Lists all custom (tenant) schemas in the sandbox.

**Inputs required:**
- Common setup (token, API key, org, sandbox)

**Steps:**
1. Confirm the target sandbox.
2. **Get approval to execute** (read-only, but confirm inputs).
3. Run the list:

```bash
curl -X GET \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Accept: application/vnd.adobe.xed-id+json'
```

**Expected result:** an array of schema summaries, each with `title`, `$id`, `version`, and
`meta:altId`. Scan `title` for the schema(s) you want; copy the `$id` for use in operations 1 and 3.

**Notes:**
- This returns your **tenant** (custom) schemas, not Adobe's standard/global ones.
- Large registries are paginated — use `?limit={n}` and follow the paging cursor if the list is
  truncated.
- For richer output (full schema objects instead of just IDs), use
  `Accept: application/vnd.adobe.xed+json` — but `xed-id+json` is the lightweight default for listing.

---

## 3. Display all attributes/details for a given schema

Shows the fully resolved schema — all fields/attributes, types, required list, and optionally
descriptors (relationships, primary keys, timestamps).

**Inputs required:**
- Common setup (token, API key, org, sandbox)
- `{$id}` of the schema (URL-encoded for the path)

**Steps:**
1. Get the `$id` from **Operation 2** if you don't have it.
2. **Get approval to execute** (read-only, but confirm inputs).
3. Run the fetch (choose the Accept header variant below based on what you need):

```bash
curl -X GET \
  'https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas/{URL_ENCODED_$id}' \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Accept: application/vnd.adobe.xed-full+json; version=1'
```

**Expected result:** `200` with the full schema body — `title`, `description`, all `properties`
(fields) with their types, the `required` array, and meta.

**Accept-header variants (pick what you need):**
- `application/vnd.adobe.xed-full+json; version=1` — full schema with all fields resolved.
- `application/vnd.adobe.xed-full-desc+json; version=1` — full schema **plus its descriptors**
  (primary key, timestamp, relationships, etc.) resolved inline under `meta:descriptors`. Use this
  to inspect a relational schema's descriptors in one call — preferred over a separate descriptors
  query.
- `application/vnd.adobe.xed-id+json` — just the identifiers (`title`, `$id`, `version`).

**Key fields to check in the response:**
- `meta:immutableTags: ["union"]` — present means Profile is enabled (deletion blocked via API).
- `meta:descriptors` — array of all descriptors; see **Operation 5** for relationship details.
- `schemaType` — `"adhoc-v2"` means relational/lookup; `"standard"` means XDM class-based.

---

## 5. Fetch relationships for a schema

Shows all `xdm:descriptorRelationship` descriptors defined on a schema — which fields are foreign
keys and what they point to.

**Inputs required:**
- Common setup (token, API key, org, sandbox)
- `{$id}` of the schema (URL-encoded for the path)

**Steps:**
1. Run the display call from **Operation 3** with the `xed-full-desc+json` Accept header — the
   `meta:descriptors` array in the response contains all descriptors including relationships.
2. Filter `meta:descriptors` entries where `"@type": "xdm:descriptorRelationship"`.

```bash
curl -X GET \
  'https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas/{URL_ENCODED_$id}' \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Accept: application/vnd.adobe.xed-full-desc+json; version=1'
```

**Reading a relationship descriptor:**

```json
{
  "@type": "xdm:descriptorRelationship",
  "xdm:sourceSchema": "...schemas/{source-hash}",
  "xdm:sourceProperty": "/customerId",
  "xdm:destinationSchema": "...schemas/{destination-hash}",
  "xdm:destinationProperty": "/customerId",
  "xdm:cardinality": "M:1"
}
```

| Field | Meaning |
|---|---|
| `xdm:sourceProperty` | Foreign key field on this schema |
| `xdm:destinationSchema` | The schema being referenced (look up its title via **Op 3**) |
| `xdm:destinationProperty` | The primary key field on the destination schema |
| `xdm:cardinality` | `M:1` = many rows here map to one row there |

**Other descriptor types you may see:**

| `@type` | Meaning |
|---|---|
| `xdm:descriptorPrimaryKey` | Marks the primary key field(s) of the schema |
| `xdm:descriptorTimestamp` | Marks the timestamp field (used for time-series ordering) |
| `xdm:descriptorIdentity` | Marks an identity field (used for Profile stitching) |

---

## 4. Create a dummy schema

Creates a minimal throwaway schema (useful for testing the other operations or verifying
entitlement). This example creates a minimal **relational** schema.

**Inputs required:**
- Common setup (token, API key, org, sandbox) + `Content-Type: application/json`
- A `title` for the dummy (use an obvious throwaway name, e.g. `dummy_test_schema`)

**Steps:**
1. Choose a clearly-disposable `title`.
2. **Get approval to execute** (creates state).
3. Run the create:

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Content-Type: application/json' \
  -d '{
        "title": "dummy_test_schema",
        "type": "object",
        "description": "Temporary dummy schema for testing.",
        "meta:extends": [ "https://ns.adobe.com/xdm/data/adhoc-v2" ],
        "definitions": {
          "customFields": {
            "type": "object",
            "properties": {
              "dummyId": { "title": "Dummy ID", "type": "string" }
            }
          }
        },
        "allOf": [ { "$ref": "#/definitions/customFields" } ]
      }'
```

**Expected result:** `201 Created` with the new schema's `$id`, `version`, and `title`. Save the
`$id`.

**Cleanup:** when done testing, delete it with **Operation 1** (pass the `$id` you just got, URL-encoded).

**Notes:**
- This is a relational dummy (`meta:extends` adhoc-v2). It's the simplest schema to create and tear
  down for testing.
- The `title` is what shows up in **Operation 2**'s list — keep it obviously disposable so it's easy
  to find and delete.

---

**Fetching schema metadata (created/modified timestamps):**

These fields are returned in every `xed-full+json` or `xed-full-desc+json` response under
`meta:registryMetadata`:

```json
"meta:registryMetadata": {
  "repo:createdDate": 1782060976602,
  "repo:lastModifiedDate": 1782060976602,
  "xdm:createdUserId": "user@techacct.adobe.com",
  "xdm:lastModifiedUserId": "user@techacct.adobe.com",
  "xdm:createdClientId": "...",
  "xdm:lastModifiedClientId": "..."
}
```

| Field | Meaning |
|---|---|
| `repo:createdDate` | Unix epoch ms — when the schema was first created |
| `repo:lastModifiedDate` | Unix epoch ms — when it was last modified |
| `xdm:createdUserId` | Technical account that created it |
| `xdm:lastModifiedUserId` | Technical account that last modified it |

Convert epoch ms to human-readable: `python -c "import datetime; print(datetime.datetime.fromtimestamp(1782060976602/1000))"`.

---

## Quick reference

| Op | Method & path | Accept / Body | State |
|---|---|---|---|
| 1. Delete | `DELETE /tenant/schemas/{URL_ENCODED_$id}` | — | **Destructive** |
| 2. List | `GET /tenant/schemas` | `Accept: …xed-id+json` | Read-only |
| 3. Display | `GET /tenant/schemas/{URL_ENCODED_$id}` | `Accept: …xed-full+json; version=1` | Read-only |
| 4. Create | `POST /tenant/schemas` | JSON body (adhoc-v2) | Creates state |
| 5. Relationships | `GET /tenant/schemas/{URL_ENCODED_$id}` | `Accept: …xed-full-desc+json; version=1` | Read-only |

Base URL: `https://platform.adobe.io/data/foundation/schemaregistry`.
**Confirm inputs and get approval before executing any operation.**
