# Customer portal

To start a new case from an order-specific link, see
[customer intake and case triage](CUSTOMER_WORKFLOW.md).

Resolve has two views of the same resolution. A merchant works in the inbox.
A customer opens a case link to see the customer-facing promise, progress,
and conversation. The customer does not need a merchant account.

| Route | Access | Purpose |
| --- | --- | --- |
| `GET /resolution-cases/{id}/customer-link` | Owning merchant | See whether a link is active and when it expires. |
| `POST /resolution-cases/{id}/customer-link` | Owning merchant | Create or replace the link and choose a public heading and whether to display the order reference. Returns the new token once. |
| `DELETE /resolution-cases/{id}/customer-link` | Owning merchant | Revoke access immediately. |
| `GET /resolution-cases/{id}/customer-messages` | Owning merchant | Read the case conversation. |
| `POST /resolution-cases/{id}/customer-messages` | Owning merchant | Reply in the portal; cases with an email contact queue a separate notice. |
| `POST /customer-portal/view` | Customer link token | Read the limited public case projection and conversation. |
| `POST /customer-portal/messages` | Customer link token | Send a message with a request ID for safe retries. |

The link expires after seven days. Replacing or revoking it invalidates the
old token. A link grants access to the current customer-facing promises and
case conversation, so send it only to the intended customer. The private
merchant title, source notes, attachments, evidence export, payment IDs,
approval records, and internal review reasons are not returned.

To try the customer screen without an account, open
[the sample portal](http://127.0.0.1:3000/customer?demo=1). For an actual local
case, connect to FastAPI in the merchant UI and open its **Customer portal**
tab. Choose the public heading, optionally show the order reference, and
select **Create customer link**. Copy the link or open the customer view in a
separate browser session. The merchant and customer can reply in the case;
refresh messages to see updates.

The browser keeps the token in the [URL fragment](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Fragment) so it is not part of the
initial page request. API requests carry it in their JSON body and return
private, non-cacheable responses. The database stores its hash. The full
link is shown only when created; replacing it is how to obtain a new copy.
Messages are plain text, capped at 2,000 characters and 100 per case.
Customer messages are limited to six per minute; reusing the same request
ID and text is an idempotent retry. A conversation never changes approval
or payment state. Hosted email notices are optional and never include the
conversation text. See [hosted follow-up](HOSTED_FOLLOWUP.md).

The app runs on loopback during development, so these links work on the
machine running Resolve. Use a hosted HTTPS environment before sharing links
with customers on other devices. Each link is limited to its assigned case.
Buyers can also return through [My cases](CUSTOMER_SIGN_IN.md) if their order
invite was associated with a verified address.
