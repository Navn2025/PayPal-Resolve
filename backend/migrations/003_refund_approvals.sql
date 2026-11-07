CREATE UNIQUE INDEX cases_approval_owner_idx ON cases(id, merchant_id, capture_id);

CREATE TABLE refund_approvals (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    state_fingerprint TEXT NOT NULL,
    request_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    decision_note TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('approved', 'revoked', 'expired', 'invalidated')),
    approved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status_reason TEXT NOT NULL,
    revocation_reason TEXT,
    UNIQUE (merchant_id, request_id),
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE UNIQUE INDEX one_active_approval_per_capture
    ON refund_approvals(merchant_id, capture_id) WHERE status = 'approved';

CREATE INDEX approvals_case_idx ON refund_approvals(case_id, approved_at);

CREATE TABLE refund_approval_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id TEXT NOT NULL REFERENCES refund_approvals(id),
    event_type TEXT NOT NULL CHECK (event_type IN ('approved', 'revoked', 'expired', 'invalidated')),
    actor_merchant_id TEXT REFERENCES merchants(id),
    note TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX approval_events_approval_idx ON refund_approval_events(approval_id, sequence);
