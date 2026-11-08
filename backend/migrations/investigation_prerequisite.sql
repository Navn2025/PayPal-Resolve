-- Transitional empty table required only while applying the immutable first
-- investigation migration after 020/009 removed the old snapshot table.
-- The immediate forward correction removes it in the same transaction.
CREATE TABLE IF NOT EXISTS commerce_order_snapshots (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    created_at TEXT
);
