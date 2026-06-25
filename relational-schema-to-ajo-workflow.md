# Pushing RELATIONAL Schemas to AJO — Full Workflow

A complete, standalone guide for pushing **relational (model-based) schemas** into Adobe Journey
Optimizer via the Adobe Experience Platform **Schema Registry** + **Identity Service** APIs. Covers
the input JSON, every step, every API call, authentication, and verification.

---

## 1. The big picture (in plain words)

AJO doesn't have its own schema store — it runs on **Adobe Experience Platform (AEP)** and reads the
schemas defined in AEP's **Schema Registry**. So "pushing a schema to AJO" means **creating it in the
Schema Registry**. For relational schemas, that means: create the schema and attach the descriptors
that make it relational (primary key, version, relationships).

A **relational schema** models structured, table-style data the way a relational database does:
distinct tables, each with an enforced primary key, linked to each other by foreign-key
relationships, joined at query time. This fits Adobe Campaign data well, because Campaign is
relational (linked recipient / delivery / transaction tables). Relational schemas are used by **AJO
Orchestrated Campaigns**, Data Mirror, and Data Distiller.

Key characteristics of relational schemas:
- **Fields are defined directly on the schema.** Every field path is a plain name like
  `/transactionId`.
- **An enforced primary key and a version field are mandatory.** Uniqueness is enforced at ingestion.
- **Relationships are explicit** — foreign key → primary key links between schemas, joined at query
  time.
- **The data lives in the data lake** and is resolved at query time.

**License gate:** relational schemas + Data Mirror require an **AJO Orchestrated Campaigns** license
(or the limited Customer Journey Analytics release).

```
Campaign console
      │  (schemas already extracted to JSON)
      ▼
Converted-schema JSON  ──►  YOUR PIPELINE  ──►  AEP Schema Registry  ──►  schema usable in AJO
                                                 (relational descriptors;
                                                  data-lake / query-time joins)
```

---

## 2. Authentication & setup

Every Schema Registry call needs the same headers:

| Value | Header | What it is |
|---|---|---|
| Access token | `Authorization: Bearer {ACCESS_TOKEN}` | Short-lived IMS bearer token. If stored encrypted, decrypt with your existing helper; refresh if expired. |
| API key / Client ID | `x-api-key: {API_KEY}` | From your Adobe Developer Console project. |
| Org ID | `x-gw-ims-org-id: {ORG_ID}` | IMS Organization ID (`XXXX@AdobeOrg`). |
| Sandbox | `x-sandbox-name: {SANDBOX_NAME}` | Which sandbox to write into. Schemas are isolated per sandbox. |
| Content type | `Content-Type: application/json` | On every POST / PUT / PATCH. |

**Base URLs:**
- Schema Registry: `https://platform.adobe.io/data/foundation/schemaregistry`
- Identity Service (only if you create identities — §8): region host
  `https://platform-va7.adobe.io` (this org's region).

**Fetch your `TENANT_ID` once** (used in every schema `$id`):

```bash
curl -X GET \
  https://platform.adobe.io/data/foundation/schemaregistry/stats \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}'
```

The response contains `"tenantId": "{TENANT_ID}"`. It's fixed for your org — fetch once, reuse
everywhere. (If your pipeline already resolves the tenant ID, skip this.)

> **Schema `$id` rule:** the schema `$id` returned on creation (e.g.
> `https://ns.adobe.com/{TENANT_ID}/schemas/{hash}`) is used everywhere. Use it **raw** in JSON
> bodies (e.g. `xdm:sourceSchema`); **URL-encode** it only when it goes into a path parameter.

---

## 3. What the input JSON must contain

A relational schema needs the following in its input definition. Per schema:

| Field | Required? | Why / used in |
|---|---|---|
| `title` | Yes | Schema name (e.g. "Loyalty Transactions"). → create call |
| `description` | Yes | What the table holds. → create call |
| `behavior` | Yes | `"record"` (default) or `"time-series"`. → create call |
| `fields` | Yes | Columns defined **directly** — each with `name`, `type`, and whether it's `required`. → create call |
| `primaryKey` | Yes | One field **or a list** (composite). Enforced unique + non-null; must be root-level and `required`. → primary-key descriptor |
| `versionField` | Yes | Field that tracks record version (datetime/number, e.g. `lastModified`). Must be `required`. → version descriptor |
| `timestampField` | Only if `time-series` | Date-time event field. For time-series the primary key **must include** it. → timestamp descriptor |
| `relationships` | As needed | List of links: `{ foreignKey, targetSchema, targetKey, cardinality }`. → relationship descriptors |

Rules:
- A field **cannot** be both the primary key and the version field.
- Field data types: `string`, `integer`, `number`, `boolean`, and `string` + `format: "date-time"`
  for dates.

Example input entry:

```json
{
  "title": "Loyalty Transactions",
  "description": "Transactions migrated from Adobe Campaign.",
  "behavior": "record",
  "fields": [
    { "name": "transactionId", "title": "Transaction ID", "type": "string",  "required": true },
    { "name": "customerId",    "title": "Customer ID (FK)", "type": "string" },
    { "name": "amount",        "title": "Amount", "type": "number" },
    { "name": "status",        "title": "Status", "type": "string" },
    { "name": "lastModified",  "title": "Last Modified", "type": "string", "format": "date-time", "required": true }
  ],
  "primaryKey": ["transactionId"],
  "versionField": "lastModified",
  "relationships": [
    { "foreignKey": "customerId", "targetSchema": "Loyalty Members", "targetKey": "crmId", "cardinality": "M:1" }
  ]
}
```

---

## 4. Step 1 — Create the relational schema

Create the schema with `POST /tenant/schemas`. The body has exactly three parts: `meta:extends` set
to the logical relational identifier `https://ns.adobe.com/xdm/data/adhoc-v2`, a `definitions` block
where the fields are defined **directly**, and an `allOf` that references that block.

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Content-Type: application/json' \
  -d '{
        "title": "Loyalty Transactions",
        "type": "object",
        "description": "Transactions migrated from Adobe Campaign.",
        "meta:extends": [ "https://ns.adobe.com/xdm/data/adhoc-v2" ],
        "definitions": {
          "customFields": {
            "type": "object",
            "properties": {
              "transactionId": { "title": "Transaction ID", "type": "string", "minLength": 1 },
              "customerId":    { "title": "Customer ID (FK)", "type": "string" },
              "amount":        { "title": "Amount", "type": "number" },
              "status":        { "title": "Status", "type": "string" },
              "lastModified":  { "title": "Last Modified", "type": "string", "format": "date-time" }
            },
            "required": [ "transactionId", "lastModified" ]
          }
        },
        "allOf": [ { "$ref": "#/definitions/customFields" } ]
      }'
```

Key points:
- **`meta:extends` is the same for every relational schema** — always exactly
  `["https://ns.adobe.com/xdm/data/adhoc-v2"]`. It's a fixed literal that marks the schema as
  relational; it does not change per schema. Only `title`, `description`, the fields, and (for
  time-series) `meta:behaviorType` vary.
- Fields live **directly** under `customFields.properties` — no `_{TENANT_ID}` nesting. So later
  paths are plain: `/transactionId`, `/customerId`, `/lastModified`.
- The primary-key field(s) and the version field must be listed in the `required` array.
- For **`time-series`** behavior, add `"meta:behaviorType": "time-series"` to the body (record is the
  default and needs nothing extra).

Successful response is **HTTP 201** with the schema identifiers:

```json
{
  "$id": "https://ns.adobe.com/{TENANT_ID}/schemas/ee56b80adc7e...",
  "version": "1.0",
  "title": "Loyalty Transactions"
}
```

**Carry the `$id` forward** — it feeds every descriptor below.

> **Duplicate prevention:** the title is the ACC `namespace:name` (the source-system schema namespace
> from Adobe Campaign — e.g. `cus:recipient` — which is **unrelated** to any AEP namespace; it's just
> used here as a unique title string). Because ACC `namespace:name` is unique, the title is a reliable
> dedup key. Before creating, check whether a schema with this title already exists
> (`GET /tenant/schemas`, scan titles):
> - **Title not found** → create the schema and continue.
> - **Title already exists** → do **not** create it. Skip this schema and report:
>   *"A schema with this title already exists in the Schema Registry."*

---

## 5. Step 2 — Primary-key descriptor (required)

Enforces uniqueness + non-null on the key. `xdm:sourceProperty` is a single path **or an array** for
a composite key. The key field(s) must be root-level and `required` (set in Step 1).

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "@type": "xdm:descriptorPrimaryKey",
        "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SCHEMA_ID}",
        "xdm:sourceProperty": [ "/transactionId" ]
      }'
```

> **`@type` is fixed for all schemas.** It names the descriptor type and is an Adobe-defined constant
> — `xdm:descriptorPrimaryKey` here, `xdm:descriptorVersion` (§6), `xdm:descriptorTimestamp` (§7),
> `xdm:descriptorIdentity` (§8), and `xdm:descriptorRelationship` (§9). Only `xdm:sourceSchema` (the
> schema `$id`) and `xdm:sourceProperty` (the field path) change per schema.
>
> **`xdm:sourceSchema`** is the full schema `$id` URI exactly as returned by the create call (§4),
> used **raw** — e.g. `https://ns.adobe.com/{TENANT_ID}/schemas/{hash}`. Don't URL-encode it (that's
> only for path parameters) and don't leave any `{...}` placeholder unsubstituted.

Composite key example: `"xdm:sourceProperty": ["/orderId", "/orderLineId"]`. For time-series the
composite key must include the timestamp field.

---

## 6. Step 3 — Version descriptor (required when a primary key exists)

Designates the field used to resolve out-of-order changes — when two records share a primary key, the
one with the higher version wins. Must point at a `required` datetime/number field.

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "@type": "xdm:descriptorVersion",
        "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SCHEMA_ID}",
        "xdm:sourceProperty": "/lastModified"
      }'
```

> `@type` (`xdm:descriptorVersion`) is fixed for all schemas. `xdm:sourceProperty` is **per-schema** —
> it's the path to *that* schema's version field (from the JSON's `versionField`), so it varies:
> `/lastModified` here, but it could be `/updatedAt`, `/versionNumber`, etc. for another schema.

---

## 7. Step 4 — Timestamp descriptor (time-series schemas only)

Only for schemas created with `"meta:behaviorType": "time-series"`. Points at a `required`
`date-time` field used to order events by occurrence. **Skip this step for `record` schemas.**

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "@type": "xdm:descriptorTimestamp",
        "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SCHEMA_ID}",
        "xdm:sourceProperty": "/eventTime"
      }'
```

> `@type` (`xdm:descriptorTimestamp`) is fixed for all schemas. `xdm:sourceProperty` is **per-schema** —
> it's the path to *that* schema's timestamp field (from the JSON's `timestampField`), so it varies:
> `/eventTime` here, but it could be `/occurredAt`, `/purchaseDate`, etc. for another schema.

---

## 8. Step 5 — Identity descriptor (optional)

Only if a field should be registered as an identity (for stitching / identity graph). Many relational
schemas don't need this — uniqueness comes from the primary key (Step 2), not from identity. Do this
only when the field genuinely represents a person/customer identifier you want recognized across
sources.

### 8a. Resolve the namespace

The descriptor references an identity namespace by its **`code`**. Since `identityNamespace` is not
in the input JSON, you derive it by matching the identity field's real-world type to a namespace.
Keep this mapping in your project **config** (not hardcoded), so it's easy to review and extend:

```json
{
  "namespaceMapping": {
    "email":      "Email",
    "phone":      "Phone",
    "customerId": "CRMID",
    "crmId":      "CRMID",
    "loyaltyId":  "LoyaltyId"
  },
  "defaultNamespace": "CRMID"
}
```

Resolution logic: normalize the identity field's name (lowercase, strip `_`/spaces), look it up in
`namespaceMapping`; if there's no match, fall back to `defaultNamespace` (a person business key
defaults to `CRMID`). A format-based signal (e.g. the field's `format: "email"`) can take priority
over the name when present.

### 8b. Check the namespace exists, create if missing (Identity Service API, region host)

```bash
# list namespaces — scan for a matching `code`
curl -X GET \
  'https://platform-va7.adobe.io/data/core/idnamespace/identities' \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}'
```

If no namespace has a `code` equal to your resolved code, create it (only then — namespaces can't be
deleted):

```bash
curl -X POST \
  'https://platform-va7.adobe.io/data/core/idnamespace/identities' \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "name": "Campaign CRM ID",
        "code": "CampaignCRMID",
        "description": "CRM identifier migrated from Adobe Campaign.",
        "idType": "CROSS_DEVICE"
      }'
```

**`idType`** classifies *what kind of thing the namespace identifies*, which controls how its values
behave in the identity graph (person-level identities are stronger and can be prioritized over
device/cookie ones). Pick the value that matches the field:

- `CROSS_DEVICE` — a **person-level** business key that follows the individual across devices (CRM ID,
  loyalty ID). **Default for a customer/person key** (e.g. `CRMID`).
- `EMAIL` — a person identifier that is an email address.
- `PHONE` — a person identifier that is a phone number.
- `COOKIE` — a browser/cookie identifier (device/browser-scoped, not a person).
- `DEVICE` — a device identifier such as a mobile ad ID (device-scoped, not a person).
- `NON_PEOPLE` — an identifier that doesn't represent a person at all (product ID, account ID, etc.).

`idType` is **locked once set** (and namespaces can't be deleted), so choose correctly. Your existing
`CRMID` / `LoyaltyId` are already `CROSS_DEVICE`, so in practice you'd reuse them rather than create
new ones.

### 8c. Create the identity descriptor

Path is a plain field name:

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "@type": "xdm:descriptorIdentity",
        "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SCHEMA_ID}",
        "xdm:sourceVersion": 1,
        "xdm:sourceProperty": "/customerId",
        "xdm:namespace": "CRMID",
        "xdm:property": "xdm:code"
      }'
```

> Field notes (this descriptor):
> - `@type` (`xdm:descriptorIdentity`) — fixed for all schemas.
> - `xdm:sourceSchema` — the schema `$id` (per schema). `xdm:sourceProperty` — the identity field
>   path (per schema). `xdm:namespace` — the namespace `code` resolved in §8a (per field).
> - `xdm:property` — pairs with how you give the namespace: use **`"xdm:code"`** when `xdm:namespace`
>   is a namespace **code** (the string, as here), or `"xdm:id"` if you used the namespace's numeric
>   ID. Since you reference namespaces by code throughout, this is always `"xdm:code"`.
>
> Note: uniqueness is handled by the primary-key descriptor (Step 2). Adding an identity here is
> separate and optional — it only registers the field for identity stitching.

---

## 9. Step 6 — Relationship descriptors (reconnect the linked tables)

This is the relational core. Each **foreign-key → target link** (a field in one schema whose value
identifies a **record** in another schema, matched on that schema's **key field** — like
`transactions.customerId → members.crmId`) is declared with **`xdm:descriptorRelationship`** (the recommended type for relational schemas — supports cardinality,
naming, and non-primary-key targets).

**Ordering — run this as a second pass.** A relationship references the **target schema's `$id`**, so
the target must already exist. Create all schemas (and their key/version descriptors) first, collect
every `$id`, then wire relationships.

Minimal (many-to-one):

```bash
curl -X POST \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -d '{
        "@type": "xdm:descriptorRelationship",
        "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SOURCE_SCHEMA_ID}",
        "xdm:sourceVersion": 1,
        "xdm:sourceProperty": "/customerId",
        "xdm:destinationSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{TARGET_SCHEMA_ID}",
        "xdm:cardinality": "M:1"
      }'
```

> **Both `xdm:destinationSchema` and `xdm:cardinality` are per-relationship, not fixed.**
> `xdm:destinationSchema` is the **target schema's `$id`** (resolved from the JSON's `targetSchema`),
> so it differs for each target table. `xdm:cardinality` describes that specific link's shape;
> `M:1` (many-to-one) is the common foreign-key case, but it can be `1:1`, `1:0`, or `M:0`.
> Example — on a `Loyalty Transactions` schema: the link `transactions.customerId → members.crmId`
> sets `xdm:destinationSchema` to the **Loyalty Members** `$id` with `M:1` (many transactions per
> member); a separate link `transactions.productId → products.productId` would use the **Products**
> `$id` (a different value), also `M:1`.

With explicit target field + display names (optional):

```json
{
  "@type": "xdm:descriptorRelationship",
  "xdm:sourceSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{SOURCE_SCHEMA_ID}",
  "xdm:sourceVersion": 1,
  "xdm:sourceProperty": "/customerId",
  "xdm:destinationSchema": "https://ns.adobe.com/{TENANT_ID}/schemas/{TARGET_SCHEMA_ID}",
  "xdm:destinationProperty": "/crmId",
  "xdm:sourceToDestinationName": "TransactionToCustomer",
  "xdm:destinationToSourceName": "CustomerToTransaction",
  "xdm:sourceToDestinationTitle": "Transaction customer",
  "xdm:destinationToSourceTitle": "Customer transactions",
  "xdm:cardinality": "M:1"
}
```

Field notes:
- `xdm:sourceProperty` — the foreign-key field. **Must be at root level** — i.e. a top-level field
  with a single-segment path like `/customerId`, **not** nested inside a sub-object (not
  `/billing/customerId`). This is a current ingestion limitation, not just a best practice.
- `xdm:destinationSchema` — the target schema `$id` (resolved from `targetSchema` after creation).
- `xdm:destinationProperty` — optional; the target field (its primary/candidate key). Best to set it
  explicitly; if omitted the relationship may not resolve as expected. (The root-level requirement
  above is documented for the **source** FK; the destination is normally the target's primary key,
  which must be root-level anyway — so in practice this is root-level too.)
- `xdm:cardinality` — `<source>:<destination>`; accepted: `1:1`, `1:0`, `M:1`, `M:0`. **Informational
  only** — not enforced at ingestion. Source and destination data types must be compatible.
- `xdm:sourceToDestinationName` / `xdm:destinationToSourceName` (technical names) and
  `xdm:sourceToDestinationTitle` / `xdm:destinationToSourceTitle` (display titles) — **optional**
  labels for the relationship in each direction. They're **per-relationship** (different for every
  link), so you'd set them to describe that specific link (e.g. "Transaction customer" one way,
  "Customer transactions" the other). Omit all four and the relationship still works, keyed on the
  fields — these only add readable naming.

---

## 10. The schema is complete after its descriptors

Once the primary-key, version, (timestamp,) and relationship descriptors are attached, the relational
schema is complete. Its data lives in the data lake and is resolved at query time, so there is no
further enablement step. Do **not** add a `union` tag to `meta:immutableTags`.

---

## 11. Step 7 — Verify

Confirm the schema and its descriptors were created (read-only).

**Schema exists** — list and scan for your titles, or GET by `$id`:

```bash
curl -X GET \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/schemas \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Accept: application/vnd.adobe.xed-id+json'
```

This lists **all of your tenant's (custom) schemas** — with the `xed-id+json` header each entry
returns `title`, `$id`, `version`, and `meta:altId`. So you scan the `title`s for the one you're
checking, and each entry also carries its `$id` if you need it.

**Descriptors attached** — list descriptors. Note: the `/descriptors` endpoint uses **different**
`Accept` headers (`xdm`, not `xed`):

```bash
curl -X GET \
  https://platform.adobe.io/data/foundation/schemaregistry/tenant/descriptors \
  -H 'Authorization: Bearer {ACCESS_TOKEN}' \
  -H 'x-api-key: {API_KEY}' \
  -H 'x-gw-ims-org-id: {ORG_ID}' \
  -H 'x-sandbox-name: {SANDBOX_NAME}' \
  -H 'Accept: application/vnd.adobe.xdm-link+json'
```

`Accept` options for the **descriptors** list (these return your *descriptors*, not schemas):
`application/vnd.adobe.xdm-id+json` (descriptor IDs — each descriptor's `@id`),
`application/vnd.adobe.xdm-link+json` (descriptor API paths), `application/vnd.adobe.xdm+json` (full
descriptor objects). The response is grouped by descriptor type
(`xdm:descriptorPrimaryKey`, `xdm:descriptorVersion`, `xdm:descriptorRelationship`, …), so you can
confirm each descriptor got attached. To instead see a **schema** with its descriptors resolved, GET
the schema with `Accept: application/vnd.adobe.xed-full-desc+json; version=1`.

---

## 12. The full sequence (mapped-out flow)

```
ONE-TIME SETUP
  0. (auth) ACCESS_TOKEN, API_KEY, ORG_ID, SANDBOX_NAME
  1. GET /stats → TENANT_ID            (skip if pipeline already does it)

PASS 1 — create each schema and its own descriptors:
FOR EACH SCHEMA IN THE INPUT JSON:
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 1. GET /tenant/schemas — title exists? → skip + report "already exists"│
  │                          not found? → continue                         │
  │ 2. POST /tenant/schemas  (meta:extends adhoc-v2, fields direct)        │
  │       → SCHEMA $id                                                      │
  │ 3. POST /tenant/descriptors  xdm:descriptorPrimaryKey   (required)     │
  │ 4. POST /tenant/descriptors  xdm:descriptorVersion      (required)     │
  │ 5. POST /tenant/descriptors  xdm:descriptorTimestamp    (time-series)  │
  │ 6. POST /tenant/descriptors  xdm:descriptorIdentity     (optional;     │
  │       resolve namespace → check/create on region host → descriptor)    │
  │    (NO union tag)                                                      │
  └──────────────────────────────────────────────────────────────────────┘
  → record each schema title → $id in a lookup map

PASS 2 — after all schemas exist and all $ids are known:
FOR EACH RELATIONSHIP:
  ┌──────────────────────────────────────────────────────────────────────┐
  │ 7. POST /tenant/descriptors  xdm:descriptorRelationship                │
  │       sourceProperty = FK (root level),                                │
  │       destinationSchema = target $id (from the map), cardinality       │
  └──────────────────────────────────────────────────────────────────────┘

VERIFY:
  8. GET /tenant/schemas (scan titles) and GET /tenant/descriptors
```

### Dependency chain

```
TENANT_ID ─────────────────────────────────────────────────┐
                                                            ▼
JSON ──► create body (meta:extends adhoc-v2) ──POST──► SCHEMA $id ──┐
                                                                   ├─► primary-key descriptor (POST)
JSON (primaryKey)  ────────────────────────────────────────────────┤
JSON (versionField) ───────────────────────────────────────────────┤─► version descriptor (POST)
JSON (timestampField, if time-series) ──────────────────────────────┤─► timestamp descriptor (POST)
JSON (identityNamespace, optional) ──► namespace check/create ──────┤─► identity descriptor (POST)
                                                                   │
all SCHEMA $ids (map)  +  JSON (relationships) ─────────────────────┘─► relationship descriptors (PASS 2)
```

---

## 13. Quick reference — endpoints used

| Step | Method & path | Purpose |
|---|---|---|
| Setup | `GET /stats` | Get `TENANT_ID`. |
| 1 | `GET /tenant/schemas` | Duplicate check — if a schema with this title exists, skip and report; otherwise create. |
| 2 | `POST /tenant/schemas` | Create relational schema (`meta:extends` adhoc-v2, direct fields); returns `$id`. |
| 3 | `POST /tenant/descriptors` (`xdm:descriptorPrimaryKey`) | Enforce primary key (single or composite). |
| 4 | `POST /tenant/descriptors` (`xdm:descriptorVersion`) | Version field for out-of-order handling. |
| 5 | `POST /tenant/descriptors` (`xdm:descriptorTimestamp`) | Time-series only — event-time field. |
| 6 | `GET`/`POST` `/idnamespace/identities` (Identity Service, region host) | Resolve/check/create namespace (only if doing identity). |
| 6 | `POST /tenant/descriptors` (`xdm:descriptorIdentity`) | Optional identity on a field. |
| 7 | `POST /tenant/descriptors` (`xdm:descriptorRelationship`) | Link FK → target schema (PASS 2). |
| 8 | `GET /tenant/schemas` / `GET /tenant/descriptors` | Verify creation. |

Schema Registry base: `https://platform.adobe.io/data/foundation/schemaregistry`. Identity Service:
region host `https://platform-va7.adobe.io/data/core/idnamespace`.

---

## 14. Gotchas & practical notes

- **`meta:extends` = adhoc-v2** is what makes the schema relational. The body contains only
  `meta:extends`, your `definitions`, and an `allOf` referencing them.
- **Plain field paths** — fields are defined directly, so all descriptor paths are plain
  (`/fieldName`), starting with `/`, never including `properties`.
- **Primary key + version are mandatory**; an attribute can't be both. The PK and version fields must
  be in the schema's `required` array.
- **Foreign keys must be root-level** (ingestion limitation) — keep relationship source fields at the
  top level.
- **Relationships are a second pass** — the target schema must exist first; you need its `$id`.
- **Cardinality is informational** — not enforced at ingestion; clean your data yourself.
- **No `union` tag** — do not add it; the schema is complete after its descriptors.
- **Descriptor `Accept` headers differ** — use `xdm-*` (not `xed-*`) when listing descriptors.
- **`$id` usage** — raw in JSON bodies, URL-encoded only in path parameters.
- **Duplicate prevention** — the title is the ACC `namespace:name` (Campaign's source-system
  namespace, not an AEP namespace), which is unique; check by title before creating, and if a schema
  with that title already exists, skip it and report "already exists" rather than creating a second
  one.
- **`_change_request_type`** is a CDC ingestion column, not part of the schema.
- **Max 4000 descriptors per sandbox.**
- **License-gated** — Orchestrated Campaigns (or limited CJA).
- **Alternative creation path** — for Orchestrated Campaigns you can also create relational schemas by
  uploading a **DDL file** in the UI (defines tables, keys, relationships in bulk, and supports the
  `_change_request_type` CDC column). The API flow above is the programmatic equivalent.
- **After schemas exist** (out of scope here) — create datasets from them and ingest data (Data
  Mirror / CDC) to actually use them in Orchestrated Campaigns.

---

## 15. Sources (Adobe official docs)

- Relational schemas (technical reference) — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/schema/relational
- Model-based schemas — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/schema/model-based
- Schemas API endpoint (create a relational schema; `meta:extends` adhoc-v2) — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/api/schemas
- Descriptors API (primary key / version / timestamp / relationship / identity payloads) — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/api/descriptors
- Define a relationship between two schemas (API) — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/tutorials/relationship-api
- Data Mirror overview — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/data-mirror/overview
- Orchestrated Campaigns — relational schemas via DDL — https://experienceleague.adobe.com/en/docs/journey-optimizer/using/campaigns/orchestrated-campaigns/data-configuration/schemas-datasets/file-upload-schema
- Orchestrated Campaigns — manual relational schema — https://experienceleague.adobe.com/en/docs/journey-optimizer/using/campaigns/orchestrated-campaigns/data-configuration/schemas-datasets/manual-schema
- Schema Registry API — getting started (headers, `/stats`, Accept headers) — https://experienceleague.adobe.com/en/docs/experience-platform/xdm/api/getting-started
