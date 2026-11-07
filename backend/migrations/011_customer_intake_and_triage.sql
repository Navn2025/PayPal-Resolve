CREATE TABLE customer_intake_invites (
    token_hash TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    order_reference TEXT NOT NULL CHECK(length(order_reference) BETWEEN 1 AND 160),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resolution_id TEXT UNIQUE,
    submitted_at TEXT,
    issue_type TEXT,
    CHECK ((resolution_id IS NULL) = (submitted_at IS NULL)),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);

CREATE TABLE customer_evidence (
    id TEXT PRIMARY KEY NOT NULL,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content BLOB NOT NULL,
    size_bytes INTEGER NOT NULL CHECK(size_bytes BETWEEN 1 AND 2097152),
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (resolution_id, filename, sha256),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);
CREATE INDEX customer_evidence_case_idx ON customer_evidence(resolution_id, created_at, id);

CREATE TABLE resolution_operations (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    assignee TEXT,
    due_at TEXT,
    waiting_on_customer INTEGER NOT NULL DEFAULT 0 CHECK(waiting_on_customer IN (0,1)),
    read_through INTEGER NOT NULL DEFAULT 0 CHECK(read_through >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);
