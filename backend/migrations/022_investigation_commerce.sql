-- Forward correction: commerce snapshots moved to commerce_orders in migration 020.
DROP TRIGGER IF EXISTS investigate_commerce_order_snapshots_insert;
DROP TRIGGER IF EXISTS investigate_commerce_order_snapshots_update;
DROP TABLE IF EXISTS commerce_order_snapshots;
CREATE TRIGGER investigate_commerce_orders_insert AFTER INSERT ON commerce_orders
WHEN NEW.resolution_id IS NOT NULL BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id=NEW.resolution_id AND merchant_id=NEW.merchant_id;
END;
CREATE TRIGGER investigate_commerce_orders_update AFTER UPDATE ON commerce_orders
WHEN NEW.resolution_id IS NOT NULL BEGIN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id=NEW.resolution_id AND merchant_id=NEW.merchant_id;
END;
