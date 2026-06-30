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
const LIGHT_RED = "FFF5F5";

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
    spacing: { before: 160, after: 60 },
    children: [new TextRun({ text, bold: true, size: 24, color: MID_GREY, font: "Arial" })]
  });
}
function body(text, italic = false) {
  return new Paragraph({
    spacing: { after: 80 },
    children: [new TextRun({ text, size: 22, color: MID_GREY, font: "Arial", italics: italic })]
  });
}
function quote(text) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    border: { left: { style: BorderStyle.SINGLE, size: 16, color: ADOBE_RED, space: 10 } },
    shading: { type: ShadingType.CLEAR, fill: LIGHT_RED },
    indent: { left: 240, right: 240 },
    children: [new TextRun({ text, size: 22, color: DARK_GREY, font: "Arial", italics: true })]
  });
}
function note(text) {
  return new Paragraph({
    spacing: { after: 80 },
    border: { left: { style: BorderStyle.SINGLE, size: 8, color: "888888", space: 8 } },
    indent: { left: 200 },
    children: [new TextRun({ text, size: 20, color: "666666", font: "Arial" })]
  });
}
function spacer() {
  return new Paragraph({ spacing: { after: 60 }, children: [new TextRun("")] });
}
function divider() {
  return new Paragraph({
    spacing: { before: 160, after: 160 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "DDDDDD", space: 1 } },
    children: [new TextRun("")]
  });
}
function bullet(text, bold_prefix = "") {
  const runs = [];
  if (bold_prefix) {
    runs.push(new TextRun({ text: bold_prefix + " ", bold: true, size: 22, color: MID_GREY, font: "Arial" }));
    runs.push(new TextRun({ text, size: 22, color: MID_GREY, font: "Arial" }));
  } else {
    runs.push(new TextRun({ text, size: 22, color: MID_GREY, font: "Arial" }));
  }
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { after: 40 },
    children: runs
  });
}
function numberedBullet(text) {
  return new Paragraph({
    numbering: { reference: "numbered", level: 0 },
    spacing: { after: 60 },
    children: [new TextRun({ text, size: 22, color: MID_GREY, font: "Arial" })]
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
  new Paragraph({ spacing: { before: 2000, after: 120 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "ACC → AJO Migration Tool", bold: true, size: 56, color: ADOBE_RED, font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Architecture Review — Meeting Preparation Guide", size: 32, color: MID_GREY, font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "What to say, how to say it, in what order", size: 24, italics: true, color: "888888", font: "Arial" })] }),
  new Paragraph({ spacing: { after: 80 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "June 2026  |  Internal Developer Reference", size: 22, color: "AAAAAA", font: "Arial" })] }),
  new Paragraph({ children: [new PageBreak()] })
);

// ── HOW TO OPEN ───────────────────────────────────────────────────────────────
children.push(h1("How to Open (30 seconds)"));
children.push(quote(
  '"This tool migrates customer data schemas and delivery templates from Adobe Campaign Classic ' +
  'to Adobe Journey Optimizer. It handles two very different authentication models, extracts ' +
  'schema definitions over SOAP, transforms them into XDM format, and pushes them to AJO via ' +
  'REST APIs — all through a React UI backed by a FastAPI async Python server."'
));
children.push(note("Keep it one sentence per layer. Don't go deep immediately — let them ask."));
children.push(divider());

// ── 1. PROBLEM ────────────────────────────────────────────────────────────────
children.push(h1("1.  What Problem Does This Solve?"));
children.push(h2("The Problem"));
children.push(bullet("ACC stores data in its own relational schema format (XML-defined, SOAP-queryable)"));
children.push(bullet("AJO expects XDM (Experience Data Model) — JSON schema format"));
children.push(bullet("These are structurally incompatible — field types, link/join semantics, key definitions all differ"));
children.push(bullet("Manual migration of dozens of custom schemas takes weeks and is error-prone"));
children.push(spacer());
children.push(h2("What the Tool Does"));
children.push(bullet("Connects to ACC (classic login OR technical IMS account) and lists all custom schemas"));
children.push(bullet("User selects which schemas to migrate"));
children.push(bullet("Tool fetches full XML definition of each schema over SOAP, parses it, transforms to XDM JSON"));
children.push(bullet("Pushes XDM to AJO Dataset API in a 14-step pipeline"));
children.push(bullet("Also migrates ACC delivery templates → AJO content templates"));
children.push(divider());

// ── 2. TECH STACK ─────────────────────────────────────────────────────────────
children.push(h1("2.  Tech Stack"));
children.push(...makeTable(
  ["Layer", "Technology", "Why"],
  [
    ["Frontend",    "React + TypeScript + Vite",   "SPA, fast dev, type safety"],
    ["State",       "Zustand (persisted)",          "Lightweight, survives page refresh"],
    ["Backend",     "FastAPI (Python async)",       "Async SOAP + DB calls without blocking"],
    ["HTTP client", "httpx async",                  "Non-blocking SOAP requests to ACC"],
    ["Database",    "PostgreSQL + SQLAlchemy async","Stores connections, sessions, schema data, job state"],
    ["Encryption",  "Fernet (cryptography lib)",    "Symmetric encryption for stored tokens/passwords"],
    ["ACC API",     "SOAP over HTTP (soaprouter.jsp)","Only programmatic interface ACC exposes"],
    ["AJO API",     "REST + IMS Bearer token",      "Standard Adobe API pattern"],
  ],
  [2400, 3400, 3560]
));
children.push(divider());

// ── 3. AUTH ───────────────────────────────────────────────────────────────────
children.push(h1("3.  Authentication — Two Paths (most important to explain)"));

children.push(h2("Classic Auth"));
children.push(quote(
  '"Classic is straightforward. User gives username + password. We build a SOAP Logon envelope, ' +
  'POST it to ACC\'s soaprouter endpoint, get back a session_token and security_token. ' +
  'We store those in the DB and use them on every subsequent SOAP call via Cookie header."'
));
children.push(...codeBlock(
`User → POST /api/acc/connect (auth_type = "classic")
  → SOAP xtk:session#Logon → session_token + security_token stored in DB
  → SOAP headers: Cookie: __sessiontoken=<token>  +  X-Security-Token: <sec_token>`));
children.push(spacer());

children.push(h2("Technical Auth (IMS)"));
children.push(quote(
  '"Technical accounts don\'t have a username/password. They authenticate via Adobe IMS — ' +
  'Adobe\'s identity platform. We call IMS with client_id + client_secret using OAuth2 ' +
  'client_credentials flow. IMS returns an access_token. We store that token encrypted ' +
  'in the DB. For every SOAP call to ACC, we use that IMS token directly as an ' +
  'Authorization Bearer header. ACC recognises it natively — no separate ACC session needed."'
));
children.push(...codeBlock(
`User → POST /api/acc/connect (auth_type = "technical")
  → POST IMS token/v3 (client_credentials) → access_token
  → stored as Fernet(access_token) in SourceConnection.encrypted_access_token
  → SOAP headers: Authorization: Bearer <ims_access_token>`));
children.push(spacer());
children.push(note("Key point if asked: IMS tokens expire (typically 24h). We track token_expires_at and auto-refresh before any SOAP call if within 60 seconds of expiry. The refresh re-calls IMS only — no user interaction needed."));
children.push(spacer());

children.push(h2("Session Cookie (browser)"));
children.push(quote(
  '"On top of both auth types, we create a UserSession row in DB with a 7-day rolling TTL ' +
  'and set an acc_session cookie in the browser. Every API call renews the TTL — active ' +
  'users never get logged out. Inactive sessions expire after 7 days naturally."'
));
children.push(divider());

// ── 4. CORE FLOW ──────────────────────────────────────────────────────────────
children.push(h1("4.  Core Flow — Schema Migration"));
children.push(body("Walk through this step by step in the meeting:"));
children.push(spacer());

const steps = [
  "User connects ACC + AJO on ConfigPage",
  "User chooses \"Schema Migration\" on MigrationTypePage (new routing step)",
  "MigrationSelectPage loads — 5 parallel API calls fire: list schemas (SOAP), already extracted (DB), mid-migration (DB), fully pushed (DB), FK dependency graph (DB + SOAP)",
  "User clicks a schema row → lightweight preview fetched via parse_schema_preview (SOAP + minimal XML parse, NOT stored in DB)",
  "User selects schemas, clicks \"Migrate →\"",
  "Extraction job starts in background (asyncio.create_task — HTTP response returns immediately with job_id)",
  "Per schema: SOAP srcSchema#Get → full XML → parse_schema_to_xdm → stored as raw_json in ConvertedSchema table",
  "Frontend polls GET /api/convert/status/{job_id} every 2 seconds",
  "When extraction completes → migration pipeline starts automatically (14 steps per schema)",
  "MigrationRunPage shows live progress — per schema, per step",
];
steps.forEach((s, i) => {
  children.push(numberedBullet(`Step ${i+1}: ${s}`));
});
children.push(divider());

// ── 5. TWO PARSERS ────────────────────────────────────────────────────────────
children.push(h1("5.  Two XML Parsers — Why Two?"));
children.push(quote(
  '"We have two parsers for the same XML because the use cases are completely different."'
));
children.push(spacer());
children.push(...makeTable(
  ["", "parse_schema_preview", "parse_schema_to_xdm"],
  [
    ["When called",  "User clicks row to expand in UI",    "Background extraction job"],
    ["Returns",      "attributes + keys + links (UI only)", "Full XDM dict: enums, linksAndJoins, rootElement, etc."],
    ["Stored in DB", "No",                                  "Yes — ConvertedSchema.raw_json"],
    ["Speed",        "Fast, minimal parsing",               "Complete, thorough"],
    ["File",         "services/schema_preview.py",          "services/schema_inspector.py"],
  ],
  [2400, 3600, 3360]
));
children.push(quote(
  '"We didn\'t want to run the full heavy parser just to show a field list in the sidebar. ' +
  'The full parse only runs when the user actually clicks Migrate."'
));
children.push(divider());

// ── 6. BACKGROUND JOBS ────────────────────────────────────────────────────────
children.push(h1("6.  Background Jobs & Polling"));

children.push(h2("Extraction Job  (/api/convert/start)"));
children.push(bullet("Runs as asyncio.create_task — HTTP response returns immediately with job_id"));
children.push(bullet("State tracked in in-memory dict _jobs keyed by job_id"));
children.push(bullet("Frontend polls GET /api/convert/status/{job_id} every 2 seconds"));
children.push(bullet("Schemas processed sequentially — avoids overwhelming ACC"));
children.push(bullet("get_valid_acc_token() called per schema — token auto-refreshes if expired mid-job"));
children.push(spacer());

children.push(h2("Migration Job  (/api/migrate/start)"));
children.push(bullet("State tracked in DB (SchemaJobItem table) — survives server restart"));
children.push(bullet("14 discrete steps per schema, each step tracked individually"));
children.push(bullet("Frontend polls GET /api/migrate/status/{job_id}"));
children.push(spacer());

children.push(quote('"In-memory for extraction (fast, short-lived). DB for migration (durable, long-running)."'));
children.push(divider());

// ── 7. SCHEMA DEPS ───────────────────────────────────────────────────────────
children.push(h1("7.  Schema Dependencies"));
children.push(quote(
  '"ACC schemas reference each other via foreign keys — just like tables in a relational DB. ' +
  'If you migrate schema A which has a link to schema B, you need B in AJO too or the ' +
  'relationship breaks."'
));
children.push(spacer());
children.push(bullet("On page load: full FK dependency graph fetched (GET /api/schemas/dependencies)"));
children.push(bullet("When user selects schema A: dependent schemas (B, C...) auto-selected and locked"));
children.push(bullet("Locked schemas appear greyed out with \"Required by A\" label — can't deselect accidentally"));
children.push(divider());

// ── 8. DB TABLES ─────────────────────────────────────────────────────────────
children.push(h1("8.  Database Tables (know these cold)"));
children.push(...makeTable(
  ["Table", "What it stores"],
  [
    ["source_connections",    "ACC credentials + session/token per user (classic or technical)"],
    ["destination_connections","AJO org credentials + IMS token"],
    ["user_sessions",         "Browser session (acc_session cookie) with rolling 7-day TTL"],
    ["converted_schemas",     "Extracted schema JSON per user per schema (raw_json + enriched_json)"],
    ["schema_job_items",      "Per-schema migration job state — 14 steps tracked per row"],
    ["tenant_config",         "AJO org-level config — identity namespaces, sandbox details"],
  ],
  [4000, 9360]
));
children.push(divider());

// ── 9. DESIGN DECISIONS ───────────────────────────────────────────────────────
children.push(h1("9.  Key Design Decisions (if they ask \"why did you do X?\")"));

const qas = [
  {
    q: "Why SOAP? Why not ACC REST API?",
    a: "ACC's primary programmatic interface is SOAP via soaprouter.jsp. It does have some REST endpoints but they don't expose full schema introspection — that only exists on the SOAP side."
  },
  {
    q: "Why store credentials/tokens in DB?",
    a: "Extraction and migration jobs run in the background after the HTTP request returns. They need to make SOAP calls autonomously for minutes. Storing tokens lets background tasks authenticate without user interaction. All sensitive values are Fernet-encrypted at rest."
  },
  {
    q: "Why rolling session TTL instead of fixed?",
    a: "Fixed TTL would log out active users mid-work if they hit the deadline. Rolling TTL means if you're actively using the tool, you never get interrupted. 7 days is the maximum idle time before expiry."
  },
  {
    q: "Why asyncio for the backend?",
    a: "Each SOAP call to ACC can take 1-5 seconds. With a sync framework, one user's extraction job would block the server for everyone. With asyncio, I/O waits (SOAP calls, DB writes) yield the event loop — the server stays responsive under concurrent users."
  },
  {
    q: "Why in-memory dict for extraction vs DB for migration?",
    a: "Extraction is fast (seconds to minutes) and the state is simple (progress count + steps list). Migration is long-running (minutes to hours for large schema sets), has 14 discrete steps per schema, and needs to survive a server restart — so it lives in DB."
  },
  {
    q: "Why sequential schema processing in extraction?",
    a: "ACC SOAP endpoints are not built for high concurrency. Parallel requests risk rate limiting or connection errors from ACC. Sequential is safer and still fast enough for typical schema counts (10-50 schemas)."
  },
];

qas.forEach(({ q, a }) => {
  children.push(new Paragraph({
    spacing: { before: 120, after: 40 },
    children: [new TextRun({ text: `Q: ${q}`, bold: true, size: 22, color: DARK_GREY, font: "Arial" })]
  }));
  children.push(quote(`"${a}"`));
  children.push(spacer());
});
children.push(divider());

// ── 10. LIKELY QUESTIONS ──────────────────────────────────────────────────────
children.push(h1("10.  Potential Questions — Be Ready"));

const likely = [
  {
    q: "What happens if ACC session expires mid-extraction?",
    a: "get_valid_acc_token() is called per-schema inside the job loop. For classic it auto re-Logons via SOAP. For technical it re-fetches IMS. The next schema gets a fresh token automatically."
  },
  {
    q: "What if the user closes the browser mid-migration?",
    a: "Migration state is in DB. When they return, MigrationSelectPage shows incomplete/failed badges per schema and they can resume or retry individual schemas."
  },
  {
    q: "How do you handle SOAP faults?",
    a: "parse_fault(resp.text) checks every response. A fault marks that schema as failed in the job, logs the error, and continues to the next schema — one bad schema doesn't kill the entire job."
  },
  {
    q: "Is this multi-tenant? Can two users run jobs simultaneously?",
    a: "Yes. Every DB row is scoped to login_id. Jobs, schemas, sessions are all per-user. Two users can extract and migrate simultaneously with no interference."
  },
  {
    q: "What is session_expires_at vs token_expires_at?",
    a: "session_expires_at is the ACC SOAP session lifetime (classic auth, ~24h). token_expires_at is the IMS OAuth token lifetime (technical auth, typically 24h). They're separate because they're separate systems."
  },
  {
    q: "Why does technical auth not use BearerTokenLogon?",
    a: "ACC natively accepts an IMS Bearer token as Authorization header on SOAP calls — you don't need to exchange it for an ACC session token first. We go direct: IMS token in, SOAP response out."
  },
];

likely.forEach(({ q, a }) => {
  children.push(new Paragraph({
    spacing: { before: 120, after: 40 },
    children: [new TextRun({ text: `Q: ${q}`, bold: true, size: 22, color: DARK_GREY, font: "Arial" })]
  }));
  children.push(note(`→ ${a}`));
  children.push(spacer());
});
children.push(divider());

// ── CLOSING ───────────────────────────────────────────────────────────────────
children.push(h1("How to Close"));
children.push(quote(
  '"The tool handles the two hardest parts of ACC→AJO migration that are currently done manually: ' +
  'schema structure translation and template placeholder conversion. It\'s designed to be ' +
  're-runnable — you can re-extract a schema if ACC changes, and failed schemas are retried ' +
  'individually. The goal is to reduce a multi-week migration project to a guided afternoon workflow."'
));
children.push(divider());

// ── SUMMARY ───────────────────────────────────────────────────────────────────
children.push(h1("One-Paragraph Summary (memorise this)"));
children.push(new Paragraph({
  spacing: { before: 60, after: 100 },
  border: {
    top: { style: BorderStyle.SINGLE, size: 4, color: ADOBE_RED, space: 8 },
    bottom: { style: BorderStyle.SINGLE, size: 4, color: ADOBE_RED, space: 8 },
    left: { style: BorderStyle.SINGLE, size: 4, color: ADOBE_RED, space: 8 },
    right: { style: BorderStyle.SINGLE, size: 4, color: ADOBE_RED, space: 8 },
  },
  shading: { type: ShadingType.CLEAR, fill: LIGHT_RED },
  indent: { left: 240, right: 240 },
  children: [new TextRun({
    text: '"The ACC to AJO Migration Tool is a FastAPI + React application. It connects to Adobe ' +
      'Campaign Classic over SOAP — supporting both classic username/password login and technical ' +
      'IMS service accounts — extracts custom data schema definitions, transforms them from ACC\'s ' +
      'XML format into AJO\'s XDM JSON format, and pushes them to AJO via REST APIs. It also ' +
      'handles delivery template migration. Sessions are cookie-based with a rolling 7-day TTL. ' +
      'IMS tokens for technical accounts are auto-refreshed before they expire. Background jobs ' +
      'process schemas asynchronously while the UI polls for progress."',
    size: 22, color: DARK_GREY, font: "Arial", italics: true
  })]
}));

// BUILD
const doc = new Document({
  numbering: {
    config: [
      {
        reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
      },
      {
        reference: "numbered",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
      }
    ]
  },
  styles: { default: { document: { run: { font: "Arial", size: 22 } } } },
  sections: [{
    properties: {
      page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
    },
    headers: {
      default: new Header({ children: [new Paragraph({
        border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 4 } },
        children: [new TextRun({ text: "ACC → AJO Migration Tool  |  Architecture Review Prep", size: 18, color: "888888", font: "Arial" })]
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

const out = "C:\\Users\\pavitram\\Desktop\\accTOajo\\final\\ACCtoAJO\\ACC_to_AJO_Architecture_Review.docx";
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(out, buf); console.log("Saved:", out); });
