DROP TRIGGER IF EXISTS investigate_commerce_order_snapshots_insert ON commerce_order_snapshots;
DROP TRIGGER IF EXISTS investigate_commerce_order_snapshots_update ON commerce_order_snapshots;
DROP TABLE IF EXISTS commerce_order_snapshots;
DROP FUNCTION IF EXISTS investigate_commerce_order_snapshots_insert_fn();
DROP FUNCTION IF EXISTS investigate_commerce_order_snapshots_update_fn();
CREATE FUNCTION investigate_commerce_orders_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
IF NEW.resolution_id IS NOT NULL THEN
UPDATE investigation_jobs SET revision=revision+1,state='queued',attempts=0,lease_token=NULL,lease_until=NULL WHERE resolution_id=NEW.resolution_id AND merchant_id=NEW.merchant_id;
END IF;
RETURN NEW; END; $$;
CREATE TRIGGER investigate_commerce_orders AFTER INSERT OR UPDATE ON commerce_orders FOR EACH ROW EXECUTE FUNCTION investigate_commerce_orders_fn();
