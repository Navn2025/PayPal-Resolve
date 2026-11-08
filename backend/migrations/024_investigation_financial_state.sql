CREATE TRIGGER investigate_paypal_refund_history_insert AFTER INSERT ON paypal_refund_history BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_paypal_refund_history_update AFTER UPDATE ON paypal_refund_history BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_refund_approvals_insert AFTER INSERT ON refund_approvals BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_refund_approvals_update AFTER UPDATE ON refund_approvals BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_refund_executions_insert AFTER INSERT ON refund_executions BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_refund_executions_update AFTER UPDATE ON refund_executions BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_review_exceptions_insert AFTER INSERT ON review_exceptions BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
CREATE TRIGGER investigate_review_exceptions_update AFTER UPDATE ON review_exceptions BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id IN (SELECT r.id FROM resolution_cases r JOIN cases c ON c.id=r.refund_case_id AND c.merchant_id=r.merchant_id WHERE c.capture_id=NEW.capture_id AND c.merchant_id=NEW.merchant_id);
END;
