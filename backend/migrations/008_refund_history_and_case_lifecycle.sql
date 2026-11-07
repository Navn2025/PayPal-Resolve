-- Preserve prior execution records, events, IDs and provider observations.
ALTER TABLE refund_executions RENAME TO refund_executions_v7;
ALTER TABLE refund_execution_events RENAME TO refund_execution_events_v7;
ALTER TABLE paypal_refund_verifications RENAME TO paypal_refund_verifications_v7;

CREATE TABLE refund_executions (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    approval_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    provider_request_id TEXT NOT NULL UNIQUE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    status TEXT NOT NULL CHECK (status IN ('reserved','submitting','unknown','pending','completed','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    approval_json TEXT NOT NULL,
    capture_check_json TEXT NOT NULL,
    provider_request_json TEXT NOT NULL,
    provider_refund_id TEXT,
    provider_refund_json TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    lease_expires_at TEXT,
    provider_identity_hash TEXT,
    UNIQUE (merchant_id, request_id),
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE,
    FOREIGN KEY (approval_id, merchant_id, case_id, capture_id)
        REFERENCES refund_approvals(id, merchant_id, case_id, capture_id) ON UPDATE CASCADE
);



CREATE TABLE refund_execution_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL REFERENCES refund_executions(id),
    status TEXT NOT NULL CHECK (status IN ('reserved','submitting','unknown','pending','completed','failed')),
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    snapshot_json TEXT
);

CREATE TABLE paypal_refund_verifications (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    refund_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    provider_status TEXT NOT NULL CHECK (provider_status IN ('CANCELLED','FAILED','PENDING','COMPLETED')),
    checked_at TEXT NOT NULL,
    execution_id TEXT REFERENCES refund_executions(id),
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);



INSERT INTO refund_executions (id,merchant_id,case_id,capture_id,approval_id,request_id,provider_request_id,amount_cents,currency,status,attempt_count,approval_json,capture_check_json,provider_request_json,provider_refund_id,provider_refund_json,error_code,created_at,updated_at,lease_expires_at,provider_identity_hash) SELECT id,merchant_id,case_id,capture_id,approval_id,request_id,provider_request_id,amount_cents,currency,status,attempt_count,approval_json,capture_check_json,provider_request_json,provider_refund_id,provider_refund_json,error_code,created_at,updated_at,lease_expires_at,provider_identity_hash FROM refund_executions_v7;
INSERT INTO refund_execution_events SELECT * FROM refund_execution_events_v7;
INSERT INTO paypal_refund_verifications SELECT * FROM paypal_refund_verifications_v7;
DROP TABLE paypal_refund_verifications_v7;
DROP TABLE refund_execution_events_v7;
DROP TABLE refund_executions_v7;
CREATE INDEX refund_executions_case_idx ON refund_executions(case_id, created_at);
CREATE INDEX paypal_refund_verifications_capture_idx
    ON paypal_refund_verifications(merchant_id, capture_id, sequence);

CREATE UNIQUE INDEX refund_executions_active_capture_idx
    ON refund_executions(merchant_id, capture_id)
    WHERE status IN ('reserved','submitting','unknown','pending');

ALTER TABLE cases ADD COLUMN closed_at TEXT;
ALTER TABLE cases ADD COLUMN lifecycle_revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE paypal_refund_history (
    merchant_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    revision TEXT NOT NULL,
    digest TEXT NOT NULL,
    order_id TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY (merchant_id, capture_id),
    FOREIGN KEY (merchant_id, capture_id) REFERENCES captures(merchant_id, capture_id)
        ON UPDATE CASCADE
);

CREATE TABLE paypal_webhook_events (
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    event_id TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    event_type TEXT NOT NULL,
    capture_id TEXT,
    refund_id TEXT,
    received_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','processed','ignored','exception')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    PRIMARY KEY (merchant_id, event_id)
);

CREATE INDEX paypal_webhook_due_idx ON paypal_webhook_events(merchant_id, status, next_attempt_at);
CREATE INDEX paypal_webhook_capture_idx ON paypal_webhook_events(merchant_id, capture_id, status);

CREATE TABLE review_exceptions (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    case_id TEXT,
    capture_id TEXT,
    source_key TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','resolved')),
    blocking INTEGER NOT NULL CHECK (blocking IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolution_note TEXT,
    UNIQUE (merchant_id, source_key),
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE INDEX review_exceptions_queue_idx
    ON review_exceptions(merchant_id, status, updated_at);
CREATE INDEX review_exceptions_capture_idx
    ON review_exceptions(merchant_id, capture_id, status, blocking);

INSERT INTO review_exceptions
    (id,merchant_id,case_id,capture_id,source_key,reason,status,blocking,created_at,updated_at)
SELECT lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-' || hex(randomblob(2))
    || '-' || hex(randomblob(2)) || '-' || hex(randomblob(6))),
    merchant_id,case_id,capture_id,'execution:' || id,'refund_execution_' || status,
    'open',0,updated_at,updated_at
FROM refund_executions WHERE status IN ('unknown','failed');

CREATE TABLE case_attachments (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes BETWEEN 1 AND 2097152),
    sha256 TEXT NOT NULL,
    content BLOB NOT NULL CHECK (length(content) = size_bytes),
    created_at TEXT NOT NULL,
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE INDEX case_attachments_owner_idx ON case_attachments(merchant_id, case_id, created_at);
