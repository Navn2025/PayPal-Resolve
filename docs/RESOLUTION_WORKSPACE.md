# Resolution workspace

The merchant API tracks several promises and their evidence in one case, even
when there is no captured payment. It can link one existing refund case;
that case continues to own the refund ledger, approvals and execution.

| Route | Contract |
| --- | --- |
| `POST /resolution-cases` | Create an owned workspace, optionally linked to a refund case. |
| `GET /resolution-cases`, `GET /resolution-cases/{id}` | List cases and inspect current promise and evidence state. |
| `POST /resolution-cases/{id}/promises` | Record a promise with source, due date, typed remedy and optional prerequisite promises. |
| `PUT /resolution-cases/{id}/promises/{promise_id}` | Replace a promise with an explicit expected revision; retain the old promise and its evidence in the timeline. |
| `POST /resolution-cases/{id}/promises/{promise_id}/evidence` | Record merchant evidence for an exact revision. Only an explicit internal warehouse receipt or inspection attestation can satisfy a manual return milestone. |
| `POST /resolution-cases/{id}/promises/{promise_id}/refresh` | Read provider evidence for the current revision. May update local evidence and consent; never issues a refund or changes provider data. |
| `GET /resolution-cases/{id}/timeline` | Paginated, ordered history of promises, merchant evidence and provider observations. |
| `GET /resolution-cases/{id}/evidence-bundle` | Private export for a merchant's review or dispute handoff. No evidence is submitted to PayPal. |

Each request uses the existing merchant bearer token. Prerequisites reference
earlier promises in the same workspace. The workspace tracks one cumulative
refund promise for a linked refund case. The amount must agree with the accepted
commitment on that case; its existing approval and execution routes remain the
only way to submit money movement. A prerequisite with incomplete evidence
blocks that refund. A changed revision cannot inherit the old revision's proof.

The outcome and its source are separate: a merchant's inspection attestation
can satisfy an internal condition, but cannot serve as PayPal or carrier proof.
An order cancellation and a payment release are two independent facts. A
formal dispute status does not close other promises. External IDs are linked by
the merchant and independently checked in the configured provider account;
Resolve does not infer cross-system identity from similar amounts or names.

## Try a conditional refund

Run `uv run uvicorn app.main:app --reload` from `backend` and open
[Swagger](http://127.0.0.1:8000/docs). Authorize with the private Resolve token.

1. Create the ordinary refund case with its payment IDs and accepted commitment.
   Create a resolution case with that ID as `refund_case_id`. For shipment-only
   and subscription cases, omit it; use `order_reference` for shipment cases.
2. Create a return promise in the resolution case:

   ```json
   {
     "promise": "Confirm warehouse receipt before sending the refund",
     "source_note": "Recorded from the agreed support resolution",
     "target": {
       "kind": "return",
       "milestone": "warehouse_received",
       "return_reference": "RMA-DEMO-1"
     }
   }
   ```

3. Create a second promise with target `{"kind":"refund","amount":"30.00"}`
   and the return promise ID in `requires`. This assumes a $30 accepted
   commitment on the linked refund case. The refund case's reconciliation
   reports `awaiting_prerequisite` until the condition is satisfied.
4. POST evidence with `{"expected_revision":1,"finding":"confirmed","note":"Warehouse logged receipt"}`.
   This confirms only the internal return milestone, under the merchant's
   identity. Refresh the refund promise with `{"expected_revision":1}` to
   discover PayPal refund history. Then use the existing approval and execution
   routes if another refund is actually owed.
5. View the case and timeline. The timeline response contains separate
   `items` and `refund_items` arrays with their own totals, paginated with the
   same requested offset and limit. The evidence bundle includes attachment
   metadata for the linked refund case; use its existing attachment routes for
   file bytes. Only the case owner can access it.

## Remedy details and configuration

| `target.kind` | Evidence Resolve checks |
| --- | --- |
| `refund` | Existing PayPal Sandbox order, capture and refund records; amounts in the workspace are based on provider observations, not manual ledger rows. History freshness and verified remaining capture balance are separate from how much of the promise is still owed. |
| `return` | An EasyPost tracker for `carrier_delivered`; a revision-specific merchant finding for `warehouse_received` or `inspection_passed`. Carrier evidence on an internal milestone is supplementary. |
| `replacement` | A replacement reference and its linked EasyPost tracker; the expected carrier and tracking code must match. A shipping label is pending, not shipped. |
| `order_cancellation` | Shopify's `cancelledAt` and/or PayPal authorization status `VOIDED`. If both references are given, both must confirm. A captured payment needs a separate refund promise; it is not shown as an authorization release. |
| `subscription` | PayPal status `CANCELLED` or `SUSPENDED` for the requested action. |
| `store_credit_or_exchange` | Exact Shopify credit transaction, account, amount, and currency; or the specified exchange line item in a matching Shopify fulfillment with shipment movement. Credit is historical issuance, not a current spendable-balance check. |
| `billing_correction` | PayPal invoice cancellation; or capture evidence plus a required, separately verified refund promise for a reported duplicate or incorrect charge. Two capture records alone cannot prove the charges were duplicates. |
| `dispute_handoff` | Formal PayPal dispute status and seller response deadline when supplied, with a matching seller-side transaction. The private JSON evidence bundle can be reviewed and shared by the merchant. Resolve does not send it or act on the formal dispute. |

PayPal evidence uses the existing Sandbox configuration and seller binding.
Shopify and EasyPost are optional. Set `RESOLVE_RESOLUTION_CONNECTOR_MERCHANT_ID`
to the Resolve merchant UUID that owns the connected accounts. For Shopify,
set `RESOLVE_SHOPIFY_SHOP_DOMAIN` to its `*.myshopify.com` hostname and
`RESOLVE_SHOPIFY_ADMIN_TOKEN` to the shop's server-side Admin token with
permission to read the relevant orders and store-credit transactions. The
connector queries Admin GraphQL `2026-10`. For EasyPost, set
`RESOLVE_EASYPOST_API_KEY` and use a tracker ID already present in that
account. The response labels EasyPost test observations when the API reports
test mode. Keep these values in the ignored local `.env`.

Connectors perform on-demand evidence refreshes. Provider proof is an observation
as of its recorded time. Non-refund connectors do not subscribe to webhooks or
perform cancellations, exchanges, shipping purchases, or credits. The existing
refund worker and webhook processing continue to update the linked refund case.
No connector was tested against a live merchant account in this change.

Provider references: [PayPal authorizations](https://developer.paypal.com/api/payments/v2/authorizations-get/),
[subscriptions](https://developer.paypal.com/api/subscriptions/v1/subscriptions-get/),
[invoices](https://developer.paypal.com/api/invoicing/v2/),
[disputes](https://developer.paypal.com/api/customer-disputes/v1/disputes-get/),
[Shopify order](https://shopify.dev/docs/api/admin-graphql/latest/objects/Order),
[credit transaction](https://shopify.dev/docs/api/admin-graphql/latest/objects/StoreCreditAccountCreditTransaction),
[fulfillment](https://shopify.dev/docs/api/admin-graphql/latest/objects/Fulfillment),
and [EasyPost tracker](https://docs.easypost.com/docs/trackers).
