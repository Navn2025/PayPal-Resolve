CREATE TABLE captures (
    capture_id TEXT PRIMARY KEY NOT NULL,
    captured_cents INTEGER NOT NULL CHECK (captured_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD')
);

CREATE TABLE cases (
    id TEXT PRIMARY KEY NOT NULL,
    order_id TEXT NOT NULL,
    complaint TEXT NOT NULL,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
    commitment_json TEXT,
    status TEXT NOT NULL CHECK (status = 'open')
);

CREATE INDEX cases_capture_idx ON cases(capture_id);

CREATE TABLE refunds (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    refund_id TEXT NOT NULL UNIQUE,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed'))
);

CREATE INDEX refunds_capture_idx ON refunds(capture_id);

CREATE TABLE condition_checks (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    status TEXT NOT NULL CHECK (status IN ('met', 'not_met')),
    evidence_note TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE INDEX condition_checks_case_idx ON condition_checks(case_id);
