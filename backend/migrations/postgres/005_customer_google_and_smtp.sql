CREATE TABLE customer_google_flows (
    state_hash TEXT PRIMARY KEY NOT NULL,
    browser_hash TEXT NOT NULL,
    app_key TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX customer_google_flow_expiry_idx ON customer_google_flows(expires_at);

ALTER TABLE customer_mail_outbox ADD COLUMN delivery_transport TEXT CHECK (delivery_transport IN ('resend','smtp'));
UPDATE customer_mail_outbox SET delivery_transport='resend' WHERE attempts>0;
