CREATE TABLE investigation_jobs (
    resolution_id TEXT PRIMARY KEY NOT NULL,
    merchant_id TEXT NOT NULL,
    revision BIGINT NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','finished','blocked')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(resolution_id,merchant_id) REFERENCES resolution_cases(id,merchant_id)
);
CREATE TABLE investigations (
    id TEXT PRIMARY KEY NOT NULL,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    revision BIGINT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('finished','blocked')),
    created_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE(resolution_id,revision),
    FOREIGN KEY(resolution_id,merchant_id) REFERENCES resolution_cases(id,merchant_id)
);
CREATE INDEX investigations_owner ON investigations(merchant_id,resolution_id,revision);
CREATE TABLE investigation_reviews (
    investigation_id TEXT PRIMARY KEY NOT NULL REFERENCES investigations(id),
    merchant_id TEXT NOT NULL REFERENCES merchants(id),
    receipt_json TEXT NOT NULL
);
CREATE TABLE investigation_audit (
    id TEXT PRIMARY KEY NOT NULL,
    resolution_id TEXT NOT NULL,
    merchant_id TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data_json TEXT NOT NULL,
    FOREIGN KEY(resolution_id,merchant_id) REFERENCES resolution_cases(id,merchant_id)
);
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
    SELECT id,merchant_id,created_at FROM resolution_cases;

CREATE FUNCTION investigate_resolution_events_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_resolution_events_insert AFTER INSERT ON resolution_events FOR EACH ROW EXECUTE FUNCTION investigate_resolution_events_insert_fn();

CREATE FUNCTION investigate_resolution_evidence_links_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_resolution_evidence_links_insert AFTER INSERT ON resolution_evidence_links FOR EACH ROW EXECUTE FUNCTION investigate_resolution_evidence_links_insert_fn();

CREATE FUNCTION investigate_resolution_evidence_state_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_resolution_evidence_state_insert AFTER INSERT ON resolution_evidence_state FOR EACH ROW EXECUTE FUNCTION investigate_resolution_evidence_state_insert_fn();

CREATE FUNCTION investigate_resolution_evidence_state_update_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_resolution_evidence_state_update AFTER UPDATE ON resolution_evidence_state FOR EACH ROW EXECUTE FUNCTION investigate_resolution_evidence_state_update_fn();

CREATE FUNCTION investigate_customer_portal_messages_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_customer_portal_messages_insert AFTER INSERT ON customer_portal_messages FOR EACH ROW EXECUTE FUNCTION investigate_customer_portal_messages_insert_fn();

CREATE FUNCTION investigate_customer_evidence_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_customer_evidence_insert AFTER INSERT ON customer_evidence FOR EACH ROW EXECUTE FUNCTION investigate_customer_evidence_insert_fn();

CREATE FUNCTION investigate_commerce_order_snapshots_insert_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_commerce_order_snapshots_insert AFTER INSERT ON commerce_order_snapshots FOR EACH ROW EXECUTE FUNCTION investigate_commerce_order_snapshots_insert_fn();

CREATE FUNCTION investigate_commerce_order_snapshots_update_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO investigation_jobs(resolution_id,merchant_id,created_at)
 VALUES(NEW.resolution_id,NEW.merchant_id,(SELECT created_at FROM resolution_cases WHERE id=NEW.resolution_id))
 ON CONFLICT(resolution_id) DO UPDATE SET revision=investigation_jobs.revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_commerce_order_snapshots_update AFTER UPDATE ON commerce_order_snapshots FOR EACH ROW EXECUTE FUNCTION investigate_commerce_order_snapshots_update_fn();

CREATE FUNCTION investigate_legacy_event_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL
 WHERE resolution_id IN (
 SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id
 JOIN cases changed ON changed.capture_id=c.capture_id AND changed.merchant_id=c.merchant_id WHERE changed.id=NEW.case_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_legacy_event AFTER INSERT ON case_events FOR EACH ROW EXECUTE FUNCTION investigate_legacy_event_fn();
