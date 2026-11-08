CREATE FUNCTION investigate_paypal_capture_verifications_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_paypal_capture_verifications AFTER INSERT ON paypal_capture_verifications FOR EACH ROW EXECUTE FUNCTION investigate_paypal_capture_verifications_fn();
CREATE FUNCTION investigate_paypal_refund_verifications_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
RETURN NEW; END; $$;
CREATE TRIGGER investigate_paypal_refund_verifications AFTER INSERT ON paypal_refund_verifications FOR EACH ROW EXECUTE FUNCTION investigate_paypal_refund_verifications_fn();
