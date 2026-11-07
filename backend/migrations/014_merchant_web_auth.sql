CREATE TABLE merchant_paypal_links (
    id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    issuer_key TEXT NOT NULL,
    subject_hash TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    UNIQUE (merchant_id,issuer_key),
    UNIQUE (issuer_key,subject_hash)
);

CREATE TABLE merchant_web_sessions (
    token_hash TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    api_key_id TEXT REFERENCES merchant_api_keys(id) ON DELETE CASCADE,
    paypal_link_id TEXT REFERENCES merchant_paypal_links(id) ON DELETE CASCADE,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    CHECK ((api_key_id IS NULL) <> (paypal_link_id IS NULL))
);
CREATE INDEX merchant_web_session_expiry_idx ON merchant_web_sessions(expires_at);

CREATE TABLE merchant_paypal_flows (
    state_hash TEXT PRIMARY KEY NOT NULL,
    browser_hash TEXT NOT NULL,
    issuer_key TEXT NOT NULL,
    intent TEXT NOT NULL CHECK (intent IN ('signin','link')),
    session_hash TEXT REFERENCES merchant_web_sessions(token_hash) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    CHECK ((intent='link') = (session_hash IS NOT NULL))
);
CREATE INDEX merchant_paypal_flow_expiry_idx ON merchant_paypal_flows(expires_at);
