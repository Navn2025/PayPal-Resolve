CREATE TABLE commerce_orders (
    id TEXT PRIMARY KEY NOT NULL,
    resolution_id TEXT UNIQUE,
    merchant_id TEXT NOT NULL REFERENCES merchants(id) DEFERRABLE INITIALLY IMMEDIATE,
    source TEXT NOT NULL,
    order_reference TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    snapshot_json TEXT NOT NULL,
    contact_json TEXT,
    synced_at TEXT NOT NULL,
    UNIQUE (merchant_id, source, order_reference),
    FOREIGN KEY (resolution_id, merchant_id) REFERENCES resolution_cases(id, merchant_id) DEFERRABLE INITIALLY IMMEDIATE
);

INSERT INTO commerce_orders (id, resolution_id, merchant_id, source, order_reference, revision, snapshot_json, contact_json, synced_at)
SELECT resolution_id, resolution_id, merchant_id, source, order_reference, revision, snapshot_json, contact_json, synced_at
FROM commerce_order_snapshots;

DROP TABLE commerce_order_snapshots;

CREATE INDEX commerce_orders_merchant_recent ON commerce_orders(merchant_id, synced_at DESC, id DESC);
