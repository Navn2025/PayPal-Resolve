ALTER TABLE cases ADD COLUMN condition_epoch TEXT;

CREATE TABLE case_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    merchant_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    capture_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (case_id, merchant_id, capture_id)
        REFERENCES cases(id, merchant_id, capture_id) ON UPDATE CASCADE
);

CREATE INDEX case_events_capture_idx ON case_events(merchant_id, capture_id, sequence);
