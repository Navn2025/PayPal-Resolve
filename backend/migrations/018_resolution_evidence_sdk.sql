CREATE TABLE resolution_evidence_refs (
    merchant_id TEXT NOT NULL,
    external_reference TEXT NOT NULL,
    resolution_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    PRIMARY KEY (merchant_id, external_reference),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE resolution_evidence_links (
    id TEXT PRIMARY KEY NOT NULL,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('order','paypal_order','paypal_capture','paypal_refund','support_ticket')),
    reference TEXT NOT NULL,
    source TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    UNIQUE (resolution_id, kind, reference),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);
CREATE UNIQUE INDEX resolution_evidence_primary_payment ON resolution_evidence_links(resolution_id, kind)
    WHERE kind IN ('paypal_order','paypal_capture');

CREATE TABLE resolution_evidence_events (
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('merchant','paypal')),
    source TEXT NOT NULL,
    event_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE REFERENCES resolution_events(id) DEFERRABLE INITIALLY IMMEDIATE,
    PRIMARY KEY (resolution_id, origin, source, event_key),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE resolution_evidence_state (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);
