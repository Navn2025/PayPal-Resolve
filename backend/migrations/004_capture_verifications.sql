CREATE TABLE paypal_capture_verifications (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    paypal_merchant_id TEXT NOT NULL,
    captured_cents INTEGER NOT NULL CHECK (captured_cents > 0),
    currency TEXT NOT NULL CHECK (currency = 'USD'),
    capture_status TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE INDEX paypal_capture_verifications_capture_idx
    ON paypal_capture_verifications(merchant_id, capture_id, sequence);
