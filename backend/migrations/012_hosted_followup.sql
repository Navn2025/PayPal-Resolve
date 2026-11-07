ALTER TABLE customer_intake_invites ADD COLUMN customer_email TEXT;

CREATE TABLE customer_case_contacts (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (resolution_id,merchant_id) REFERENCES resolution_cases(id,merchant_id)
);
CREATE INDEX customer_contacts_email_idx ON customer_case_contacts(email,resolution_id);

CREATE TABLE customer_signins (
    token_hash TEXT PRIMARY KEY NOT NULL,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE INDEX customer_signins_email_idx ON customer_signins(email,created_at);

CREATE TABLE customer_sessions (
    token_hash TEXT PRIMARY KEY NOT NULL,
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE customer_account_links (
    token_hash TEXT PRIMARY KEY NOT NULL,
    session_hash TEXT NOT NULL REFERENCES customer_sessions(token_hash) ON DELETE CASCADE,
    resolution_id TEXT NOT NULL REFERENCES customer_case_contacts(resolution_id),
    parent_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE customer_mail_outbox (
    id TEXT PRIMARY KEY NOT NULL,
    event_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('invite','signin','reply','refund')),
    recipient TEXT NOT NULL,
    resolution_id TEXT REFERENCES resolution_cases(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','accepted','failed','cancelled')),
    provider_id TEXT
);
CREATE INDEX customer_mail_due_idx ON customer_mail_outbox(status,next_attempt_at);

CREATE TABLE provider_refresh_schedule (
    promise_id TEXT PRIMARY KEY NOT NULL REFERENCES resolution_promises(id),
    revision INTEGER NOT NULL,
    next_attempt_at TEXT NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    lease_id TEXT
);

CREATE TABLE resolution_helpdesk (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    host TEXT NOT NULL,
    ticket_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    FOREIGN KEY (resolution_id,merchant_id) REFERENCES resolution_cases(id,merchant_id)
);
