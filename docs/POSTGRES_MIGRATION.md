# Move Resolve from SQLite to PostgreSQL

Choose **Neon** for the current Resolve demo. We need a PostgreSQL database;
FastAPI already owns merchant access, customer sign-in, and evidence storage.
The repository uses ordinary PostgreSQL with no vendor SDK, so Supabase is
also an option if you want its [Auth and Storage platform](https://supabase.com/docs/guides/database/overview)
for later milestones. The migration itself does not switch either service.

## Import into a fresh database

1. Create a database or disposable branch in [Neon](https://console.neon.tech/).
   Copy the **direct** connection URL from the Connect dialog for the import.
   Use the provider's TLS options. For Supabase, use its direct URL or the
   [session pooler](https://supabase.com/docs/guides/database/connecting-to-postgres)
   if your machine cannot reach the direct host.
2. Stop the SQLite API and both workers before the final copy. Keep a backup
   of the source file. Put the connection string in `backend/.env` (ignored
   by Git). Use a dedicated Resolve database or branch; the app owns a private
   `resolve` schema. Do not put a database URL in frontend settings or chat.

   ```dotenv
   RESOLVE_DATABASE_URL=postgresql://ROLE:PASSWORD@HOST/DATABASE?sslmode=require
   ```

3. From the repository root, run:

   ```powershell
   uv --directory backend sync
   uv --directory backend run python -m app.migrate_sqlite
   ```

   The default source is the configured SQLite file. Use `--source PATH` to
   import a specific backup. The importer opens SQLite read-only, upgrades a
   private copy if needed, checks its integrity, and copies to an empty
   Resolve schema. It verifies foreign keys and compares the copied rows,
   including attachment bytes, before committing. It keeps record IDs,
   stored key hashes, timestamps, cents, and identity sequence high-water
   marks. A populated destination is rejected; there is no merge mode.
4. Start FastAPI with the same `RESOLVE_DATABASE_URL`. Verify an existing
   merchant key, case, and settlement before starting the workers. If you
   later switch the runtime to [Neon's pooled endpoint](https://neon.com/docs/connect/choose-connection),
   select the same branch and database. The API and both workers must use
   the same database. Inspect any imported pending work before enabling
   delivery or refund execution.

SQLite remains the default when `RESOLVE_DATABASE_URL` is unset. The import
does not change the source file or the app's environment. Once writes start
on PostgreSQL, do not switch back to the old SQLite copy as a rollback
without accounting for writes made since the copy.

The API contract is unchanged. PostgreSQL writes take a transaction-scoped
lock in the Resolve schema before reading or changing state, preserving the
SQLite serialization used by refund approvals and reservations. Reads use a
repeatable snapshot. This first implementation prioritizes correctness and
works with one writer at a time; it does not claim high-volume write scaling.
SQLite and PostgreSQL have separate migration histories; add corresponding
schema changes to both while both backends are supported.
The database stores evidence as bytes, so monitor storage as uploads grow.
If you use a free Neon tier, check its [usage limits](https://neon.com/docs/introduction/plans)
when running an always-on polling worker.

## PostgreSQL migration history errors

Startup compares the applied migration history to the SQL shipped with Resolve.
The original migration 003 is preserved, and migration 004 adds the PayPal
callback claim column. The original migration 005 is also preserved; 006 adds
email notification flags to existing invites and contacts. Resolve recognizes
the exact interim checksum for each migration if the new columns were already
applied. Restart the backend with the updated code and the same database
configuration to upgrade.

If an unknown checksum or a newer schema still prevents startup, check that the
running release has the original migrations for that database. Keep the history
table and existing data intact; editing checksums or resetting the schema does
not repair a migration mismatch.

Treat numbered migrations as immutable even before committing: a backend
running with `--reload` may already have applied them. The default backend
test suite checks the known PostgreSQL migration checksums even without a
PostgreSQL connection.

## Test PostgreSQL locally

Point the integration tests to a disposable PostgreSQL database. They create
and remove uniquely named test schemas. Use a separate database from the one
you plan to deploy.

```powershell
$env:RESOLVE_TEST_DATABASE_URL = 'postgresql://USER:PASSWORD@127.0.0.1:5432/TEST_DB'
$env:RESOLVE_TEST_STORAGE = 'postgres'
uv --directory backend run python -m pytest -q tests/test_postgres.py tests/test_customer_portal.py tests/test_customer_workflow.py tests/test_hosted_followup.py tests/test_resolution_workspace.py
```
