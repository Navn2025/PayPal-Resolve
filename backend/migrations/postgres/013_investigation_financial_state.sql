CREATE FUNCTION investigate_paypal_refund_history_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_paypal_refund_history AFTER INSERT OR UPDATE ON paypal_refund_history FOR EACH ROW EXECUTE FUNCTION investigate_paypal_refund_history_fn();
CREATE FUNCTION investigate_refund_approvals_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_refund_approvals AFTER INSERT OR UPDATE ON refund_approvals FOR EACH ROW EXECUTE FUNCTION investigate_refund_approvals_fn();
CREATE FUNCTION investigate_refund_executions_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_refund_executions AFTER INSERT OR UPDATE ON refund_executions FOR EACH ROW EXECUTE FUNCTION investigate_refund_executions_fn();
CREATE FUNCTION investigate_review_exceptions_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_review_exceptions AFTER INSERT OR UPDATE ON review_exceptions FOR EACH ROW EXECUTE FUNCTION investigate_review_exceptions_fn();
