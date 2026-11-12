"""Read-only evidence adapters. No provider data is mutated here."""

import re
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import ValidationError

from app.core.exceptions import StoreError
from app.schemas.resolution import ProviderProof


SHOPIFY_VERSION = "2026-10"
EASYPOST_BASE_URL = "https://api.easypost.com"
SHIP_MOVED = {"in_transit", "out_for_delivery", "available_for_pickup", "delivered"}
SHIP_EXCEPTIONS = {"failure", "error", "return_to_sender", "cancelled"}
SHOPIFY_SHIPMENT_MOVED = {
    "CARRIER_PICKED_UP",
    "IN_TRANSIT",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
}
SHOPIFY_SHIPMENT_EXCEPTIONS = {"CANCELED", "FAILURE", "LABEL_VOIDED", "NOT_DELIVERED"}


class ResolutionProviders:
    def __init__(self, paypal):
        self.paypal = paypal
        self.settings = paypal.settings

    @staticmethod
    def _object(value):
        if not isinstance(value, dict):
            raise StoreError(
                502, "Provider response did not contain the expected record"
            )
        return value

    def _request(self, method, url, **kwargs):
        try:
            response = self.paypal.http.request(
                method, url, follow_redirects=False, **kwargs
            )
        except httpx.TimeoutException:
            raise StoreError(504, "Evidence provider timed out") from None
        except httpx.HTTPError:
            raise StoreError(502, "Evidence provider connection failed") from None
        if response.status_code == 404:
            raise StoreError(404, "Evidence record was not found")
        if response.status_code == 429 or response.status_code >= 500:
            raise StoreError(503, "Evidence provider is temporarily unavailable")
        if response.status_code != 200:
            raise StoreError(502, "Evidence provider rejected the lookup")
        try:
            return self._object(response.json())
        except ValueError:
            raise StoreError(502, "Invalid evidence provider response") from None

    def _connector_owner(self, merchant_id):
        owner = self.settings.resolution_connector_merchant_id
        if owner is None:
            raise StoreError(503, "External resolution connectors are not configured")
        if owner != merchant_id:
            raise StoreError(
                403,
                "External resolution connectors are not configured for this merchant",
            )

    def _paypal_read(self, merchant_id, path, resource_id, *, id_field="id"):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", resource_id):
            raise StoreError(422, "Invalid PayPal evidence resource ID")
        settings = self.paypal.configuration()
        if settings.paypal_resolve_merchant_id != merchant_id:
            raise StoreError(403, "PayPal Sandbox is not configured for this merchant")
        token = self.paypal._access_token(settings)
        result = self._object(
            self.paypal._json_request(
                "GET",
                path + resource_id,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json",
                },
                not_found_detail="PayPal Sandbox evidence record was not found",
            )
        )
        if result.get(id_field) != resource_id:
            raise StoreError(502, "PayPal returned a different evidence record")
        return result

    def _shopify_read(self, merchant_id, identifier, query):
        self._connector_owner(merchant_id)
        host, token = (
            self.settings.shopify_shop_domain,
            self.settings.shopify_admin_token,
        )
        if (
            not host
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com", host)
            or not token
            or not token.get_secret_value().strip()
        ):
            raise StoreError(503, "Shopify evidence connector is not configured")
        body = self._request(
            "POST",
            f"https://{host}/admin/api/{SHOPIFY_VERSION}/graphql.json",
            headers={
                "X-Shopify-Access-Token": token.get_secret_value(),
                "Accept": "application/json",
            },
            json={"query": query, "variables": {"id": identifier}},
        )
        if body.get("errors"):
            raise StoreError(
                502, "Shopify could not authorize or complete the evidence query"
            )
        data = self._object(body.get("data"))
        if data.get("node") is None:
            raise StoreError(404, "Shopify evidence record was not found")
        node = self._object(data["node"])
        if node.get("id") != identifier:
            raise StoreError(502, "Shopify returned a different evidence record")
        return node

    @staticmethod
    def _status(data, key="status"):
        value = data.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,70}", value):
            raise StoreError(502, "Provider did not return a valid evidence status")
        return value

    @staticmethod
    def _money(data, *, amount_key, currency_key):
        try:
            value, currency = data[amount_key], data[currency_key]
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{1,15}(\.\d{1,3})?", value
            ):
                raise ValueError
            if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                raise ValueError
            return Decimal(value), currency
        except (InvalidOperation, ValueError, TypeError, KeyError):
            raise StoreError(
                502, "Provider did not return a valid evidence amount"
            ) from None

    def tracking(self, merchant_id, reference, milestone):
        self._connector_owner(merchant_id)
        key = self.settings.easypost_api_key
        if not key or not key.get_secret_value().strip():
            raise StoreError(503, "EasyPost evidence connector is not configured")
        tracker = self._request(
            "GET",
            EASYPOST_BASE_URL + "/v2/trackers/" + reference.tracker_id,
            auth=httpx.BasicAuth(key.get_secret_value(), ""),
        )
        if (
            tracker.get("id") != reference.tracker_id
            or tracker.get("tracking_code") != reference.tracking_code
            or not isinstance(tracker.get("carrier"), str)
            or tracker["carrier"].casefold() != reference.carrier.casefold()
        ):
            raise StoreError(
                409, "Carrier or tracking number does not match the promised shipment"
            )
        status = self._status(tracker)
        confirmed = status == "delivered" or (
            milestone == "shipped" and status in SHIP_MOVED
        )
        outcome = (
            "fulfilled"
            if confirmed
            else "needs_review"
            if status in SHIP_EXCEPTIONS
            else "pending"
        )
        mode = tracker.get("mode")
        return ProviderProof(
            provider="easypost",
            resource_id=reference.tracker_id,
            status=status,
            outcome=outcome,
            environment=mode if mode in ("test", "production") else None,
            detail="Carrier reported the required milestone"
            if confirmed
            else "Carrier has not confirmed the required milestone",
        )

    def cancellation(self, merchant_id, target):
        proofs = []
        if target.shopify_order_id:
            order = self._shopify_read(
                merchant_id,
                target.shopify_order_id,
                "query ResolutionOrder($id:ID!){node(id:$id){... on Order{id cancelledAt}}}",
            )
            if "cancelledAt" not in order:
                raise StoreError(
                    502, "Shopify did not return the order cancellation field"
                )
            cancelled = order["cancelledAt"] is not None
            if cancelled and not isinstance(order["cancelledAt"], str):
                raise StoreError(
                    502, "Shopify did not return a valid cancellation date"
                )
            proofs.append(
                ProviderProof(
                    provider="shopify",
                    resource_id=target.shopify_order_id,
                    status="CANCELLED" if cancelled else "OPEN",
                    outcome="fulfilled" if cancelled else "pending",
                    detail="Shopify order cancellation",
                )
            )
        if target.paypal_authorization_id:
            auth = self._paypal_read(
                merchant_id,
                "/v2/payments/authorizations/",
                target.paypal_authorization_id,
            )
            status = self._status(auth)
            outcome = (
                "fulfilled"
                if status == "VOIDED"
                else ("pending" if status in ("CREATED", "PENDING") else "needs_review")
            )
            proofs.append(
                ProviderProof(
                    provider="paypal",
                    resource_id=target.paypal_authorization_id,
                    status=status,
                    outcome=outcome,
                    environment="sandbox",
                    detail="PayPal authorization status",
                )
            )
        return proofs

    def subscription(self, merchant_id, target):
        row = self._paypal_read(
            merchant_id, "/v1/billing/subscriptions/", target.paypal_subscription_id
        )
        status = self._status(row)
        desired = "CANCELLED" if target.action == "cancel" else "SUSPENDED"
        return ProviderProof(
            provider="paypal",
            resource_id=target.paypal_subscription_id,
            status=status,
            outcome="fulfilled"
            if status == desired
            else ("needs_review" if status in ("CANCELLED", "EXPIRED") else "pending"),
            environment="sandbox",
            detail="PayPal subscription status; does not verify a refund",
        )

    def credit_or_exchange(self, merchant_id, target):
        if target.action == "store_credit":
            record = self._shopify_read(
                merchant_id,
                target.credit_transaction_id,
                "query ResolutionCredit($id:ID!){node(id:$id){... on StoreCreditAccountCreditTransaction"
                "{id account{id} amount{amount currencyCode}}}}",
            )
            money = self._money(
                record.get("amount"), amount_key="amount", currency_key="currencyCode"
            )
            if self._object(record.get("account")).get(
                "id"
            ) != target.credit_account_id or money != (target.amount, target.currency):
                raise StoreError(
                    409,
                    "Store credit does not match the agreed account, amount and currency",
                )
            return ProviderProof(
                provider="shopify",
                resource_id=target.credit_transaction_id,
                status="CREDITED",
                outcome="fulfilled",
                amount=money[0],
                currency=money[1],
                detail="Store account credit transaction; not a cash refund",
            )
        record = self._shopify_read(
            merchant_id,
            target.fulfillment_id,
            "query ResolutionExchange($id:ID!){node(id:$id){... on Fulfillment{id order{id} status displayStatus "
            "fulfillmentLineItems(first:100){nodes{lineItem{id}} pageInfo{hasNextPage}}}}}",
        )
        items = self._object(record.get("fulfillmentLineItems"))
        if self._object(record.get("order")).get("id") != target.shopify_order_id or (
            not isinstance(items.get("nodes"), list)
            or not any(
                isinstance(node, dict)
                and isinstance(node.get("lineItem"), dict)
                and node["lineItem"].get("id") == target.exchange_line_item_id
                for node in items["nodes"]
            )
        ):
            raise StoreError(
                409,
                "Fulfillment does not verify the expected order and exchange line item",
            )
        fulfillment = self._status(record)
        status = (
            self._status(record, "displayStatus")
            if record.get("displayStatus")
            else fulfillment
        )
        outcome = (
            "needs_review"
            if fulfillment in ("CANCELED", "CANCELLED", "FAILURE", "ERROR")
            or status in SHOPIFY_SHIPMENT_EXCEPTIONS
            else "fulfilled"
            if fulfillment == "SUCCESS" and status in SHOPIFY_SHIPMENT_MOVED
            else "pending"
        )
        return ProviderProof(
            provider="shopify",
            resource_id=target.fulfillment_id,
            status=status,
            outcome=outcome,
            detail="Shopify fulfillment of the selected exchange item",
        )

    def billing(self, merchant_id, target, legacy):
        if target.action == "cancel_invoice":
            row = self._paypal_read(
                merchant_id, "/v2/invoicing/invoices/", target.paypal_invoice_id
            )
            status = self._status(row)
            return [
                ProviderProof(
                    provider="paypal",
                    resource_id=target.paypal_invoice_id,
                    status=status,
                    outcome="fulfilled"
                    if status == "CANCELLED"
                    else (
                        "pending"
                        if status in ("DRAFT", "SENT", "SCHEDULED", "UNPAID")
                        else "needs_review"
                    ),
                    environment="sandbox",
                    detail="PayPal invoice status; does not confirm a money movement",
                )
            ]
        proofs = []
        for identifier in dict.fromkeys(
            filter(None, (legacy.payment.capture_id, target.original_capture_id))
        ):
            capture = self._paypal_read(
                merchant_id, "/v2/payments/captures/", identifier
            )
            if (
                self._object(capture.get("payee")).get("merchant_id")
                != self.settings.paypal_sandbox_merchant_id
            ):
                raise StoreError(
                    409, "Billing evidence does not match the configured PayPal seller"
                )
            amount, currency = self._money(
                capture.get("amount"), amount_key="value", currency_key="currency_code"
            )
            status = self._status(capture)
            if (
                status not in ("COMPLETED", "REFUNDED", "PARTIALLY_REFUNDED")
                or currency != legacy.payment.currency
            ):
                raise StoreError(
                    409, "Billing evidence does not verify a captured payment"
                )
            if (
                identifier == legacy.payment.capture_id
                and amount != legacy.payment.captured_amount
            ):
                raise StoreError(
                    409, "Billing evidence amount does not match the refund case"
                )
            proofs.append(
                ProviderProof(
                    provider="paypal",
                    resource_id=identifier,
                    status=status,
                    outcome="fulfilled",
                    amount=amount,
                    currency=currency,
                    environment="sandbox",
                    detail="PayPal captured payment checked; does not establish a duplicate charge",
                )
            )
        if target.action == "duplicate_charge" and len(proofs) != 2:
            raise StoreError(
                409,
                "Duplicate-charge correction requires two distinct verified captures",
            )
        return proofs

    def dispute(self, merchant_id, target, legacy):
        row = self._paypal_read(
            merchant_id,
            "/v1/customer/disputes/",
            target.paypal_dispute_id,
            id_field="dispute_id",
        )
        transactions = row.get("disputed_transactions")
        if not isinstance(transactions, list) or not any(
            isinstance(tx, dict)
            and tx.get("seller_transaction_id") == legacy.payment.capture_id
            and (
                not isinstance(tx.get("seller"), dict)
                or tx["seller"].get("merchant_id")
                in (None, self.settings.paypal_sandbox_merchant_id)
            )
            for tx in transactions
        ):
            raise StoreError(409, "PayPal dispute is not linked to this case's capture")
        status = self._status(row)
        return ProviderProof(
            provider="paypal",
            resource_id=target.paypal_dispute_id,
            status=status,
            outcome="fulfilled"
            if status == "RESOLVED"
            else "needs_review"
            if status == "WAITING_FOR_SELLER_RESPONSE"
            else "pending",
            response_due_at=row.get("seller_response_due_date"),
            environment="sandbox",
            detail="Formal PayPal dispute status; does not fulfill other promises",
        )

    def read(self, merchant_id, target, legacy):
        try:
            match target.kind:
                case "return":
                    return [self.tracking(merchant_id, target.tracking, "delivered")]
                case "replacement":
                    return [
                        self.tracking(merchant_id, target.tracking, target.milestone)
                    ]
                case "order_cancellation":
                    return self.cancellation(merchant_id, target)
                case "subscription":
                    return [self.subscription(merchant_id, target)]
                case "store_credit_or_exchange":
                    return [self.credit_or_exchange(merchant_id, target)]
                case "billing_correction":
                    return self.billing(merchant_id, target, legacy)
                case "dispute_handoff":
                    return [self.dispute(merchant_id, target, legacy)]
        except ValidationError:
            raise StoreError(
                502, "Evidence provider returned an invalid proof field"
            ) from None
        raise StoreError(
            422, "Use the existing PayPal history reader for refund promises"
        )
