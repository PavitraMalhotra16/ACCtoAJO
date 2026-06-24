const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, LevelFormat, TableOfContents,
  PageBreak
} = require('docx');
const fs = require('fs');

const CONTENT_W = 9360; // US Letter 1" margins
const col = (n) => ({ size: n, type: WidthType.DXA });
const border = { style: BorderStyle.SINGLE, size: 1, color: 'CCCCCC' };
const borders = { top: border, bottom: border, left: border, right: border };
const hdrBorder = { style: BorderStyle.SINGLE, size: 1, color: '2E75B6' };
const hdrBorders = { top: hdrBorder, bottom: hdrBorder, left: hdrBorder, right: hdrBorder };

function h1(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] });
}
function h2(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] });
}
function h3(text) {
  return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] });
}
function p(text, opts = {}) {
  return new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text, ...opts })] });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    spacing: { after: 80 },
    children: [new TextRun(text)]
  });
}
function code(text) {
  return new Paragraph({
    spacing: { after: 60 },
    border: { left: { style: BorderStyle.SINGLE, size: 6, color: '0066CC', space: 6 } },
    indent: { left: 360 },
    children: [new TextRun({ text, font: 'Courier New', size: 18, color: '1A1A2E' })]
  });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function table(headers, rows, colWidths) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: totalW, type: WidthType.DXA },
    columnWidths: colWidths,
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) => new TableCell({
          borders: hdrBorders,
          width: col(colWidths[i]),
          shading: { fill: '1F5C99', type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          verticalAlign: VerticalAlign.CENTER,
          children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, color: 'FFFFFF', size: 18 })] })]
        }))
      }),
      ...rows.map((row, ri) => new TableRow({
        children: row.map((cell, ci) => new TableCell({
          borders,
          width: col(colWidths[ci]),
          shading: { fill: ri % 2 === 0 ? 'F8FBFF' : 'FFFFFF', type: ShadingType.CLEAR },
          margins: { top: 70, bottom: 70, left: 120, right: 120 },
          children: [new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: cell, font: 'Arial', size: 18 })] })]
        }))
      }))
    ]
  });
}

function spacer(n = 1) {
  return Array.from({ length: n }, () => new Paragraph({ spacing: { after: 120 }, children: [] }));
}

const doc = new Document({
  numbering: {
    config: [{
      reference: 'bullets',
      levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
    }]
  },
  styles: {
    default: { document: { run: { font: 'Arial', size: 22 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 40, bold: true, font: 'Arial', color: '1F5C99' },
        paragraph: { spacing: { before: 360, after: 200 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: '1F5C99', space: 4 } } } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 30, bold: true, font: 'Arial', color: '1F5C99' },
        paragraph: { spacing: { before: 280, after: 140 }, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, font: 'Arial', color: '2E75B6' },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    headers: {
      default: new Header({ children: [
        new Paragraph({
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: '1F5C99', space: 4 } },
          children: [
            new TextRun({ text: 'ACC ', bold: true, color: '1F5C99', size: 20 }),
            new TextRun({ text: '→', color: '1F5C99', size: 20 }),
            new TextRun({ text: ' AJO Migration Tool', bold: true, color: '1F5C99', size: 20 }),
            new TextRun({ text: '  |  Complete System Reference', color: '666666', size: 18 }),
          ]
        })
      ]})
    },
    footers: {
      default: new Footer({ children: [
        new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { top: { style: BorderStyle.SINGLE, size: 2, color: 'CCCCCC', space: 4 } },
          children: [
            new TextRun({ text: 'Page ', size: 18, color: '666666' }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: '666666' }),
            new TextRun({ text: ' of ', size: 18, color: '666666' }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18, color: '666666' }),
          ]
        })
      ]})
    },
    children: [
      // ── TITLE PAGE ──────────────────────────────────────────────
      new Paragraph({ spacing: { before: 2880, after: 240 }, children: [
        new TextRun({ text: 'ACC → AJO Migration Tool', bold: true, size: 64, font: 'Arial', color: '1F5C99' })
      ]}),
      new Paragraph({ spacing: { after: 240 }, children: [
        new TextRun({ text: 'Complete System Reference', size: 40, font: 'Arial', color: '2E75B6' })
      ]}),
      new Paragraph({ spacing: { after: 120 }, children: [
        new TextRun({ text: 'Confidential — Internal Use Only', size: 22, color: '888888', italics: true })
      ]}),
      new Paragraph({ spacing: { after: 120 }, children: [
        new TextRun({ text: 'June 2026', size: 22, color: '888888' })
      ]}),
      pageBreak(),

      // ── TABLE OF CONTENTS ───────────────────────────────────────
      new TableOfContents('Table of Contents', { hyperlink: true, headingStyleRange: '1-3',
        stylesWithLevels: [{ styleId: 'Heading1', level: 1 }, { styleId: 'Heading2', level: 2 }, { styleId: 'Heading3', level: 3 }] }),
      pageBreak(),

      // ── 1. PROJECT STRUCTURE ─────────────────────────────────────
      h1('1. Project Structure'),
      p('The ACC → AJO Migration Tool is a full-stack application with a FastAPI async backend and a React + TypeScript frontend.'),
      ...spacer(),
      h2('1.1 Directory Layout'),
      ...['backend/main.py — FastAPI app, CORS, router registration, DB init',
          'backend/db.py — SQLAlchemy ORM models + init_db()',
          'backend/config.py — Settings (DATABASE_URL, ENCRYPTION_KEY, page sizes)',
          'backend/core/security.py — encrypt/decrypt, get_login_from_cookie, get_valid_acc_token',
          'backend/routes/auth.py — /api/acc/connect, /api/ajo/connect, /api/acc/disconnect, status',
          'backend/routes/schemas.py — /api/acc/schemas, /api/acc/schemas/{ns}/{name}',
          'backend/routes/conversion.py — /api/convert/start, status, extracted',
          'backend/routes/templates.py — /api/templates/count, extract, stored-count',
          'backend/routes/migrate.py — /api/migrate/start, status, jobs, completed, incomplete',
          'backend/services/acc_soap.py — SOAP envelope builders + response parsers',
          'backend/services/schema_inspector.py — parse_schema_to_xdm(): XML → JSON',
          'backend/pipeline/runner.py — run_migration_job() orchestration',
          'backend/pipeline/handlers.py — 14 step handler functions',
          'frontend_app/src/App.tsx — React Router + ProtectedRoute',
          'frontend_app/src/store/configStore.ts — Zustand: accConnected, ajoConnected',
          'frontend_app/src/pages/ConfigPage.tsx — Home: connect ACC + AJO',
          'frontend_app/src/pages/MigrationSelectPage.tsx — Pick schemas',
          'frontend_app/src/pages/MigrationRunPage.tsx — Live extraction + push dashboard',
          'frontend_app/src/pages/TemplateMigrationPage.tsx — Template extraction progress',
      ].map(bullet),
      ...spacer(),

      h2('1.2 How to Run'),
      p('Backend (from backend/ folder):'),
      code('uvicorn main:app --reload --port 8000'),
      p('Frontend (from frontend_app/ folder):'),
      code('npm run dev   # starts on http://localhost:5173'),
      ...spacer(),
      p('.env file required in backend/:'),
      code('DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/acc_ajo'),
      code('ENCRYPTION_KEY=<generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">'),
      new Paragraph({ spacing: { after: 120 }, children: [
        new TextRun({ text: 'IMPORTANT: ', bold: true, color: 'CC0000' }),
        new TextRun({ text: 'Never commit .env — it contains ENCRYPTION_KEY and DATABASE_URL.' })
      ]}),
      pageBreak(),

      // ── 2. DATABASE TABLES ────────────────────────────────────────
      h1('2. Database Tables'),

      h2('2.1 source_connections — ACC Connection'),
      table(
        ['Column', 'Type', 'Notes'],
        [
          ['login_id', 'String', 'Primary identity. Classic: username. Technical: client_id'],
          ['auth_type', 'String', '"classic" or "technical"'],
          ['instance_url', 'String', 'ACC instance base URL'],
          ['encrypted_password', 'Text', 'Fernet-encrypted password (classic only) — used for auto re-Logon'],
          ['session_token', 'Text', 'SOAP session token — populated for both classic and technical'],
          ['security_token', 'Text', 'SOAP security token — populated for both classic and technical'],
          ['session_expires_at', 'DateTime', 'Classic only — now + 23h at login; reset on every auto re-Logon'],
          ['client_id', 'String', 'OAuth client ID (technical only)'],
          ['encrypted_credentials', 'Text', 'Fernet-encrypted "client_id:client_secret" (technical only) — used for IMS refresh'],
          ['encrypted_access_token', 'Text', 'Fernet-encrypted IMS Bearer token (technical only)'],
          ['token_expires_at', 'DateTime', 'IMS token expiry = now + expires_in from IMS (technical only)'],
          ['authenticated', 'Boolean', 'True after successful connect'],
        ],
        [2400, 1800, 5160]
      ),
      ...spacer(),

      h2('2.2 destination_connections — AJO Connection'),
      table(
        ['Column', 'Type', 'Notes'],
        [
          ['org_id', 'String', 'Adobe Org ID e.g. 65cfe7fc@AdobeOrg'],
          ['tenant_id', 'String', 'Derived: "_" + org_id.split("@")[0].lower()'],
          ['client_id', 'String', 'OAuth client ID'],
          ['sandbox_name', 'String', 'AEP sandbox name'],
          ['encrypted_credentials', 'Text', 'Fernet-encrypted "client_id:client_secret"'],
          ['encrypted_access_token', 'Text', 'Fernet-encrypted IMS Bearer token'],
          ['token_expires_at', 'DateTime', 'now + expires_in from IMS'],
          ['authenticated', 'Boolean', 'True after successful connect'],
        ],
        [2400, 1800, 5160]
      ),
      ...spacer(),

      h2('2.3 user_sessions — Browser Sessions'),
      table(
        ['Column', 'Type', 'Notes'],
        [
          ['id', 'String (UUID)', 'Stored in acc_session cookie'],
          ['login_id', 'String', 'Links to source_connections.login_id'],
          ['expires_at', 'DateTime', 'Rolling 7-day TTL — extended on every valid request'],
        ],
        [2400, 1800, 5160]
      ),
      ...spacer(),

      h2('2.4 converted_schemas — Extracted Schema JSON'),
      table(
        ['Column', 'Type', 'Notes'],
        [
          ['job_id', 'String', 'Which extraction job created this'],
          ['login_id', 'String', 'Owning user'],
          ['schema_name', 'String', 'namespace:name e.g. cus:recipient'],
          ['raw_json', 'Text', 'Parsed ACC schema — input to pipeline'],
          ['enriched_json', 'Text', 'Built payload after step 5 — ready to push to AEP'],
        ],
        [2400, 1800, 5160]
      ),
      ...spacer(),

      h2('2.5 schema_job_items — Per-Schema Migration State'),
      table(
        ['Column', 'Type', 'Notes'],
        [
          ['job_id', 'String', 'Migration job UUID'],
          ['schema_name', 'String', 'namespace:name'],
          ['status', 'String', 'QUEUED → RUNNING → COMPLETED / FAILED'],
          ['current_step', 'String', 'Step name e.g. CREATE_SCHEMA'],
          ['current_step_order', 'Integer', '1–14'],
          ['current_snapshot', 'Text', 'JSON dump of pipeline data dict — enables resume'],
          ['identity_is_primary', 'Boolean', 'Set by RESOLVE_IDENTITY step'],
          ['error_message', 'Text', 'Failure reason if FAILED'],
          ['fields_added', 'Integer', 'Fields patched into existing AEP schema'],
          ['completed_at', 'DateTime', 'Set when COMPLETED'],
        ],
        [2600, 1600, 5160]
      ),
      ...spacer(),

      h2('2.6 Template Tables'),
      p('acc_deliverytemplate_raw: login_id, source_id, batch_id, raw_xml (full SOAP XML)'),
      p('acc_deliverytemplate_parsed: login_id, source_id, batch_id, template_data (JSON with subject, htmlBody, textBody, channel)'),
      pageBreak(),

      // ── 3. AUTHENTICATION ─────────────────────────────────────────
      h1('3. Authentication'),

      h2('3.1 ACC Classic Auth (Username + Password)'),
      ...['Browser POSTs to /api/acc/connect with auth_type:"classic", login, password, instance_url',
          'Backend calls ACC SOAP xtk:session#Logon → gets session_token + security_token',
          'Backend calls ACC SOAP xtk:session#TestCnx to validate tokens',
          'Saves to source_connections: session_token, security_token, encrypted_password, session_expires_at = now + 23h',
          'Creates user_sessions row (7-day rolling TTL)',
          'Sets acc_session cookie (httponly, samesite=lax, 7 days)',
      ].map(bullet),
      ...spacer(),
      p('Auto-refresh via get_valid_acc_token():', { bold: true }),
      code('If session_expires_at > now + 60s: return conn.session_token  (SOAP session still valid)'),
      code('Else: decrypt(encrypted_password) → POST ACC xtk:session#Logon → new session_token + security_token'),
      code('     UPDATE source_connections SET session_token, security_token, session_expires_at = now + 23h'),
      p('User never needs to manually reconnect. 23h window = 1h proactive buffer before ACC 24h default session expires.'),
      ...spacer(),

      h2('3.2 ACC Technical Auth (IMS OAuth)'),
      ...['Browser POSTs to /api/acc/connect with auth_type:"technical", client_id, client_secret, scope, instance_url',
          'Backend calls Adobe IMS POST /ims/token/v3 → gets access_token + expires_in',
          '(if expires_in > 86400 → divide by 1000: IMS sometimes returns ms)',
          'Backend calls ACC SOAP xtk:session#BearerTokenLogon with the IMS access_token',
          '→ gets session_token + security_token (proper ACC SOAP tokens, works identically to classic)',
          'Saves session_token, security_token, encrypted_access_token, encrypted_credentials, token_expires_at to source_connections',
          'Creates user_sessions row (7-day rolling TTL)',
          'Sets acc_session cookie (httponly, 7 days)',
      ].map(bullet),
      ...spacer(),
      p('Auto-refresh via get_valid_acc_token():', { bold: true }),
      code('If token_expires_at > now + 60s: return conn.session_token  (SOAP session still valid)'),
      code('Else: decrypt(encrypted_credentials) → POST IMS /ims/token/v3 → new access_token'),
      code('      POST ACC xtk:session#BearerTokenLogon → new session_token + security_token'),
      code('      UPDATE source_connections SET session_token, security_token, encrypted_access_token, token_expires_at'),
      ...spacer(),

      h2('3.3 AJO Auth (IMS OAuth — No Cookie)'),
      ...['Browser POSTs to /api/ajo/connect with org_id, client_id, client_secret, sandbox_name',
          'Backend calls Adobe IMS POST /ims/token/v3',
          'tenant_id derived: "_" + org_id.split("@")[0].lower()',
          'Saves encrypted_access_token, encrypted_credentials, token_expires_at to destination_connections',
          'No cookie set — AJO identity is purely DB-side (not tied to browser session)',
      ].map(bullet),
      ...spacer(),

      h2('3.4 Session Management'),
      ...['acc_session cookie (httponly, 7-day rolling) → user_sessions.id (UUID)',
          'user_sessions.login_id → source_connections.login_id',
          'On every valid request: expires_at pushed forward by 7 days (rolling window)',
          'If expired or missing → 401, user must reconnect',
          'No acc_user fallback (removed — was a security gap)',
      ].map(bullet),
      ...spacer(),

      h2('3.5 _get_acc_conn()'),
      p('Used by every schema-related route in routes/schemas.py. Returns (conn, token) tuple.'),
      code('Step 1: resolve acc_session cookie → login_id via get_login_from_cookie()'),
      code('Step 2: fetch source_connections row for that login_id'),
      code('Step 3: call get_valid_acc_token(conn, db) — auto-refreshes if technical + expired'),
      code('Return: (conn, token)'),
      p('Classic: token = conn.session_token  (auto re-Logon\'d if session_expires_at passed)'),
      p('Technical: token = conn.session_token  (from BearerTokenLogon; IMS-refreshed + re-BearerLogon\'d if token_expires_at passed)'),
      p('In both cases routes and SOAP envelope builders are identical — no auth-type branching needed downstream.'),
      pageBreak(),

      // ── 4. PAGE-BY-PAGE FLOW ──────────────────────────────────────
      h1('4. Page-by-Page Flow'),

      h2('4.1 ConfigPage /'),
      p('File: frontend_app/src/pages/ConfigPage.tsx | Store: useConfigStore (Zustand)'),
      ...spacer(),
      h3('On Page Load (useEffect, fires once)'),
      ...['GET /api/acc/status → { connected, login } → updates accConnected in Zustand store',
          'GET /api/ajo/status → { connected, org_id, sandbox_name } → updates ajoConnected',
          'GET /api/migrate/jobs → if active job found → GET /api/migrate/status/{job_id}',
          'If running > 0 or queued > 0 → auto-navigate to /migration/run?migrate_job={id}',
      ].map(bullet),
      ...spacer(),
      h3('User Actions'),
      table(
        ['Action', 'API', 'Response', 'Result'],
        [
          ['Fill ACC classic + Connect', 'POST /api/acc/connect', '{ success, authenticated, login }', 'acc_session cookie set, store updated'],
          ['Fill ACC technical + Connect', 'POST /api/acc/connect', '{ success, authenticated, login, expires_in }', 'acc_session cookie set, store updated'],
          ['Disconnect ACC', 'POST /api/acc/disconnect', '{ success }', 'Cookie deleted, store cleared'],
          ['Fill AJO form + Connect', 'POST /api/ajo/connect', '{ success, authenticated, expires_in }', 'DB updated, store updated'],
          ['Click "Migrate →"', '—', '—', 'navigate(/migration/type)'],
        ],
        [2200, 2300, 2500, 2360]
      ),
      p('Migrate button is disabled until both accConnected and ajoConnected are true.'),
      ...spacer(),

      h2('4.2 MigrationTypePage /migration/type'),
      p('Protected by ProtectedRoute — requires accConnected && ajoConnected. No API calls on load.'),
      table(
        ['Action', 'Redirect'],
        [
          ['Click "Schema Migration"', 'navigate(/migration/select)'],
          ['Click "Template Migration"', 'navigate(/migration/template)'],
          ['Click "← Back"', 'navigate(/)'],
        ],
        [4680, 4680]
      ),
      ...spacer(),

      h2('4.3 MigrationSelectPage /migration/select'),
      h3('On Page Load — 5 Parallel API Calls'),
      table(
        ['API', 'Response', 'UI effect'],
        [
          ['GET /api/acc/schemas', '{ schemas: [{namespace, name, label}] }', 'Populates left sidebar — ALL schemas shown'],
          ['GET /api/convert/extracted', '{ extracted: ["cus:recipient", ...] }', '"Ready to push" badge on extracted schemas'],
          ['GET /api/migrate/incomplete', '{ schemas: [{schema_name, status, current_step, ...}] }', '"In progress" / "Failed" badge; failed independent schemas pre-selected'],
          ['GET /api/migrate/completed', '{ schemas: ["cus:recipient", ...] }', '"Pushed to AJO" green badge'],
          ['GET /api/schemas/dependencies', '{ dependents_of: {"hdbk:accountProfile": ["hdbk:membership"]}, dependent_set: ["hdbk:membership"] }', 'Drives sidebar lock/checkbox logic and right-panel grouping'],
        ],
        [2500, 3300, 3560]
      ),
      ...spacer(),
      h3('Sidebar Behaviour'),
      table(
        ['Schema type', 'Visual', 'Selectable'],
        [
          ['Independent (no outgoing FK to custom schemas)', 'Blue text, checkbox, "+N dependents" badge', 'Yes'],
          ['Dependent — parent NOT selected', 'Gray text, lock icon, orange "dependent" badge', 'No'],
          ['Dependent — parent IS selected', 'Green text, lock icon, green "will migrate" badge', 'No'],
        ],
        [3200, 3200, 2960]
      ),
      p('Dependent schemas are reordered in the sidebar to appear directly below their parent independent schema.'),
      ...spacer(),
      h3('Badge Logic'),
      table(
        ['Badge', 'Condition'],
        [
          ['(none)', 'Fresh from ACC, never touched'],
          ['"Ready to push"', 'Exists in converted_schemas DB, not yet migrated'],
          ['"Pushed to AJO"', 'status=COMPLETED in schema_job_items (re-selectable)'],
          ['"In progress"', 'status=RUNNING or QUEUED (checkbox hidden, locked)'],
          ['"Failed: step X"', 'status=FAILED — pre-selected automatically for retry'],
          ['"+N dependents"', 'Independent schema with N schemas that FK-link to it'],
          ['"dependent"', 'Schema has an outgoing FK — cannot be selected independently'],
          ['"will migrate"', 'Dependent schema whose parent is currently selected'],
        ],
        [2800, 6560]
      ),
      ...spacer(),
      h3('Right Panel — Field Preview'),
      ...['PK fields: purple dot + purple row highlight',
          'FK fields: orange dot + orange row highlight; label column shows "→ targetSchema"',
          'Summary line: "Primary Key: membershipId | FK: accountProfileId → hdbk:accountProfile"',
          'Dependent schema cards shown below the selected independent schema (orange border, auto-expanded)',
          'Dependent schema details auto-fetched when parent is selected',
      ].map(bullet),
      ...spacer(),
      h3('Clicking "Migrate →" (handleNext)'),
      code('expandWithDependents(selected) → adds all dependents of selected schemas'),
      code('POST /api/convert/start'),
      code('Body: { "schemas": [accountProfile, membership, order] }  ← includes auto-added dependents'),
      code('Response: { "job_id": "abc123", "message": "started", "skipped": [] }'),
      code('navigate("/migration/run?extract_job=abc123")'),
      p('User selects only independent schemas. Dependent schemas are added automatically by expandWithDependents() before POST. Header badge shows total count including dependents.'),
      ...spacer(),

      h2('4.4 MigrationRunPage /migration/run'),
      p('URL params: ?extract_job={id} (new), ?migrate_job={id} (resume), ?phase=migrate (skip extraction)'),
      ...spacer(),
      h3('Phase: extracting'),
      p('Polls GET /api/convert/status/{job_id} every 2 seconds until status === "completed".'),
      code('Response: { id, status, schema_count, success_count, failed_count, current_schema, steps }'),
      p('When completed → automatically fires POST /api/migrate/start:'),
      code('Body: { "extract_job_id": "abc123" }'),
      code('Response: { "job_id": "mig456", "total": 2, "queued": 2, "skipped": 0, "message": "started" }'),
      p('If message === "all_done" → jumps to phase=done immediately (all schemas already current in AEP).'),
      ...spacer(),
      h3('Phase: migrating'),
      p('Polls GET /api/migrate/status/{job_id} every 2 seconds.'),
      table(
        ['Card type', 'Status', 'Shows'],
        [
          ['InProgressCard', 'RUNNING', 'Step X of 14, step name, 14-segment progress bar (blue=current, green=done)'],
          ['CompletedCard', 'COMPLETED', 'Green tick, "Pushed to AJO" / "Already in AJO" / "Updated — N fields added", duration'],
          ['FailedCard', 'FAILED', 'Red X, step where it failed, error message, red segment in bar'],
          ['QueuedCard', 'QUEUED', 'Grey "Queued" badge'],
        ],
        [2200, 1800, 5360]
      ),
      p('When running === 0 && queued === 0 → phase = done.'),
      ...spacer(),
      h3('Phase: done'),
      p('"Migration complete — all N schemas pushed to AJO" (green) or "N failed" (yellow). "Back to home" → navigate("/").'),
      ...spacer(),

      h2('4.5 TemplateMigrationPage /migration/template'),
      h3('On Page Load — Phase: counting'),
      code('GET /api/templates/count'),
      code('Response: { "total": 31, "stored": 0, "to_migrate": 31 }'),
      p('If to_migrate === 0 → phase = nothing (all templates already extracted).'),
      ...spacer(),
      h3('Phase: extracting'),
      p('Polling (every 2s): GET /api/templates/stored-count → { "stored": N } — updates live counter.'),
      p('Extraction loop (runs until done):'),
      code('POST /api/templates/extract (no body)'),
      code('Response: { "extracted": 100, "total_found": 100, "skipped": 0, "batch_id": "uuid", "errors": [] }'),
      ...['Each call uses COUNT(acc_deliverytemplate_raw) as SOAP startLine cursor (tracks fetched count)',
          'Per template: skips SOAP if already in raw; skips parsing if already in parsed',
          'Fetches next batch of page_size (default 100) templates from ACC',
          'Loop breaks when total_found === 0 (no more) or extracted < total_found (partial page = end)',
          'Single click extracts all templates — user never clicks again',
      ].map(bullet),
      pageBreak(),

      // ── 5. ALL API ENDPOINTS ──────────────────────────────────────
      h1('5. All API Endpoints'),
      p('All endpoints require Cookie: acc_session={uuid} (set automatically by browser).'),
      ...spacer(),

      h2('5.1 Authentication Endpoints'),
      table(
        ['Method', 'Endpoint', 'Body', 'Response', 'Cookie'],
        [
          ['POST', '/api/acc/connect', '{ auth_type, instance_url, login?, password?, client_id?, client_secret?, scope? }', '{ success, authenticated, login, expires_in? }', 'acc_session (7d)'],
          ['POST', '/api/acc/disconnect', '—', '{ success }', 'Deletes acc_session'],
          ['GET', '/api/acc/status', '—', '{ connected, login }', '—'],
          ['POST', '/api/ajo/connect', '{ org_id, client_id, client_secret, sandbox_name }', '{ success, authenticated, expires_in }', '—'],
          ['GET', '/api/ajo/status', '—', '{ connected, org_id, sandbox_name }', '—'],
          ['GET', '/api/connections/status', '—', '{ sourceAuthenticated, destinationAuthenticated, sourceLoginId, destinationOrgId }', '—'],
        ],
        [800, 2200, 2800, 2360, 1200]
      ),
      ...spacer(),

      h2('5.2 Schema Endpoints'),
      table(
        ['Method', 'Endpoint', 'Response'],
        [
          ['GET', '/api/acc/schemas', '{ schemas: [{ namespace, name, label }] }'],
          ['GET', '/api/acc/schemas/{namespace}/{name}', '{ namespace, name, label, attributes: [{name, type, label}], keys: {autoPk, primaryKeys, uniqueKeys}, links: [{name, targetSchema, sourceField}] }'],
          ['GET', '/api/schemas/dependencies', '{ dependents_of: { "hdbk:accountProfile": ["hdbk:membership"] }, dependent_set: ["hdbk:membership"] }'],
        ],
        [800, 3000, 5560]
      ),
      ...spacer(),

      h2('5.3 Schema Extraction (Conversion) Endpoints'),
      table(
        ['Method', 'Endpoint', 'Body', 'Response'],
        [
          ['POST', '/api/convert/start', '{ schemas: [{namespace, name, label}] }', '{ job_id, message, skipped }'],
          ['POST', '/api/convert/start-all', '—', '{ job_id, message, total, skipped }'],
          ['GET', '/api/convert/status/{job_id}', '—', '{ id, status, schema_count, success_count, failed_count, current_schema, steps }'],
          ['GET', '/api/convert/extracted', '—', '{ extracted: ["cus:recipient", ...] }'],
        ],
        [800, 2400, 2400, 3760]
      ),
      ...spacer(),

      h2('5.4 Schema Migration Endpoints'),
      table(
        ['Method', 'Endpoint', 'Body', 'Response'],
        [
          ['POST', '/api/migrate/start', '{ extract_job_id? }', '{ job_id, total, queued, skipped, message }'],
          ['GET', '/api/migrate/status/{job_id}', '—', '{ job_id, total, completed, running, queued, failed, schemas: [...] }'],
          ['GET', '/api/migrate/jobs', '—', '{ jobs: [{ job_id, created_at }] }'],
          ['GET', '/api/migrate/completed', '—', '{ schemas: ["cus:recipient", ...] }'],
          ['GET', '/api/migrate/incomplete', '—', '{ schemas: [{schema_name, status, current_step, current_step_order, error_message}] }'],
        ],
        [800, 2400, 2400, 3760]
      ),
      ...spacer(),

      h2('5.5 Template Endpoints'),
      table(
        ['Method', 'Endpoint', 'Response'],
        [
          ['GET', '/api/templates/count', '{ total, stored, to_migrate }'],
          ['GET', '/api/templates/stored-count', '{ stored }'],
          ['POST', '/api/templates/extract', '{ extracted, total_found, skipped, batch_id, errors }'],
        ],
        [800, 3000, 5560]
      ),
      pageBreak(),

      // ── 6. SCHEMA DEPENDENCY FEATURE ─────────────────────────────
      h1('6. Schema Dependency Feature'),

      h2('6.1 Concept'),
      p('ACC schemas can reference each other through link elements — XML elements with type="link" that define a foreign-key relationship.'),
      code('<element name="accountProfile" type="link" target="hdbk:accountProfile">'),
      code('  <join xpath-src="@accountProfileId" xpath-dst="@id"/>'),
      code('</element>'),
      ...spacer(),
      table(
        ['Term', 'Definition', 'Example'],
        [
          ['Independent schema', 'Has no FK pointing to another custom schema. User selects this from the sidebar.', 'hdbk:accountProfile'],
          ['Dependent schema', 'Has an outgoing FK to another custom schema. Cannot be selected alone — migrates automatically with its parent.', 'hdbk:membership (FK → accountProfile)'],
          ['sourceField', 'The local attribute that holds the FK value, parsed from xpath-src.', 'accountProfileId'],
          ['targetSchema', 'The schema the FK points to, from the target attribute.', 'hdbk:accountProfile'],
        ],
        [2200, 4500, 2660]
      ),
      p('Why this matters: migrating a dependent schema without its independent parent breaks the FK relationship in AJO. The tool enforces correctness automatically.'),
      ...spacer(),

      h2('6.2 How the Dependency Graph is Built'),
      p('File: backend/routes/schemas.py — get_dependency_graph()'),
      p('Called from: frontend_app/src/api/client.ts — getSchemaDependencies() — called on page load in MigrationSelectPage.tsx'),
      p('Hybrid strategy: PATH A uses already-extracted DB data (fast, no SOAP). PATH B fetches live from ACC SOAP when DB is empty.', { bold: false }),
      ...spacer(),
      h3('PATH A — DB (post-extraction, fast)'),
      ...['Authenticate: get_login_from_cookie() → login_id',
          'SELECT converted_schemas WHERE login_id = ? → if rows exist, use them',
          'all_names = { row.schema_name for row in rows }',
          'For each row: load raw_json → read linksAndJoins array',
          'For each link where targetSchema in all_names: dependents_of[target].append(row.schema_name), dependent_set.add(row.schema_name)',
          'Return immediately — zero SOAP calls',
      ].map(bullet),
      ...spacer(),
      h3('PATH B — SOAP fallback (pre-extraction)'),
      table(
        ['Step', 'Action', 'Details'],
        [
          ['1', 'Authenticate', 'SELECT source_connections WHERE login_id = ? → get_valid_acc_token(conn, db)'],
          ['2', 'Fetch custom schema list', 'POST soaprouter.jsp — build_list_schemas_envelope(). Filters out system namespaces: xtk, nms, nl, ncm, crm, bur, sfa, ext, offer, mkt, wpa, sup, temp, ghost, nav, acs, fda'],
          ['3', 'Fetch all srcSchema XML (concurrent)', 'asyncio.gather(*[_fetch_links() for each schema]). Each: POST soaprouter.jsp — build_srcschema_get_envelope(ns, name) → parse_schema_preview() → (schema_key, links[])'],
          ['4', 'Build graph', 'For each schema_key with FK links to other custom schemas: dependents_of[target].append(schema_key), dependent_set.add(schema_key)'],
          ['5', 'Return', '{ dependents_of: {...}, dependent_set: [...] } — computed fresh, not persisted'],
        ],
        [600, 2400, 6360]
      ),
      ...spacer(),

      h2('6.3 API: GET /api/schemas/dependencies'),
      p('Auth: acc_session cookie → login_id via get_login_from_cookie(). No body.'),
      p('PATH A (DB): reads converted_schemas.raw_json.linksAndJoins — no SOAP calls.'),
      p('PATH B (SOAP): ACC SOAP calls made:'),
      ...['build_list_schemas_envelope → xtk:queryDef#ExecuteQuery (1 call to get schema list)',
          'build_srcschema_get_envelope × N concurrent → xtk:queryDef#ExecuteQuery (1 per custom schema)',
      ].map(bullet),
      ...spacer(),
      p('Response shape:'),
      code('{ "dependents_of": { "hdbk:accountProfile": ["hdbk:membership", "hdbk:order"] },'),
      code('  "dependent_set": ["hdbk:membership", "hdbk:order"] }'),
      table(
        ['Field', 'Type', 'Meaning'],
        [
          ['dependents_of', 'Record<string, string[]>', 'For each independent schema, list of schemas that FK-link to it'],
          ['dependent_set', 'string[]', 'All schema keys that have at least one outgoing FK to another custom schema'],
        ],
        [2200, 2400, 4760]
      ),
      ...spacer(),

      h2('6.4 API: GET /api/acc/schemas/{ns}/{name} — FK Link Info'),
      p('File: backend/services/schema_preview.py — parse_schema_preview() updated to parse link elements.'),
      p('Parses this XML pattern:'),
      code('<element name="accountProfile" type="link" target="hdbk:accountProfile">'),
      code('  <join xpath-src="@accountProfileId" xpath-dst="@id"/>'),
      code('</element>'),
      p('Returns additional links field in schema detail response:'),
      code('{ ..., "links": [{ "name": "accountProfile", "targetSchema": "hdbk:accountProfile", "sourceField": "accountProfileId" }] }'),
      table(
        ['Field', 'Source in XML', 'Meaning'],
        [
          ['name', '<element name="">', 'Name of the link element'],
          ['targetSchema', '<element target="">', 'The schema this FK points to'],
          ['sourceField', '<join xpath-src="@..."> with @ stripped', 'The local field that holds the FK value'],
        ],
        [2000, 3000, 4360]
      ),
      p('Not stored in the database. Parsed from live SOAP response each time schema detail is requested.'),
      ...spacer(),

      h2('6.5 Frontend State and Rendering'),
      p('File: frontend_app/src/pages/MigrationSelectPage.tsx'),
      p('State managed:'),
      code('dependentsOf: Record<string, string[]>   // { "hdbk:accountProfile": ["hdbk:membership"] }'),
      code('dependentSet: Set<string>                // { "hdbk:membership", "hdbk:order" }'),
      code('belongsTo:    Record<string, string[]>   // { "hdbk:membership": ["hdbk:accountProfile"] } (reverse map)'),
      ...spacer(),
      p('Sidebar ordering logic — dependents placed directly below their parent:'),
      code('For each schema in baseFiltered:'),
      code('  If already inserted → skip'),
      code('  Add schema to ordered list'),
      code('  If independent → immediately add all its dependents from baseFiltered'),
      ...spacer(),
      p('Sidebar rendering per schema:'),
      table(
        ['Condition', 'isActivated', 'Styling', 'Badge'],
        [
          ['Independent', '—', 'Blue text, checkbox', '"+N dependents" if deps exist'],
          ['Dependent, parent not selected', 'false', 'Gray, opacity-70, lock icon', '"dependent of parentName"'],
          ['Dependent, parent selected', 'true', 'Green bg, green lock icon', '"will migrate"'],
        ],
        [2200, 1400, 2800, 2960]
      ),
      ...spacer(),
      p('When independent schema is selected (toggle()):'),
      ...['fetchDetail(key) → GET /api/acc/schemas/{ns}/{name} → attributes + keys + links',
          'fetchDependentsOf(key) → prefetches detail for each dependent schema',
          'Auto-expands all dependent cards in the right panel (setDepExpanded)',
          'FK field in attributes highlighted orange in the field table',
          'Dependent schema cards shown below parent with orange border',
      ].map(bullet),
      ...spacer(),

      h2('6.6 Full End-to-End Flow'),
      p('User opens /migration/select → 5 parallel API calls fire, including GET /api/schemas/dependencies.'),
      p('Backend concurrently fetches all custom schema XMLs from ACC, parses FK links, returns dependency graph.'),
      p('Frontend receives: dependentSet = {"hdbk:membership", "hdbk:order"}, dependentsOf = {"hdbk:accountProfile": ["hdbk:membership", "hdbk:order"]}.'),
      ...spacer(),
      p('Sidebar renders:'),
      code('hdbk:accountProfile   [checkbox]  [+2 dependents]'),
      code('hdbk:membership       [lock]       [dependent of accountProfile]  ← ordered below parent'),
      code('hdbk:order            [lock]       [dependent of accountProfile]  ← ordered below parent'),
      ...spacer(),
      p('User clicks hdbk:accountProfile:'),
      ...['GET /api/acc/schemas/hdbk/accountProfile → links: [] (no FK)',
          'GET /api/acc/schemas/hdbk/membership → links: [{ targetSchema: "hdbk:accountProfile", sourceField: "accountProfileId" }]',
          'GET /api/acc/schemas/hdbk/order → links: [{ targetSchema: "hdbk:accountProfile", sourceField: "accountProfileId" }]',
          'Sidebar: membership and order turn green with "will migrate" badge',
          'Header badge: "3 schemas will migrate"',
          'Right panel: accountProfile fields shown; below it, membership and order cards (orange border) with accountProfileId row highlighted orange',
      ].map(bullet),
      ...spacer(),
      p('User clicks Migrate →:'),
      code('expandWithDependents({"hdbk:accountProfile"}) → [accountProfile, membership, order]'),
      code('POST /api/convert/start → { job_id: "abc123" }'),
      code('navigate("/migration/run?extract_job=abc123")'),
      pageBreak(),

      // ── 7. SCHEMA MIGRATION PIPELINE ─────────────────────────────
      h1('7. Schema Migration Pipeline (14 Steps)'),
      p('Triggered automatically when extraction completes. Runs in background via run_migration_job().'),
      p('Concurrency: _GLOBAL_SEM(10) across all jobs + job_sem(3) per job (max 3 schemas concurrent per job).'),
      p('Resume/retry: After every step, current_snapshot (full data dict JSON) is saved to schema_job_items. On retry, pipeline resumes from one step before where it failed.'),
      ...spacer(),

      h2('7.1 Phase 1 — Enrichment (Steps 1–5, concurrent per schema)'),
      table(
        ['Step', 'Name', 'What it does'],
        [
          ['1', 'LOAD_JSON', 'Reads raw_json from converted_schemas DB. Parses into pipeline data dict.'],
          ['2', 'MAP_TYPES', 'Maps ACC field types to XDM types: string, integer, number, boolean, date, datetime.'],
          ['3', 'RESOLVE_IDENTITY', 'Finds identity field + namespace. email→Email, ecid→ECID, etc. Sets identity_is_primary flag.'],
          ['4', 'FETCH_TENANT_ID', 'Reads tenant_id from destination_connections DB row.'],
          ['5', 'BUILD_PAYLOAD', 'Builds complete AEP JSON Schema payload. Writes enriched_json to converted_schemas DB.'],
        ],
        [600, 2400, 6360]
      ),
      ...spacer(),

      h2('7.2 Phase 2 — AEP Push (Steps 6–12, concurrent per schema)'),
      table(
        ['Step', 'Name', 'API called', 'Notes'],
        [
          ['6', 'NORMALIZE_INPUT', '—', 'Re-reads enriched_json from DB (durable, survives restart)'],
          ['7', 'DUPLICATE_CHECK', 'GET /tenant/schemas', 'Checks if schema already exists in AEP'],
          ['8', 'CREATE_SCHEMA', 'POST /tenant/schemas or PATCH', 'New schema or patch missing fields into existing'],
          ['9', 'PRIMARY_KEY_DESCRIPTOR', 'POST /tenant/descriptors', 'xdm:descriptorPrimaryKey descriptor'],
          ['10', 'VERSION_DESCRIPTOR', 'POST /tenant/descriptors', 'xdm:descriptorVersion descriptor'],
          ['11', 'TIMESTAMP_DESCRIPTOR', 'POST /tenant/descriptors', 'Time-series only — skipped for record schemas'],
          ['12', 'IDENTITY_DESCRIPTOR', 'GET /idnamespace + POST /tenant/descriptors', 'Creates or reuses identity namespace, then adds xdm:descriptorIdentity'],
        ],
        [600, 2200, 2800, 3760]
      ),
      ...spacer(),

      h2('7.3 Phase 3 — Cross-Schema (Steps 13–14, sequential)'),
      table(
        ['Step', 'Name', 'What it does'],
        [
          ['13', 'RELATIONSHIP_DESCRIPTORS', 'POSTs xdm:descriptorOneToOne or many-to-one relationship descriptors between schemas'],
          ['14', 'VERIFY', 'GETs schemas + descriptors from AEP to confirm everything landed correctly'],
        ],
        [600, 2400, 6360]
      ),
      ...spacer(),

      h2('7.4 Final Status Values'),
      table(
        ['Status', 'Meaning'],
        [
          ['COMPLETED', 'Newly pushed — all 14 steps passed'],
          ['ALREADY_EXISTS', 'Found in AEP at step 7 — no changes needed'],
          ['UPDATED', 'Found in AEP — new fields were patched in (fields_added > 0)'],
          ['FAILED', 'Error at some step — error_message shows which step and why'],
        ],
        [2400, 6960]
      ),
      pageBreak(),

      // ── 8. TEMPLATE EXTRACTION FLOW ───────────────────────────────
      h1('8. Template Extraction Flow'),
      p('Triggered by POST /api/templates/extract. Uses SOAP xtk:queryDef#ExecuteQuery on nms:delivery.'),
      ...spacer(),

      table(
        ['Step', 'Action', 'Details'],
        [
          ['1', 'Cursor', 'COUNT(acc_deliverytemplate_raw WHERE login_id=?) → start_line (tracks fetched templates, not parsed)'],
          ['2', 'Pre-load skip sets', 'SELECT source_id FROM acc_deliverytemplate_raw → already_in_raw (set). SELECT source_id FROM acc_deliverytemplate_parsed → already_in_parsed (set). One DB query each, O(1) lookup per template.'],
          ['3', 'Fetch page from ACC', 'build_list_templates_envelope(token, security_token, page_size=100, start_line). Filters: @isModel=1, @builtIn!=1, @messageType=0 OR 1'],
          ['4a', 'Step A — Raw', 'If source_id NOT in already_in_raw: SOAP fetch → build_get_delivery_envelope() → INSERT acc_deliverytemplate_raw. Else: skip SOAP call entirely.'],
          ['4b', 'Step B — Parsed', 'If source_id NOT in already_in_parsed: parse fields (subject, htmlBody, textBody, smsContent) → INSERT acc_deliverytemplate_parsed. COMMIT. Else: skipped++. If detail not available (raw existed in DB), reload from stored raw_xml → parse_delivery_detail().'],
          ['5', 'Return', '{ extracted, total_found, skipped, batch_id, errors }'],
        ],
        [600, 1800, 6960]
      ),
      ...spacer(),
      h3('Per-Template Decision Matrix'),
      table(
        ['In raw?', 'In parsed?', 'Action'],
        [
          ['No', 'No', 'SOAP fetch → store raw → parse → store parsed'],
          ['Yes', 'No', 'Skip SOAP, reload raw XML from DB → parse → store parsed'],
          ['Yes', 'Yes', 'Skip entirely (skipped++)'],
        ],
        [1800, 1800, 5760]
      ),
      ...spacer(),
      p('Pagination: Frontend loops calling POST /api/templates/extract until total_found === 0. Raw row count in DB acts as SOAP cursor — no separate pagination state needed.'),
      pageBreak(),

      // ── 9. CONFIGURATION ──────────────────────────────────────────
      h1('9. Configuration'),

      h2('9.1 backend/config.py'),
      table(
        ['Key', 'Default', 'Purpose'],
        [
          ['DATABASE_URL', 'postgresql+asyncpg://...', 'DB connection string'],
          ['ENCRYPTION_KEY', '(required, from .env)', 'Fernet key for credential encryption'],
          ['SOAP_TIMEOUT', '30.0', 'Seconds before ACC SOAP call times out'],
          ['CORS_ORIGINS_RAW', 'http://localhost:3000, http://localhost:5173', 'Allowed frontend origins'],
          ['template_page_size', '100', 'Templates fetched per extraction batch'],
        ],
        [2800, 2800, 3760]
      ),
      ...spacer(),

      h2('9.2 Route Protection'),
      p('Defined in App.tsx. All migration pages are wrapped in ProtectedRoute:'),
      code('condition={accConnected && ajoConnected}'),
      p('Covers: /migration/type, /migration/select, /migration/run, /migration/template'),
      p('If either connection is false → redirected to / (ConfigPage).'),
      p('Connection state lives in Zustand (useConfigStore) — set by ConfigPage on load via GET /api/acc/status and GET /api/ajo/status.'),
      ...spacer(),

      h2('9.3 Security Notes'),
      table(
        ['What', 'How'],
        [
          ['Passwords, client_secrets, access_tokens', 'Fernet-encrypted before DB storage'],
          ['SOAP session/security tokens (classic)', 'Stored plaintext — required for direct SOAP header injection'],
          ['Browser session', 'acc_session cookie: httponly, samesite=lax, 7-day rolling TTL'],
          ['Token auto-refresh (technical)', 'encrypted_credentials used for refresh — never exposed to browser'],
          ['.env file', 'Never committed — contains ENCRYPTION_KEY and DATABASE_URL'],
        ],
        [3500, 5860]
      ),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync(
    'C:\\Users\\pavitram\\Desktop\\accTOajo\\schemaFinal\\ACCtoAJO\\SYSTEM_REFERENCE.docx',
    buffer
  );
  console.log('SYSTEM_REFERENCE.docx created successfully');
}).catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
