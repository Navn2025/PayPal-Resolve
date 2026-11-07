-- Old actions without an identity fingerprint may only be reconciled by reads.
ALTER TABLE refund_executions ADD COLUMN provider_identity_hash TEXT;
