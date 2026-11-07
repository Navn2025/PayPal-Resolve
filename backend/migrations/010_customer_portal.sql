CREATE TABLE customer_portal_links (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
    show_order_reference INTEGER NOT NULL CHECK (show_order_reference IN (0, 1)),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);

CREATE TABLE customer_portal_messages (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK (sender IN ('customer', 'merchant')),
    request_id TEXT NOT NULL,
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
    created_at TEXT NOT NULL,
    UNIQUE (resolution_id, sender, request_id),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) ON UPDATE CASCADE
);

CREATE INDEX customer_portal_messages_case_idx ON customer_portal_messages(resolution_id, sequence);
CREATE INDEX customer_portal_messages_rate_idx ON customer_portal_messages(resolution_id, sender, created_at);
