ALTER TABLE merchant_api_keys ADD COLUMN scope TEXT NOT NULL DEFAULT 'full' CHECK (scope IN ('full','commerce'));

CREATE TABLE commerce_order_snapshots (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    source TEXT NOT NULL,
    order_reference TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    snapshot_json TEXT NOT NULL,
    contact_json TEXT,
    synced_at TEXT NOT NULL,
    UNIQUE (merchant_id, source, order_reference),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);
