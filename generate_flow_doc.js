const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, BorderStyle, WidthType, ShadingType,
  PageNumber, PageBreak, LevelFormat
} = require("docx");
const fs = require("fs");

const ADOBE_RED = "EB1000";
const DARK_GREY = "1F1F1F";
const MID_GREY  = "444444";
const CODE_BG   = "F0F0F0";
const WHITE     = "FFFFFF";
const STRIPE    = "F9F9F9";

function h1(text) {
  return new Paragraph({
    spacing: { before: 320, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: ADOBE_RED, space: 4 } },
    children: [new TextRun({ text, bold: true, size: 36, color: ADOBE_RED, font: "Arial" })]
  });
}
function h2(text) {
  return new Paragraph({
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, size: 28, color: DARK_GREY, font: "Arial" })]
  });
}
function h3(text) {
  return new Paragraph({
    spacing: { before: 180, after: 60 },
    children: [new TextRun({ text, bold: true, size: 24, color: MID_GREY, font: "Arial" })]
  });
}
function body(text, italic = false) {
  return new Paragraph({
    spacing: { after: 80 },
    children: [new TextRun({ text, size: 22, color: MID_GREY, font: "Arial", italics: italic })]
  });
}
function note(text) {
  return new Paragraph({
    spacing: { after: 80 },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: ADOBE_RED, space: 8 } },
    indent: { left: 200 },
    children: [new TextRun({ text, size: 20, color: MID_GREY, font: "Arial", italics: true })]
  });
}
function spacer() {
  return new Paragraph({ spacing: { after: 80 }, children: [new TextRun("")] });
}
function divider() {
  return new Paragraph({
    spacing: { before: 160, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 1 } },
    children: [new TextRun("")]
  });
}
function codeBlock(text) {
  return text.split("\n").map(line =>
    new Paragraph({
      spacing: { before: 20, after: 20 },
      indent: { left: 360 },
      shading: { type: ShadingType.CLEAR, fill: CODE_BG },
      children: [new TextRun({ text: line === "" ? " " : line, font: "Courier New", size: 18, color: "1A1A1A" })]
    })
  );
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 40 },
    children: [new TextRun({ text, size: 21, color: MID_GREY, font: "Arial" })]
  });
}
const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: "DDDDDD" };
const allBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };
function headerCell(text, width) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: DARK_GREY },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    borders: allBorders,
    children: [new Paragraph({ children: [new TextRun({ text, bold: true, size: 20, color: WHITE, font: "Arial" })] })]
  });
}
function dataCell(text, width, shade = WHITE) {
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, fill: shade },
    margins: { top: 80, bottom: 80, left: 120, right: 120 },
    borders: allBorders,
    children: [new Paragraph({ children: [new TextRun({ text: String(text), size: 20, color: MID_GREY, font: "Arial" })] })]
  });
}
function makeTable(headers, rows, colWidths) {
  const total = colWidths.reduce((a, b) => a + b, 0);
  return [
    new Table({
      width: { size: total, type: WidthType.DXA },
      columnWidths: colWidths,
      rows: [
        new TableRow({ children: headers.map((h, i) => headerCell(h, colWidths[i])) }),
        ...rows.map((row, ri) => new TableRow({
          children: row.map((cell, ci) => dataCell(cell, colWidths[ci], ri % 2 === 0 ? WHITE : STRIPE))
        }))
      ]
    }),
    spacer()
  ];
}

const children = [];

// TITLE PAGE
children.push(
  new Paragraph({ spacing: { before: 2400, after: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "ACC → AJO Migration Tool", bold: true, size: 56, color: ADOBE_RED, font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Authentication & Extraction Flow — Final Version", size: 32, color: MID_GREY, font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "From Login to Raw JSON Committed in DB", size: 24, italics: true, color: "888888", font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "June 2026  |  Internal Developer Reference", size: 22, color: "AAAAAA", font: "Arial" })] }),
  new Paragraph({ children: [new PageBreak()] })
);

// ── 1. ACC LOGIN ──────────────────────────────────────────────────────────────
children.push(h1("1.  ACC Login — User Fills Form and Clicks Connect"));
children.push(h2("1.1  Frontend Call"));
children.push(...codeBlock(
`AccPanel handleConnect()                      [components/AccPanel.tsx]
  └── accConnect({auth_type, instance_url, ...})
        [api/client.ts]
        └── POST /api/acc/connect`));
children.push(spacer());

children.push(h2("1.2  Classic Auth — routes/auth.py → acc_connect()"));
children.push(...codeBlock(
`POST /api/acc/connect  (auth_type = "classic")
  │
  ├── build_logon_envelope(login, password)
  │     → xtk:session#Logon SOAP XML
  │
  ├── POST {instance_url}/nl/jsp/soaprouter.jsp   [httpx]
  │     SOAPAction: xtk:session#Logon
  │
  ├── parse_logon_response(xml) → session_token, security_token
  │
  ├── build_test_cnx_envelope(session_token, security_token)
  ├── POST /nl/jsp/soaprouter.jsp
  │     SOAPAction: xtk:session#TestCnx  ← verifies session is live
  │
  ├── upsert SourceConnection in DB
  │     login_id, auth_type="classic", session_token, security_token, encrypted_password
  │
  ├── create UserSession in DB (expires_at = now + 7 days)
  └── set cookies: acc_session = UUID, acc_user = login`));
children.push(spacer());

children.push(h2("1.3  Technical Auth (IMS) — routes/auth.py → acc_connect()"));
children.push(...codeBlock(
`POST /api/acc/connect  (auth_type = "technical")
  │
  ├── POST https://ims-na1.adobelogin.com/ims/token/v3
  │     grant_type=client_credentials → access_token, expires_in
  │
  │   <- No SOAP call to ACC at login time.
  │      The IMS access_token is used directly as Bearer on every SOAP request.
  │
  ├── upsert SourceConnection in DB
  │     login_id               = client_id
  │     auth_type              = "technical"
  │     instance_url           = body.instance_url
  │     encrypted_credentials  = Fernet("client_id:client_secret")
  │     encrypted_access_token = Fernet(access_token)   <- IMS token stored here
  │     token_expires_at       = now + expires_in
  │     (no session_token or security_token stored)
  │
  ├── create UserSession in DB
  └── set cookies: acc_session = UUID, acc_user = client_id`));
children.push(spacer());

children.push(h2("1.4  What Is Stored in DB After ACC Login"));
children.push(...makeTable(
  ["Column", "Classic", "Technical"],
  [
    ["login_id",                "username",               "client_id"],
    ["auth_type",               "\"classic\"",             "\"technical\""],
    ["session_token",           "SOAP session token",      "(not used)"],
    ["security_token",          "SOAP security token",     "(not used)"],
    ["encrypted_access_token",  "(not used)",              "Fernet(IMS access_token)"],
    ["encrypted_credentials",   "(not used)",              "Fernet(\"client_id:client_secret\")"],
    ["token_expires_at",        "null",                    "IMS token expiry timestamp"],
    ["encrypted_password",      "Fernet(password)",        "(not used)"],
  ],
  [3800, 2600, 2960]
));
children.push(divider());

// ── 2. AJO LOGIN ──────────────────────────────────────────────────────────────
children.push(h1("2.  AJO Login — User Fills Form and Clicks Connect"));
children.push(...codeBlock(
`POST /api/ajo/connect
  │
  ├── POST https://ims-na1.adobelogin.com/ims/token/v3
  │     grant_type=client_credentials → access_token, expires_in
  │
  ├── derive tenant_id = "_" + org_id.split("@")[0].lower()
  │
  ├── upsert DestinationConnection in DB
  │     org_id, tenant_id, client_id, sandbox_name,
  │     encrypted_credentials = Fernet("client_id:client_secret"),
  │     encrypted_access_token = Fernet(access_token),
  │     token_expires_at = now + expires_in
  │
  └── returns {success, expires_in}

→ setAjoConnected(orgId, sandboxName)   [configStore]`));
children.push(divider());

// ── 3. SESSION VERIFICATION ───────────────────────────────────────────────────
children.push(h1("3.  Session & Token Management"));

children.push(h2("3.1  get_login_from_cookie() — core/security.py"));
children.push(body("Called by every protected route to identify the current user."));
children.push(...codeBlock(
`acc_session cookie → look up UserSession WHERE id = cookie AND expires_at > now
  │
  ├── found:
  │     session.expires_at = now + 7 days   ← ROLLING TTL resets on every request
  │     await db.commit()
  │     return session.login_id
  │
  └── not found → return None → route raises HTTP 401
        (no acc_user fallback — valid session always required)`));
children.push(spacer());

children.push(h2("3.2  get_valid_acc_token() — core/security.py"));
children.push(body("Called before every SOAP request to guarantee a fresh, working token. Returns a plain token string — no branch needed in callers."));
children.push(...codeBlock(
`get_valid_acc_token(conn, db)
  │
  ├── auth_type == "classic":
  │     session_expires_at > now + 60s → return conn.session_token
  │     expired / missing →
  │       decrypt password → build_logon_envelope → POST SOAP Logon
  │       parse new session_token + security_token → update DB → return
  │
  └── auth_type == "technical":
        token_expires_at > now + 60s →
          decrypt conn.encrypted_access_token → return IMS access_token
        expired →
          decrypt encrypted_credentials → split client_id, client_secret
          POST IMS token/v3 → new access_token + expires_in
          update conn.encrypted_access_token + conn.token_expires_at in DB
          return new access_token

        <- No SOAP call to ACC. IMS access_token IS the token returned.`));
children.push(spacer());

children.push(h2("3.3  acc_soap_headers() — core/security.py"));
children.push(...makeTable(
  ["auth_type", "Headers sent with every SOAP call"],
  [
    ["classic",   "Cookie: __sessiontoken=<token>  |  X-Security-Token: <sec_token>"],
    ["technical", "Authorization: Bearer <ims_access_token>   (no X-Security-Token)"],
  ],
  [2400, 6960]
));
children.push(divider());

// ── 4. SCHEMA LIST ────────────────────────────────────────────────────────────
children.push(h1("4.  Schema List — MigrationSelectPage Mounts"));
children.push(body("On mount, 5 API calls fire in parallel via Promise.all."));

children.push(h2("4.1  Call 1 — getSchemas() → GET /api/acc/schemas"));
children.push(...codeBlock(
`routes/schemas.py → list_schemas()
  │
  ├── get_login_from_cookie() → login_id
  ├── fetch SourceConnection → conn
  ├── get_valid_acc_token(conn, db) → fresh session_token
  │
  ├── build_list_schemas_envelope(session_token, security_token)
  │     → xtk:queryDef#ExecuteQuery, lineCount="9999"
  │
  ├── POST soap_url with acc_soap_headers()
  ├── guard: 403 or "Session has expired" → raise HTTP 401
  ├── parse_schemas(resp.text) → [{namespace, name, label}, ...]
  └── filter SYSTEM_NAMESPACES → custom schemas only

→ setSchemas()`));
children.push(spacer());

children.push(h2("4.2  Calls 2–5 (parallel)"));
children.push(...makeTable(
  ["Call", "Endpoint", "Returns", "Used for"],
  [
    ["getExtractedSchemas()",  "GET /api/convert/extracted",   "schema names in DB",                  "Green checkmarks"],
    ["getIncompleteSchemas()", "GET /api/migrate/incomplete",  "RUNNING/FAILED/QUEUED schemas",       "Step X badges"],
    ["getPushedSchemas()",     "GET /api/migrate/completed",   "COMPLETED schema names",              "Pushed to AJO badge"],
    ["getSchemaDependencies()","GET /api/schemas/dependencies","FK dependency graph",                  "Auto-lock dependent schemas"],
  ],
  [3600, 3600, 3200, 3600]  // won't fit well, will just use reasonable widths
));

children.push(h2("4.3  Schema Dependency Resolution"));
children.push(body("When a schema is selected, its FK dependencies are automatically included and shown as locked in the UI."));
children.push(...codeBlock(
`GET /api/schemas/dependencies
  [routes/schemas.py → get_schema_dependencies()]
  │
  ├── load all extracted schemas from DB
  ├── for each: parse linksAndJoins from raw_json
  │     → concurrent SOAP fetch for each linked schema
  └── returns {dependencies: {schema_name: [linked_schema_names]}}

→ dependent schemas: locked in sidebar + auto-included on parent select`));
children.push(divider());

// ── 5. SCHEMA DETAIL ──────────────────────────────────────────────────────────
children.push(h1("5.  Schema Detail Expand — User Clicks a Schema Row"));
children.push(...codeBlock(
`toggleExpand(schema)                          [MigrationSelectPage.tsx]
  └── fetchDetail(schema)
        guard: already loaded or loading → skip (no double fetch)
        │
        └── GET /api/acc/schemas/{namespace}/{name}
              [routes/schemas.py → inspect_schema()]
              │
              ├── get_valid_acc_token() → fresh token
              ├── build_srcschema_get_envelope(...)
              │     → xtk:srcSchema#Get SOAP XML
              ├── POST soap_url
              ├── parse_fault() → HTTP 400 if SOAP error
              └── parse_schema_preview(resp.text, namespace, name)
                    [services/schema_preview.py]  ← LIGHTWEIGHT PARSER
                    → attributes: [{name, type, label}]
                    → keys: {autoPk, primaryKeys, uniqueKeys}
                    → links: [{name, target, label}]    ← NEW in final version
                    → NOT stored in DB
                    → returns {namespace, name, label, attributes, keys, links}

→ renders SchemaDetailCard: fields table + PK badge + FK/link badges`));
children.push(spacer());

children.push(...makeTable(
  ["", "parse_schema_preview", "parse_schema_to_xdm"],
  [
    ["File",         "services/schema_preview.py",                "services/schema_inspector.py"],
    ["Returns",      "{attributes, keys, links} — UI only",       "Full dict: enums, linksAndJoins, rootElement, etc."],
    ["Stored in DB", "No",                                         "Yes — ConvertedSchema.raw_json"],
    ["Triggered by", "User clicking row to expand",               "User clicking Migrate →"],
  ],
  [2400, 4000, 3960]
));
children.push(divider());

// ── 6. MIGRATION TYPE PAGE ────────────────────────────────────────────────────
children.push(h1("6.  Migration Type Selection (New Step)"));
children.push(body("After clicking Migrate on ConfigPage, users now choose between two migration types."));
children.push(...codeBlock(
`ConfigPage → "Migrate" button
  → navigate('/migration/type')     [MigrationTypePage.tsx]

  ┌──────────────────┐   ┌──────────────────┐
  │  Schema          │   │  Template        │
  │  Migration       │   │  Migration       │
  └──────────────────┘   └──────────────────┘
         ↓                       ↓
  /migration/select        /migration/template`));
children.push(divider());

// ── 7. MIGRATE BUTTON ─────────────────────────────────────────────────────────
children.push(h1("7.  User Selects Schemas and Clicks \"Migrate →\""));
children.push(h2("7.1  handleNext() — Frontend"));
children.push(...codeBlock(
`handleNext()                                  [MigrationSelectPage.tsx]
  │
  ├── chosen = selected schemas
  │
  ├── CHECK: allAlreadyExtracted = chosen.every(s => extracted.has(key(s)))
  │     if TRUE  → startMigration()  POST /api/migrate/start
  │                → navigate('/migration/run?migrate_job=...')  (retry path)
  │
  └── if FALSE → startConversion(chosen)  POST /api/convert/start
                  → navigate('/migration/run?extract_job=...')`));
children.push(spacer());

children.push(h2("7.2  Backend — routes/conversion.py → convert_start()"));
children.push(...codeBlock(
`POST /api/convert/start
  body: {schemas: [{namespace, name, label}, ...]}
  │
  ├── get_login_from_cookie() → login_id
  ├── fetch SourceConnection → acc conn
  ├── get_valid_acc_token(acc, db) → token refreshed before job starts
  │
  ├── query ConvertedSchema WHERE login_id = current
  │     → already_done = set of schema_names already in DB
  │
  ├── schemas_to_run = requested - already_done
  ├── if empty → return {message: "all_done"}
  │
  ├── _jobs[job_id] = {status: "pending", schema_count, steps: [], ...}
  └── asyncio.create_task(_run_conversion_job(...))   ← NON-BLOCKING

→ returns {job_id, message: "started"}
→ navigate('/migration/run?extract_job={job_id}')`));
children.push(divider());

// ── 8. EXTRACTION JOB ─────────────────────────────────────────────────────────
children.push(h1("8.  Extraction Background Job — Raw JSON Committed to DB"));
children.push(body("Runs after the HTTP response has been returned. Processes schemas sequentially."));
children.push(...codeBlock(
`_run_conversion_job(job_id, schemas, acc_conn, login_id)
                                              [routes/conversion.py]
  │
  for each schema in schemas (SEQUENTIAL):
    │
    ├── get_valid_acc_token(acc_conn, db)    ← per-schema token refresh
    │
    ├── build_srcschema_get_envelope(session_token, security_token, namespace, name)
    │     [services/acc_soap.py] → xtk:srcSchema#Get SOAP XML
    │
    ├── POST soap_url with acc_soap_headers()    [httpx]
    │     → response = full raw XML of the schema
    │
    ├── parse_fault(resp.text)
    │     → SOAP error → ValueError → schema marked failed, continue to next
    │
    ├── parse_schema_to_xdm(resp.text, namespace, name)
    │     [services/schema_inspector.py]   ← FULL PARSER
    │     → parses complete XML
    │     → extracts:
    │         source         (namespace:name)
    │         rootElement    (main element name)
    │         attributes     [{name, type, label, nullable, required, ...}]
    │         keys           {autoPk, primaryKeys, uniqueKeys}
    │         linksAndJoins  [{name, target, type, cardinality, ...}]
    │         enums          [{name, values: [{value, label}]}]
    │     → returns fully structured dict
    │
    ├── async with AsyncSessionLocal() as db_session:
    │     db_session.add(ConvertedSchema(
    │       job_id      = job_id,
    │       login_id    = login_id,
    │       schema_name = "namespace:name",
    │       raw_json    = json.dumps(parsed)
    │     ))
    │     await db_session.commit()        ← COMMITTED TO DB HERE ✓
    │
    └── success_count += 1

  job["status"] = "completed"
  ← frontend polling auto-triggers 14-step migration pipeline`));
children.push(spacer());

children.push(h2("8.1  What Is Stored in DB at End of Extraction"));
children.push(...makeTable(
  ["Table", "Column", "Value"],
  [
    ["ConvertedSchema", "id",           "UUID (primary key)"],
    ["ConvertedSchema", "job_id",       "UUID of this extraction run"],
    ["ConvertedSchema", "login_id",     "User who triggered extraction"],
    ["ConvertedSchema", "schema_name",  "\"namespace:name\""],
    ["ConvertedSchema", "raw_json",     "Full parsed JSON from parse_schema_to_xdm"],
    ["ConvertedSchema", "enriched_json","null — filled by migration pipeline"],
  ],
  [3000, 2800, 3560]
));
children.push(note("End of scope. The 14-step migration pipeline reads raw_json from DB and is a separate flow."));
children.push(divider());

// ── 9. API ROUTES ─────────────────────────────────────────────────────────────
children.push(h1("9.  API Routes Reference"));

children.push(h2("9.1  Auth"));
children.push(...makeTable(
  ["Method", "Path", "Description"],
  [
    ["POST", "/api/acc/connect",       "Classic (SOAP Logon) or Technical (IMS client_credentials, Bearer token stored)"],
    ["POST", "/api/acc/disconnect",    "Clear session cookies + DB session"],
    ["GET",  "/api/acc/status",        "{connected, login}"],
    ["POST", "/api/ajo/connect",       "IMS client_credentials, store tokens"],
    ["GET",  "/api/ajo/status",        "{connected, org_id, sandbox_name}"],
    ["GET",  "/api/connections/status","Combined ACC + AJO status"],
  ],
  [1600, 5200, 6560]
));

children.push(h2("9.2  Schemas"));
children.push(...makeTable(
  ["Method", "Path", "Description"],
  [
    ["GET", "/api/acc/schemas",              "List custom schemas from ACC"],
    ["GET", "/api/acc/schemas/{ns}/{name}",  "Lightweight preview (attributes + keys + links)"],
    ["GET", "/api/schemas/dependencies",     "FK dependency graph across extracted schemas"],
  ],
  [1600, 5200, 6560]
));

children.push(h2("9.3  Conversion"));
children.push(...makeTable(
  ["Method", "Path", "Description"],
  [
    ["POST", "/api/convert/start",           "Extract selected schemas to DB"],
    ["POST", "/api/convert/start-all",       "Extract all custom schemas"],
    ["GET",  "/api/convert/status/{job_id}", "Poll extraction progress (in-memory)"],
    ["GET",  "/api/convert/extracted",       "Schema names already in DB"],
  ],
  [1600, 5200, 6560]
));

children.push(h2("9.4  Migration"));
children.push(...makeTable(
  ["Method", "Path", "Description"],
  [
    ["POST", "/api/migrate/start",             "Start 14-step pipeline"],
    ["GET",  "/api/migrate/status/{job_id}",   "Poll migration progress (DB)"],
    ["GET",  "/api/migrate/jobs",              "All job IDs for current user"],
    ["GET",  "/api/migrate/incomplete",        "Schemas in RUNNING/FAILED/QUEUED"],
    ["GET",  "/api/migrate/completed",         "Schemas fully pushed to AJO"],
    ["GET",  "/api/migrate/schema/{item_id}",  "Single schema item detail"],
  ],
  [1600, 5200, 6560]
));

children.push(h2("9.5  Templates (New in Final Version)"));
children.push(...makeTable(
  ["Method", "Path", "Description"],
  [
    ["GET",    "/api/templates/count",              "Count delivery templates in ACC"],
    ["GET",    "/api/templates/stored-count",       "Count templates already in DB"],
    ["POST",   "/api/templates/extract",            "Extract ACC templates to DB"],
    ["DELETE", "/api/templates/stored",             "Clear stored templates"],
    ["GET",    "/api/templates/folder-config",      "AJO folder IDs per channel"],
    ["POST",   "/api/templates/setup",              "Discover folder IDs from sample template names"],
    ["GET",    "/api/templates/analysis",           "Scan placeholders across all templates"],
    ["POST",   "/api/templates/migrate",            "Start template migration run"],
    ["GET",    "/api/templates/runs/{id}/status",   "Poll template migration progress"],
  ],
  [1600, 5200, 6560]
));
children.push(divider());

// ── 10. KEY DIFFERENCES ───────────────────────────────────────────────────────
children.push(h1("10.  Key Differences vs Previous Version"));
children.push(...makeTable(
  ["Area", "Previous Version", "Final Version"],
  [
    ["Technical ACC auth",   "Stored IMS token as session_token — expired silently",    "IMS access_token stored as encrypted_access_token; used directly as Authorization: Bearer on SOAP calls"],
    ["Token management",     "refresh_acc_token_if_needed() — separate helper",        "Unified get_valid_acc_token() — handles classic re-logon AND technical IMS refresh"],
    ["SOAP headers",         "Hardcoded Cookie + X-Security-Token",                    "acc_soap_headers() returns correct headers per auth_type"],
    ["Schema detail",        "Returns attributes + keys",                              "Returns attributes + keys + links (FK relationships)"],
    ["Schema dependencies",  "Not present",                                            "GET /api/schemas/dependencies — FK graph, auto-includes dependents"],
    ["Migration type screen","Direct to schema select",                                "New MigrationTypePage — choose Schema OR Template migration"],
    ["Pipeline steps",       "5 steps",                                                "14 steps across 2 passes"],
    ["Template migration",   "Not present",                                            "Full flow: extract → placeholder conversion → AJO push"],
    ["Pushed tracking",      "Not present",                                            "GET /api/migrate/completed + getPushedSchemas()"],
  ],
  [3000, 3800, 4560]  // reduced to fit
));

// BUILD
const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
    }]
  },
  styles: { default: { document: { run: { font: "Arial", size: 22 } } } },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
        children: [new TextRun({ text: "ACC → AJO Migration Tool  |  Auth & Extraction Flow (Final)", size: 18, color: "888888", font: "Arial" })]
      })] })
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT,
        children: [
          new TextRun({ text: "Page ", size: 18, color: "888888", font: "Arial" }),
          new TextRun({ children: [PageNumber.CURRENT], size: 18, color: "888888", font: "Arial" }),
          new TextRun({ text: " of ", size: 18, color: "888888", font: "Arial" }),
          new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: "888888", font: "Arial" }),
        ]
      })] })
    },
    children
  }]
});

const out = "C:\\Users\\pavitram\\Desktop\\accTOajo\\final\\ACCtoAJO\\ACC_to_AJO_Auth_Extraction_Flow_Final.docx";
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(out, buf); console.log("Saved:", out); });
