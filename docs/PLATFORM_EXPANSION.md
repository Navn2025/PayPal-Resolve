# Merchant operations expansion

Implementation scope for CHG-048, 2026-11-10. All endpoints retain merchant
ownership and separate refund approval/execution. Provider access is opt-in;
local test evidence does not establish account-backed success.

## Implemented workflows

1. `POST /platform/account/signup`, `/login`, `/accept-invite` create individual
   password-backed sessions. Owners invite staff and change roles at
   `/platform/team`. Roles: owner, manager (refund approvals), finance (refund
   execution), agent (case work), viewer (read only). Existing full merchant keys
   retain administrator authority; scoped commerce keys retain their restrictions.
2. `/platform/connections/{provider}` saves encrypted, merchant-scoped credentials
   and exposes only redacted configuration/status. Reads check the exact provider
   hostname. PayPal Sandbox writes still need explicit enablement and approvals.
3. `/platform/imports` imports Zendesk ticket comments; signed webhook deliveries
   enqueue ticket IDs for a separate worker. Exact order-reference matching may
   link a case; ambiguous/no matches remain in a merchant review queue. Imported
   private comments stay private. Source IDs deduplicate retries and feed the
   existing optional extraction flow. Suggestions never become promises silently.
4. `/platform/watchdog` scans the whole owned workspace, snapshots overdue current
   promises, identifies pending/failed/missing proof, assigns the configured case
   owner label (assigning unassigned cases to an active workspace owner) and
   prepares customer-update drafts. Daily repeat scans deduplicate.
   It does not auto-send updates or issue refunds.
5. `/platform/cases/{id}/offers` publishes versioned options referencing exact
   promise revisions. Buyer capability routes list safe terms and record one
   version-bound acceptance/decline. Stale, expired, replaced and revoked-link
   attempts fail. A published refund offer adds an acceptance gate to payment.
6. `/platform/dashboard` aggregates the whole merchant workspace. USD financial
   totals deduplicate shared captures, separate completed/pending/outstanding, and
   do not treat absent provider history as a verified zero. Case closure metrics
   report only known timestamps and include their sample count.
7. `/platform/cases/{id}/returns` guides item selection from registered orders,
   quantities, reasons, merchant approval/rejection, return tracking, warehouse
   receipt/inspection and replacement shipment. Updates use revision checks.
   Carrier delivery and internal receipt remain separate evidence. Physical
   shipment/label purchase and Shopify mutation permissions are external steps.
8. `/platform/cases/{id}/dispute-packages` creates immutable, hashed evidence
   packages with payment evidence, conversation, promises, source labels,
   attachments and missing-evidence checklists. A merchant reviews then exports.
   Provider dispute submission is a later explicitly approved integration, as in
   the requested roadmap; generating a package does not submit it to PayPal.

## Validation boundaries

Use only disposable SQLite/PostgreSQL for migration and authorization tests.
Exercise real application paths with HTTP stand-ins for provider pagination,
authentication, retries and outages. Validate stale offer acceptance, cross-tenant
denial, role revocation, financial permission boundaries, shared-capture precision,
duplicate imports/alerts/returns and immutable package history. Regenerate the
FastAPI OpenAPI contract and SDK types after implementation. Verify the native
merchant and buyer UI separately from API tests.

## Start using it

1. Start the API and frontend using their existing README commands. Open
   `http://127.0.0.1:3000/account` to create a new workspace. To keep an existing
   workspace, sign in with its full merchant key at `/login`, then open
   `/account?claim=1` to create its first owner account. Signup is controlled by
   `RESOLVE_MERCHANT_SIGNUP_ENABLED` (default true).
2. Open `/workspace/operations`. The Overview shows case outcomes, evidence
   gaps, overdue promises, complaint categories and closure times. Financial
   totals are USD recorded-ledger amounts, separate from independently verified
   PayPal evidence. Shared captures count once; promises are cumulative amounts,
   and pending amounts are separate from completed refunds.
3. In Team, create an invitation and privately share its link. It expires after
   two days and can be used once by the specified email. Invitations are not
   emailed automatically. Changing role or disabling a member revokes their
   sessions. At least one active owner must remain. A staff email currently
   belongs to one workspace.
4. In Connections, save only the provider credentials needed for this workspace,
   explicitly enable the connection, then choose Check connection. Empty secret
   fields retain existing credentials. Set a stable Fernet
   `RESOLVE_PLATFORM_ENCRYPTION_KEY` in the API and worker environments before
   saving connections. `.env.example` has the generation command; the prepared
   ignored local file already has a generated key. Keep it with private backups.
   Changing a connection requires fresh financial review. A successful PayPal
   credential check does not prove the capture belongs to the expected seller.
5. In Support imports, enter a Zendesk ticket ID. Exact ticket `external_id`
   matches a unique case/order reference; a unique registered order can open its
   case automatically. Otherwise, select and confirm the correct merchant case.
   Imported comments preserve IDs, quotes, author roles, timestamps and public/
   private labels. They remain merchant evidence and are not copied into the
   buyer conversation. The existing extraction panel can propose promises from
   these sources when AI is enabled and policy permits; review them before saving.
6. Configure a Zendesk ticket trigger with the displayed endpoint:
   `https://YOUR_FRONTEND/webhooks/zendesk/MERCHANT_UUID`. Save that webhook's
   signing secret in its owning Zendesk connection, not an API token in its place.
   Use the payload below, and retain Zendesk's signature and signature-timestamp
   headers. The invocation ID header is preferred when present. Public HTTPS
   delivery requires a hosted frontend or a separately configured tunnel.

   ```json
   {"ticket_id":"{{ticket.id}}","event_id":"{{ticket.id}}:{{ticket.updated_at}}"}
   ```

7. From `backend`, run `uv run python -m app.operations_worker --loop`. It reads
   the ordinary backend settings, decrypts owning workspace connections, handles
   bounded imports with leases/retries, and scans overdue commitments every
   minute. Alerts deduplicate by promise revision and UTC day. Use Missed promises
   → Scan workspace for an immediate pass; copy and review customer drafts.
   The worker neither sends mail nor authorizes/executes payments. Existing
   investigation, follow-up and refund-recovery workers remain separate.
8. Open a case to publish up to four remedy choices from current promise
   revisions, with an expiry within thirty days. Share the existing private
   buyer link. Buyers see safe terms and remaining conditions and can accept
   one choice or decline. Replaced/revised/expired offers and revoked links cannot
   be accepted. A refund offer requires the selected current acceptance before
   financial approval; all existing condition, amount, provider-history and
   explicit execution gates still apply.
9. Sync item-level orders through the commerce API/SDK to enable guided returns.
   Buyers or agents choose products and quantities, then a merchant approves
   or rejects. Merchant controls record tracking, warehouse receipt, inspection,
   replacement tracking and completion in order. Reserved quantities prevent
   duplicate over-returns across cases for the same registered order. Rejected
   requests release quantities. Optional exact-revision milestone confirmation
   records merchant evidence for a matching return/replacement promise. It does
   not claim a carrier independently verified the milestone.
10. In the case's dispute panel, enter the dispute reference and reason, prepare
    a package, inspect its evidence/missing-evidence checklist, and have an owner
    or manager review it before export. The JSON export contains the full case
    timeline, payment evidence, private source conversations, and attachment
    metadata/hashes; raw attachment files remain separate. Keep exported private
    evidence secure. Evidence changes require a newly prepared/reviewed package;
    historical snapshots remain readable. Nothing is submitted to PayPal.

## Permissions

| Role | Case work / offers / returns | Approve refunds | Execute approved Sandbox refunds | Review dispute packages | Team / connections / SDK keys |
|---|---|---|---|---|---|
| Owner | Yes | Yes | Yes | Yes | Yes |
| Manager | Yes | Yes | No | Yes | No |
| Finance | Yes | Yes | Yes | No | No |
| Agent | Yes | No | No | No | No |
| Viewer | Read | No | No | No | Read |

All staff are scoped to one merchant. Legacy full keys and existing key/PayPal
browser sessions retain administrator authority; do not distribute full keys to
staff. Commerce-only keys cannot access these operations. Authenticated writes
record the staff UUID or a credential pseudonym, request intent and completion;
this supplements existing domain audit events. Passwords use salted scrypt and
opaque hashed sessions; login/signup are throttled. MFA, verified email, password
reset/recovery, cross-workspace memberships and self-service OAuth installation
are follow-up work. Current onboarding accepts merchant-provided provider tokens.

## Storage, contracts and checks

SQLite migration 026 and PostgreSQL migrations 016–017 add identities, encrypted
connections, import jobs/sources, offers, alerts, returns and package snapshots.
017 makes new foreign keys deferrable for the existing SQLite import order;
016 was retained unchanged. API startup applies migrations. Back up storage and
the encryption key before operating a hosted deployment. No prior migration is
rewritten. OpenAPI is generated at `postman/contracts/resolve.openapi.json`;
TypeScript operations helpers use those types with a full key and direct API URL.

Validation for CHG-048 used synthetic data: full backend regression, disposable
PostgreSQL upgrade/import and operations tests, local signed-webhook/provider
failure tests, a real Postman TLS proxy (eight mocked requests, zero pass-through),
packaged SDK integration tests, frontend type/lint checks and production build,
and a desktop/mobile owner → buyer → invited staff browser workflow.
See [CHG-048](ENGINEERING_LOG.md) for exact commands, results and limitations.
No real Zendesk delivery, new provider account authorization, Shopify return/
replacement mutation, email delivery, carrier label purchase or PayPal dispute
submission was exercised. Existing Sandbox-only financial execution is retained.
