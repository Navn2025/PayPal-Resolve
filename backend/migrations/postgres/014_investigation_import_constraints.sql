-- The verified importer loads alphabetically in one deferred transaction.
DO $$ DECLARE item record; BEGIN
FOR item IN SELECT conrelid::regclass AS relation,conname FROM pg_constraint
WHERE contype='f' AND conrelid IN ('investigation_jobs'::regclass,'investigations'::regclass,'investigation_reviews'::regclass,'investigation_audit'::regclass)
LOOP
EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE',item.relation,item.conname);
END LOOP; END; $$;
