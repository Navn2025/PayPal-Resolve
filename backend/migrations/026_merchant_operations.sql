CREATE TABLE platform_staff (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('owner','manager','finance','agent','viewer')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL
);
CREATE TABLE platform_sessions (
 token_hash TEXT PRIMARY KEY, staff_id TEXT NOT NULL REFERENCES platform_staff(id),
 created_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX platform_sessions_staff_idx ON platform_sessions(staff_id);
CREATE TABLE platform_invites (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 email TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('manager','finance','agent','viewer')),
 token_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL, used_at TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE platform_auth_limits (
 id TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE platform_audit (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 actor_id TEXT NOT NULL, action TEXT NOT NULL, resource_id TEXT,
 recorded_at TEXT NOT NULL, data_json TEXT NOT NULL
);
CREATE INDEX platform_audit_merchant_idx ON platform_audit(merchant_id,recorded_at);
CREATE TABLE platform_connections (
 merchant_id TEXT NOT NULL REFERENCES merchants(id), provider TEXT NOT NULL,
 config_json TEXT NOT NULL, credentials_ciphertext TEXT NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), revision INTEGER NOT NULL,
 checked_at TEXT, check_status TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(merchant_id,provider)
);
CREATE TABLE platform_imports (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 provider TEXT NOT NULL, ticket_id TEXT NOT NULL, case_id TEXT REFERENCES resolution_cases(id),
 order_reference TEXT, title TEXT NOT NULL, state TEXT NOT NULL,
 suggestions_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(merchant_id,provider,ticket_id)
);
CREATE TABLE platform_ticket_messages (
 id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES platform_imports(id),
 source_id TEXT NOT NULL, sender TEXT NOT NULL CHECK(sender IN ('buyer','merchant')),
 body TEXT NOT NULL, public INTEGER NOT NULL CHECK(public IN (0,1)), sent_at TEXT NOT NULL,
 UNIQUE(import_id,source_id)
);
CREATE TABLE platform_webhook_jobs (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 provider TEXT NOT NULL, event_id TEXT NOT NULL, body_hash TEXT NOT NULL,
 ticket_id TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt_at TEXT NOT NULL, lease_id TEXT, error TEXT, created_at TEXT NOT NULL,
 UNIQUE(merchant_id,provider,event_id)
);
CREATE TABLE platform_alerts (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 case_id TEXT NOT NULL REFERENCES resolution_cases(id), promise_id TEXT NOT NULL,
 promise_revision INTEGER NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL,
 assignee TEXT, reason TEXT NOT NULL, customer_draft TEXT NOT NULL,
 created_at TEXT NOT NULL, resolved_at TEXT,
 UNIQUE(merchant_id,promise_id,promise_revision,day)
);
CREATE TABLE platform_offers (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 case_id TEXT NOT NULL REFERENCES resolution_cases(id), revision INTEGER NOT NULL,
 choices_json TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL,
 selected_choice TEXT, decision_at TEXT, decision_actor TEXT,
 created_at TEXT NOT NULL, UNIQUE(case_id,revision)
);
CREATE TABLE platform_returns (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 case_id TEXT NOT NULL REFERENCES resolution_cases(id), order_id TEXT NOT NULL REFERENCES commerce_orders(id),
 request_id TEXT NOT NULL, revision INTEGER NOT NULL, status TEXT NOT NULL,
 items_json TEXT NOT NULL, reason TEXT NOT NULL, tracking_json TEXT,
 replacement_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(merchant_id,request_id)
);
CREATE TABLE platform_packages (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 case_id TEXT NOT NULL REFERENCES resolution_cases(id), dispute_id TEXT NOT NULL,
 reason TEXT NOT NULL, snapshot_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
 created_at TEXT NOT NULL, reviewed_at TEXT, reviewer_id TEXT,
 UNIQUE(merchant_id,case_id,snapshot_hash)
);
