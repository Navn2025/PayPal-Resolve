-- Optional. Use only after approving which contact fields may be shared.
-- For example, grant SELECT (order_reference, email) if the SDK only reads email.
-- Mirror the tenant filter from the orders view when the app database is shared.
BEGIN;
CREATE VIEW resolve_evidence.contacts WITH (security_barrier = true) AS
SELECT o.id::text AS order_reference, u.name::text, u.email::text, u.phone::text
FROM public.orders o
JOIN public.users u ON u.id = o.user_id;
GRANT SELECT (order_reference, name, email, phone) ON resolve_evidence.contacts
    TO resolve_evidence_reader;
COMMIT;
