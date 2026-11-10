CREATE TABLE assurance_policies (
 merchant_id TEXT PRIMARY KEY REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, revision INTEGER NOT NULL,
 data_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE assurance_return_guides (
 return_id TEXT PRIMARY KEY REFERENCES platform_returns(id) DEFERRABLE INITIALLY IMMEDIATE, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE,
 revision INTEGER NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE assurance_return_labels (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, return_id TEXT NOT NULL REFERENCES platform_returns(id) DEFERRABLE INITIALLY IMMEDIATE,
 filename TEXT NOT NULL, content BYTEA NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE assurance_return_reviews (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, return_id TEXT NOT NULL REFERENCES platform_returns(id) DEFERRABLE INITIALLY IMMEDIATE,
 request_id TEXT NOT NULL, kind TEXT NOT NULL, data_json TEXT NOT NULL, actor_id TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(merchant_id,request_id)
);
CREATE TABLE assurance_disputes (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, capture_id TEXT NOT NULL,
 provider TEXT NOT NULL, reference TEXT NOT NULL, version INTEGER NOT NULL,
 state TEXT NOT NULL, data_json TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(merchant_id,provider,reference)
);
CREATE TABLE assurance_dispute_events (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, provider TEXT NOT NULL,
 event_id TEXT NOT NULL, body_hash TEXT NOT NULL, reference TEXT NOT NULL, version INTEGER NOT NULL,
 outcome TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(merchant_id,provider,event_id)
);
CREATE TABLE assurance_refund_traces (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, capture_id TEXT NOT NULL,
 refund_id TEXT NOT NULL, request_id TEXT NOT NULL, data_json TEXT NOT NULL,
 actor_id TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(merchant_id,request_id)
);
CREATE TABLE assurance_receipts (
 resolution_id TEXT PRIMARY KEY REFERENCES resolution_cases(id) DEFERRABLE INITIALLY IMMEDIATE, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE,
 received_at TEXT NOT NULL, source TEXT NOT NULL
);
CREATE TABLE assurance_projections (
 order_id TEXT PRIMARY KEY REFERENCES commerce_orders(id) DEFERRABLE INITIALLY IMMEDIATE, merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE,
 revision INTEGER NOT NULL, fingerprint TEXT NOT NULL, snapshot_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE assurance_events (
 sequence BIGSERIAL PRIMARY KEY, id TEXT NOT NULL UNIQUE,
 merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE, source TEXT NOT NULL,
 order_id TEXT NOT NULL REFERENCES commerce_orders(id) DEFERRABLE INITIALLY IMMEDIATE, order_reference TEXT NOT NULL,
 revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(order_id,revision)
);
CREATE INDEX assurance_events_scope_idx ON assurance_events(merchant_id,source,sequence);
