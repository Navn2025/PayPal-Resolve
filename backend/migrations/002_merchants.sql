ALTER TABLE captures RENAME TO legacy_captures;
ALTER TABLE cases RENAME TO legacy_cases;
ALTER TABLE refunds RENAME TO legacy_refunds;
ALTER TABLE condition_checks RENAME TO legacy_condition_checks;

CREATE TABLE merchants (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE merchant_api_keys (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    token_hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

INSERT INTO merchants VALUES (
    '00000000-0000-0000-0000-000000000000',
    'Unassigned legacy development records',
    strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
);

CREATE TABLE captures (
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    capture_id TEXT NOT NULL,
    captured_cents INTEGER NOT NULL CHECK (captured_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    PRIMARY KEY (merchant_id, capture_id)
);

CREATE TABLE cases (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    order_id TEXT NOT NULL,
    complaint TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    commitment_json TEXT,
    status TEXT NOT NULL CHECK (status = 'open'),
    FOREIGN KEY (merchant_id, capture_id)
        REFERENCES captures(merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE TABLE refunds (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    refund_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    UNIQUE (merchant_id, refund_id),
    FOREIGN KEY (merchant_id, capture_id)
        REFERENCES captures(merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE TABLE condition_checks (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    status TEXT NOT NULL CHECK (status IN ('met', 'not_met')),
    evidence_note TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    recorded_by_merchant_id TEXT REFERENCES merchants(id)
);

INSERT INTO captures
    SELECT '00000000-0000-0000-0000-000000000000', capture_id, captured_cents, currency
    FROM legacy_captures;
INSERT INTO cases
    SELECT id, '00000000-0000-0000-0000-000000000000', order_id, complaint,
           capture_id, commitment_json, status FROM legacy_cases;
INSERT INTO refunds
    SELECT sequence, '00000000-0000-0000-0000-000000000000', refund_id, capture_id,
           amount_cents, currency, status FROM legacy_refunds;
INSERT INTO condition_checks
    SELECT sequence, case_id, status, evidence_note, recorded_at, NULL
    FROM legacy_condition_checks;

DROP TABLE legacy_condition_checks;
DROP TABLE legacy_refunds;
DROP TABLE legacy_cases;
DROP TABLE legacy_captures;

CREATE INDEX cases_merchant_capture_idx ON cases(merchant_id, capture_id);
CREATE INDEX refunds_merchant_capture_idx ON refunds(merchant_id, capture_id);
CREATE INDEX condition_checks_case_idx ON condition_checks(case_id);
