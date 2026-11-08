-- Run in the merchant application's database after adapting table/column names.
-- A DBA creates a dedicated LOGIN with no broad grants and gives it membership
-- in resolve_evidence_reader. Keep that login's connection URL on the app server.
-- Use one merchant's rows per connection. For shared databases, apply explicit
-- tenant filters to every view before granting the role access.
BEGIN;
CREATE ROLE resolve_evidence_reader NOLOGIN;
CREATE SCHEMA resolve_evidence;
REVOKE ALL ON SCHEMA resolve_evidence FROM PUBLIC;

CREATE VIEW resolve_evidence.orders WITH (security_barrier = true) AS
SELECT o.id::text AS order_reference, o.evidence_revision AS revision,
       o.status::text AS order_status, o.user_id::text AS customer_reference
FROM public.orders o;

CREATE VIEW resolve_evidence.payments WITH (security_barrier = true) AS
SELECT p.order_id::text AS order_reference, p.paypal_order_id::text, p.paypal_capture_id::text,
       p.currency::text, p.status::text, p.captured_amount, p.refunded_amount
FROM public.payments p
WHERE p.provider = 'paypal';

CREATE VIEW resolve_evidence.items WITH (security_barrier = true) AS
SELECT i.order_id::text AS order_reference, i.id AS line_id, i.product_id::text AS product_id,
       p.name::text, p.sku::text, i.quantity, i.unit_amount
FROM public.order_items i
LEFT JOIN public.products p ON p.id = i.product_id;

GRANT USAGE ON SCHEMA resolve_evidence TO resolve_evidence_reader;
GRANT SELECT ON resolve_evidence.orders, resolve_evidence.payments, resolve_evidence.items
    TO resolve_evidence_reader;
COMMIT;
