# ACC Authentication Backend

FastAPI backend that authenticates React users against **Adobe Campaign Classic** via SOAP.

---

## Project layout

```
project/
├── main.py            # FastAPI app – routes, CORS, session cookie
├── acc_soap.py        # SOAP envelope builders + XML parsers
├── config.py          # Pydantic-settings config (reads .env)
├── session_store.py   # In-memory token store (swap for Redis in prod)
├── requirements.txt
├── .env.example       # Copy to .env and fill in
└── frontend/
    ├── useLogin.js    # React hook – calls POST /login
    └── LoginForm.jsx  # Example form component
```

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env – set ACC_ENDPOINT, SECRET_KEY, CORS_ORIGINS_RAW

# 4. Run the development server
uvicorn main:app --reload --port 8000
```

The API is now available at `http://localhost:8000`.  
Interactive docs: `http://localhost:8000/docs`

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ACC_ENDPOINT` | `http://127.0.0.1:8080/nl/jsp/soaprouter.jsp` | ACC SOAP router URL |
| `SOAP_TIMEOUT` | `30.0` | Seconds before a SOAP call times out |
| `CORS_ORIGINS_RAW` | `http://localhost:3000` | Comma-separated allowed origins |
| `SECRET_KEY` | `change-me-in-production` | Used for signed cookies / JWT |
| `DEBUG` | `false` | Enables verbose logging |

---

## API

### `POST /login`

**Request body**
```json
{ "loginId": "admin", "password": "secret" }
```

**Success (200)**
```json
{
  "authorized": true,
  "message": "OK",
  "session_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```
An `acc_session` HttpOnly cookie is also set – the frontend should include
`credentials: "include"` in subsequent fetch calls so the cookie is forwarded.

**Authentication failure (200 with `authorized: false`)**
```json
{
  "authorized": false,
  "message": "Invalid login or password.",
  "session_id": null
}
```

**Network / server error (502)**
```json
{ "detail": "Cannot reach Adobe Campaign Classic" }
```

### `GET /health`
```json
{ "status": "ok" }
```

---

## SOAP envelopes (reference)

### xtk:session#Logon
```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:urn="urn:xtk:session">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:Logon>
      <urn:sessiontoken/>
      <urn:strLogin>LOGIN_ID</urn:strLogin>
      <urn:strPassword>PASSWORD</urn:strPassword>
      <urn:elemParameters/>
    </urn:Logon>
  </soapenv:Body>
</soapenv:Envelope>
```

### xtk:session#TestCnx
```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:urn="urn:xtk:session">
  <soapenv:Header>
    <urn:SecurityHeader>
      <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
      <urn:securityToken>SECURITY_TOKEN</urn:securityToken>
    </urn:SecurityHeader>
  </soapenv:Header>
  <soapenv:Body>
    <urn:TestCnx/>
  </soapenv:Body>
</soapenv:Envelope>
```
HTTP headers also required:
```
Cookie: __sessiontoken=SESSION_TOKEN
X-Security-Token: SECURITY_TOKEN
```

### xtk:queryDef#ExecuteQuery (future use)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope
    xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:urn="urn:xtk:queryDef">
  <soapenv:Header>
    <urn:SecurityHeader xmlns:urn="urn:xtk:session">
      <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
      <urn:securityToken>SECURITY_TOKEN</urn:securityToken>
    </urn:SecurityHeader>
  </soapenv:Header>
  <soapenv:Body>
    <urn:ExecuteQuery>
      <urn:sessiontoken>SESSION_TOKEN</urn:sessiontoken>
      <urn:entity>
        <queryDef schema="nms:recipient" operation="select" lineCount="5" startLine="0">
          <select>
            <node expr="@firstName"/>
            <node expr="@lastName"/>
            <node expr="@email"/>
          </select>
          <where>
            <condition expr="@email != ''"/>
          </where>
        </queryDef>
      </urn:entity>
    </urn:ExecuteQuery>
  </soapenv:Body>
</soapenv:Envelope>
```

---

## Production checklist

- [ ] Replace in-memory `SessionStore` with Redis (`redis-py` / `aioredis`)
- [ ] Set `SECRET_KEY` to a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`)
- [ ] Run behind HTTPS – set `secure=True` on the cookie (already done when `DEBUG=false`)
- [ ] Restrict `CORS_ORIGINS_RAW` to your actual frontend domain
- [ ] Add a `/logout` endpoint that calls `xtk:session#Logoff` and clears the cookie
- [ ] Add a background task to call `store.purge_expired()` periodically
- [ ] Consider rate-limiting `/login` to prevent brute-force attacks
