-- ACC → AJO database schema
-- Database: acc_ajo
-- Run: psql -U postgres -d acc_ajo -f schema.sql

-- Stores Adobe Campaign Classic (ACC) connection credentials and SOAP session tokens.
CREATE TABLE IF NOT EXISTS source_connections (
    id                   TEXT PRIMARY KEY,
    login_id             VARCHAR(255) NOT NULL UNIQUE,
    encrypted_password   TEXT         NOT NULL,
    session_token        TEXT,
    security_token       TEXT,
    authenticated        BOOLEAN      NOT NULL DEFAULT FALSE,
    last_authenticated_at TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Stores Adobe Journey Optimizer (AJO / AEP) OAuth credentials and IMS access token.
CREATE TABLE IF NOT EXISTS destination_connections (
    id                    TEXT PRIMARY KEY,
    org_id                VARCHAR(255) NOT NULL UNIQUE,
    client_id             VARCHAR(255),
    sandbox_name          VARCHAR(255),
    encrypted_credentials TEXT,                  -- Fernet-encrypted "clientId:clientSecret"
    encrypted_access_token TEXT,                 -- Fernet-encrypted IMS access token
    token_expires_at      TIMESTAMPTZ,           -- When the access token expires
    authenticated         BOOLEAN      NOT NULL DEFAULT FALSE,
    last_authenticated_at TIMESTAMPTZ,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Tracks active browser sessions tied to an ACC login.
CREATE TABLE IF NOT EXISTS user_sessions (
    id         TEXT PRIMARY KEY,                 -- UUID, stored in acc_session cookie
    login_id   VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ  NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_login_id ON user_sessions (login_id);
