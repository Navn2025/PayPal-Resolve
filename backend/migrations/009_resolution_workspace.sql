CREATE UNIQUE INDEX cases_resolution_owner_idx ON cases(id, merchant_id);

CREATE TABLE resolution_cases (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    refund_case_id TEXT,
    title TEXT NOT NULL,
    order_reference TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (id, merchant_id),
    UNIQUE (merchant_id, refund_case_id),
    FOREIGN KEY (refund_case_id, merchant_id) REFERENCES cases(id, merchant_id) ON UPDATE CASCADE
);

CREATE INDEX resolution_cases_owner_idx ON resolution_cases(merchant_id, created_at, id);

CREATE TABLE resolution_promises (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('refund','return','replacement','order_cancellation',
        'subscription','store_credit_or_exchange','billing_correction','dispute_handoff')),
    revision INTEGER NOT NULL CHECK (revision > 0),
    promise_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (id, resolution_id, merchant_id),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);

CREATE UNIQUE INDEX resolution_refund_promise_idx
    ON resolution_promises(resolution_id) WHERE kind='refund';
CREATE INDEX resolution_promises_case_idx ON resolution_promises(resolution_id, sequence);

CREATE TABLE resolution_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    promise_id TEXT,
    revision INTEGER,
    event_type TEXT NOT NULL CHECK (event_type IN ('case_created','promise_recorded','promise_revised',
        'merchant_evidence','provider_observation','verification_failed')),
    source TEXT NOT NULL CHECK (source IN ('merchant_recorded','provider_confirmed','system')),
    recorded_at TEXT NOT NULL,
    data_json TEXT NOT NULL,
    CHECK ((promise_id IS NULL) = (revision IS NULL)),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE,
    FOREIGN KEY (promise_id, resolution_id, merchant_id)
        REFERENCES resolution_promises(id, resolution_id, merchant_id) ON UPDATE CASCADE
);

CREATE INDEX resolution_events_case_idx ON resolution_events(resolution_id, sequence);
CREATE INDEX resolution_events_proof_idx ON resolution_events(promise_id, revision, sequence);
