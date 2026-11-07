# Customer intake and case triage

1. Start the backend and frontend as shown in the [local UI guide](../frontend/README.md).
   Connect a merchant account and choose **Invite customer**. Enter the order
   reference, copy the private link, and share it with the buyer.
2. Open the link as a buyer in a separate browser session. Choose an issue
   (missing item, duplicate charge, damaged delivery, refund delay, or other)
   and submit a description. The same link now opens the new case.
3. Attach a photo, receipt, or return slip under **Customer evidence**. The
   buyer and merchant both see the file labeled **Customer submitted**.
4. Reload the merchant workspace. Search by order, title, case ID, or assignee,
   or filter by **Waiting on customer**, **Needs approval**, **Pending with
   PayPal**, or **Unread**. Open **Manage case** to assign a person or team and
   set the next deadline. Open **Customer portal** in the case to view the
   conversation, download evidence, reply, and mark displayed messages read.
5. If the case needs a refund, use **Link payment record** on the existing case,
   select the correct merchant-owned payment case, and record the agreed refund
   promise. This keeps the original issue, conversation, evidence, and buyer URL.
   The payment record must already exist; use the existing payment API to create
   one if needed. Linking alone does not request a refund.

Try the standalone sample intake at
[localhost:3000/customer?intake=1](http://127.0.0.1:3000/customer?intake=1).
It creates no backend records. An ordinary link issued by the local workspace
is reachable on this machine. For emailed invites, notifications and remote
access, see [hosted follow-up setup](HOSTED_FOLLOWUP.md).

The merchant creates an invite for one order. The invite itself authorizes
access; entering an order number never reveals a case. The first valid
submission creates one case and turns the same invite into a case link for
seven days from submission. A retry returns the original case. Replace or
revoke the case link in **Customer portal**; replaying the original invite
cannot restore access. Share private links only with the intended buyer.

| Route | Purpose |
| --- | --- |
| `POST /resolution-cases/intake-invites` | Merchant issues a seven-day, order-specific invite. |
| `POST /customer-portal/intake-view`, `POST /customer-portal/intake` | Read only the invited order reference; submit one issue for that invite. |
| `POST /customer-portal/evidence`, `POST /customer-portal/evidence/{id}` | Upload and download case-scoped customer evidence. |
| `GET /resolution-cases/{id}/customer-evidence`, `GET /resolution-cases/{id}/customer-evidence/{file_id}` | List and download customer-submitted evidence as the owning merchant. |
| `GET /resolution-cases/{id}/operations`, `PUT /resolution-cases/{id}/operations` | Read derived inbox state; update assignee label, due date and waiting-on-customer flag. |
| `POST /resolution-cases/{id}/operations/read` | Mark customer messages read through a displayed watermark. |
| `GET /resolution-cases/inbox` | Search and filter the merchant's cases before pagination. |
| `PUT /resolution-cases/{id}/payment-link` | Attach one existing payment case owned by the merchant. |

Uploads accept PDF, PNG, and JPEG up to 2 MiB each, with a maximum of 10 files
per case. File names, media types, and file signatures are checked. An identical
file with the same name can be retried without another attachment. Downloads
require an active case link or the owning merchant and are served as attachments.
Customer files remain separate from the evidence that verifies a remedy or
changes refund eligibility.

The timeline shows the report and the milestones that have evidence, such as
**Return confirmed**, **Refund approved**, and **PayPal confirmed a refund**.
The source label distinguishes a customer submission, a merchant finding, and
provider confirmation. The next actor comes from the same workflow rules as the
inbox. A case due date overrides the earliest outstanding promise deadline.
Overdue means the chosen deadline passed while work remains. A new buyer reply
clears the waiting-on-customer flag and becomes unread. Reading through one
message does not clear newer replies. Assignment and read state are shared
merchant fields; assignment labels do not grant account permissions.
