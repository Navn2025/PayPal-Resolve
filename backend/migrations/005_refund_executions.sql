CREATE UNIQUE INDEX approval_execution_owner_idx
    ON refund_approvals(id, merchant_id, case_id, capture_id);

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
    UNIQUE (merchant_id, request_id),
    UNIQUE (merchant_id, capture_id),
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE,
    FOREIGN KEY (approval_id, merchant_id, case_id, capture_id)
        REFERENCES refund_approvals(id, merchant_id, case_id, capture_id) ON UPDATE CASCADE
);

CREATE INDEX refund_executions_case_idx ON refund_executions(case_id, created_at);

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

CREATE INDEX paypal_refund_verifications_capture_idx
    ON paypal_refund_verifications(merchant_id, capture_id, sequence);
