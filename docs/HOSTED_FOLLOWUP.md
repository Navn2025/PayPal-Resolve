# Hosted customer follow-up

The order invite, case, and customer portal remain usable without any external
integration. The contract for the optional follow-up integrations is:

| Action | Contract |
| --- | --- |
| Invite by email | The merchant may supply `customer_email` when creating an order intake invite. The same invite is queued for email; submitting it binds the case to that address. |
| Reply and refund notices | Queue one message per merchant reply and per independently verified completed PayPal refund on a shared refund promise. Messages link to My cases and omit the conversation and amounts. |
| My cases | Sign in with a verified Google mailbox or redeem a short-lived email link. List only cases assigned to that address. Open a case through a separate short-lived link; merchant revocation still applies. |
| Automatic checks | The worker processes already-verified PayPal webhook receipts and periodically refreshes enabled EasyPost and Shopify promises through the existing proof adapters. Carrier and warehouse milestones remain independent. |
| Helpdesk | A merchant can link an existing Zendesk ticket and refresh its status. Resolve reads the ticket summary; customer documents, messages, and payment data stay in Resolve. |

## Configure when the customer portal is hosted

Keep FastAPI on the same host as the Next.js server and listen on loopback.
Put the customer pages and their narrow API proxies behind HTTPS. Preserve the
public `Host` header and expose `/customer`, `/customer/account`,
`/api/customer-portal/*`, `/api/customer-account/*` and the Next.js static
assets. Keep the general FastAPI API private; to also expose the merchant
workspace, follow the [merchant sign-in guide](MERCHANT_SIGN_IN.md). Set
`RESOLVE_CUSTOMER_PUBLIC_ORIGIN` to the same exact HTTPS origin in both
`backend/.env` and `frontend/.env.local`.

Resend is the default email transport. [Buyer sign-in and email](CUSTOMER_SIGN_IN.md)
covers Google sign-in and the optional Nodemailer SMTP transport.

1. Verify the [sending domain in Resend](https://resend.com/docs/dashboard/domains/introduction).
   Disable click tracking for the private support and sign-in links. In the
   backend set `RESOLVE_CUSTOMER_EMAIL_ENABLED=true`,
   `RESOLVE_CUSTOMER_EMAIL_MERCHANT_ID` to the owning Resolve merchant UUID,
   `RESOLVE_RESEND_FROM` to a sender on that domain and
   `RESOLVE_RESEND_API_KEY` to a sending key. Set
   `RESOLVE_CUSTOMER_SIGNING_KEY` to a stable random secret (at least 32
   characters). Share it with the worker through its environment. Keep this
   key and the public origin stable while email is queued.
2. Start the bounded worker from `backend`: `uv run python -m app.followup_worker --loop`.
   It prints counts, never addresses, tokens or private message contents. The
   queue distinguishes provider acceptance from mailbox delivery. Retryable
   errors use the same [Resend idempotency key](https://resend.com/docs/dashboard/emails/idempotency-keys)
   within the provider's 24-hour window; stale jobs are not resent. The worker
   does not initiate, approve, or retry refunds. The existing refund recovery
   worker is separate.
3. In the merchant inbox choose **Invite customer**, enter the order reference
   and the buyer email already verified by the merchant for that order. Select
   **Email this invite from Resolve** to send it. Either way, entering an email
   binds the resulting case to that address. Copy-only invites do not send
   automatic notifications. **My cases** is a separate customer sign-in
   screen; it does not accept a merchant key. Sign-in links expire in 15
   minutes and can be used once. The account session lasts up to seven days;
   links opened from it last at most one hour. An expired original share
   link does not hide an account case. Merchant revocation removes it from
   My cases and invalidates links already opened from that account.

## Provider updates

1. Register a stable public HTTPS callback on the **same PayPal Sandbox REST
   app** used for the order. Route only `POST /webhooks/paypal/sandbox` to
   FastAPI and preserve the raw body and PayPal signature headers. Set
   `RESOLVE_PAYPAL_SANDBOX_WEBHOOK_ID` to the registered ID and use the existing
   supported events from [PayPal reconciliation](PAYPAL_RECONCILIATION.md).
2. Confirm a genuine Sandbox delivery appears as verified in Resolve. PayPal's
   [integration guide](https://developer.paypal.com/api/rest/webhooks/rest/)
   explains subscription and verification. Simulated signatures prove the
   local handler and worker path; they do not prove this registration or a
   real callback. To validate without money movement, a temporary subscription
   to `INVOICING.INVOICE.CREATED` can receive an unsent Sandbox draft invoice.
   A verified irrelevant event is stored as `ignored`. A supported refund
   event is required to validate account-backed reconciliation.
   To inspect recent receipts without dumping event bodies or signature
   headers, run this from `backend`:

   ```powershell
   @'
   from app.settings import Settings
   from app.storage import configured_store
   config = Settings()
   with configured_store(config).transaction() as db:
       for row in db.execute(
           """SELECT event_type,status,received_at FROM paypal_webhook_events
              WHERE merchant_id=? ORDER BY received_at DESC LIMIT 5""",
           (str(config.paypal_resolve_merchant_id),),
       ):
           print(*row)
   '@ | uv run python -
   ```
3. Set `RESOLVE_AUTO_PROVIDER_REFRESH_ENABLED=true` with the merchant-scoped
   EasyPost and/or Shopify credentials in `backend/.env`. Unresolved provider
   promises are checked about every five minutes and fulfilled ones about
   hourly. The worker checks replacements, carrier-delivered returns, Shopify
   cancellations and tracked exchange fulfillment. Unchanged observations do
   not create new timeline entries. Warehouse receipt and inspection still
   require an explicit merchant finding. These are scheduled API reads, so
   EasyPost and Shopify do not need incoming webhook registration.

## Link an existing helpdesk ticket

Set `RESOLVE_HELPDESK_MERCHANT_ID`, `RESOLVE_ZENDESK_SUBDOMAIN`, and
`RESOLVE_ZENDESK_OAUTH_TOKEN` with access to
[read Zendesk tickets](https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/#show-ticket).
Replace the OAuth access token when it expires; Resolve does not refresh it.
Open the resolution case and use the **Zendesk ticket** card to link a ticket
ID, refresh the status, or open the ticket in Zendesk. Resolve stores the
ticket ID, status, and last check. It does not create Zendesk tickets, copy
comments, or send evidence to Zendesk. Zendesk credentials are never exposed
to the buyer or browser.

The worker and backend use the same database settings. For shared hosted
storage, see [PostgreSQL migration](POSTGRES_MIGRATION.md). A local SQLite
file is for a single host. API contracts are in the
[generated OpenAPI spec](../postman/contracts/resolve.openapi.json).
