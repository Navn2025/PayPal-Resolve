-- The verified SQLite importer restores tables alphabetically in one transaction.
-- New operations foreign keys must participate in its existing deferred checks.
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT c.conrelid::regclass AS relation, c.conname
    FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
    JOIN pg_namespace n ON n.oid=t.relnamespace
    WHERE c.contype='f' AND n.nspname=current_schema()
      AND t.relname LIKE 'platform_%'
  LOOP
    EXECUTE format('ALTER TABLE %s ALTER CONSTRAINT %I DEFERRABLE INITIALLY IMMEDIATE', item.relation, item.conname);
  END LOOP;
END $$;
