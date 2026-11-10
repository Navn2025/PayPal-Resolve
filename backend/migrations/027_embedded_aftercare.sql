CREATE TABLE aftercare_apps (
 key_id TEXT PRIMARY KEY REFERENCES merchant_api_keys(id),
 merchant_id TEXT NOT NULL REFERENCES merchants(id),
 source TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE aftercare_issues (
 id TEXT PRIMARY KEY, merchant_id TEXT NOT NULL REFERENCES merchants(id),
 order_id TEXT NOT NULL REFERENCES commerce_orders(id),
 case_id TEXT NOT NULL REFERENCES resolution_cases(id),
 request_id TEXT NOT NULL, request_json TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(merchant_id,request_id)
);
CREATE INDEX aftercare_issues_case_idx ON aftercare_issues(merchant_id,case_id);
