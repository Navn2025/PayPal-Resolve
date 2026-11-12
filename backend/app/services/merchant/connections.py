"""Encrypted workspace credentials and explicit provider checks."""

from app.dependencies.providers import (
    paypal_for as paypal_for,
    settings_for as _request_settings_for,
)

from app.schemas.platform_connections import (
    ConnectionInput as ConnectionInput,
)


import json
import re
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
import httpx
from pydantic import SecretStr

from app.core.exceptions import StoreError
from app.services.merchant.identity import audit, now


FIELDS = {
    "paypal": (
        {"merchant_id", "refunds_enabled", "partial_refunds_enabled"},
        {"client_id", "client_secret"},
    ),
    "zendesk": ({"subdomain"}, {"oauth_token", "webhook_secret"}),
    "shopify": ({"shop_domain"}, {"admin_token"}),
    "easypost": (set(), {"api_key"}),
}


class Connections:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings

    def cipher(self):
        try:
            return Fernet(
                self.settings.platform_encryption_key.get_secret_value().encode()
            )
        except (AttributeError, ValueError):
            raise StoreError(
                503,
                "Set RESOLVE_PLATFORM_ENCRYPTION_KEY to a stable Fernet key before connecting accounts",
            ) from None

    def decrypt(self, row):
        try:
            return json.loads(
                self.cipher().decrypt(row["credentials_ciphertext"].encode())
            )
        except (InvalidToken, ValueError):
            raise StoreError(
                503,
                "Connection credentials cannot be decrypted with the configured key",
            ) from None

    @staticmethod
    def view(row):
        return {
            "provider": row["provider"],
            "config": json.loads(row["config_json"]),
            "enabled": bool(row["enabled"]),
            "revision": row["revision"],
            "check_status": row["check_status"],
            "checked_at": row["checked_at"],
            "updated_at": row["updated_at"],
            "credentials_stored": True,
        }

    def list(self, merchant):
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM platform_connections WHERE merchant_id=? ORDER BY provider",
                (str(merchant),),
            ).fetchall()
        return {
            "items": [self.view(r) for r in rows],
            "encryption_configured": bool(self.settings.platform_encryption_key),
        }

    def get(self, merchant, provider):
        with self.store.transaction() as db:
            return db.execute(
                "SELECT * FROM platform_connections WHERE merchant_id=? AND provider=?",
                (str(merchant), provider),
            ).fetchone()

    def save(self, merchant, actor, provider, payload):
        if provider not in FIELDS:
            raise StoreError(404, "Provider not supported")
        public, private = FIELDS[provider]
        if set(payload.config) - public or set(payload.credentials) - private:
            raise StoreError(422, "Unknown connection fields")
        config = payload.config
        if provider == "zendesk" and not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,62}", str(config.get("subdomain", ""))
        ):
            raise StoreError(422, "Enter the Zendesk subdomain, without a URL")
        if provider == "shopify" and not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{0,62}\.myshopify\.com",
            str(config.get("shop_domain", "")),
        ):
            raise StoreError(422, "Enter the exact myshopify.com shop hostname")
        if provider == "paypal":
            if not re.fullmatch(
                r"[A-Za-z0-9]{1,64}", str(config.get("merchant_id", ""))
            ):
                raise StoreError(422, "Enter the PayPal Sandbox seller merchant ID")
            for key in ("refunds_enabled", "partial_refunds_enabled"):
                if key in config and type(config[key]) is not bool:
                    raise StoreError(422, "PayPal switches must be booleans")
        with self.store.transaction(write=True) as db:
            row = db.execute(
                "SELECT * FROM platform_connections WHERE merchant_id=? AND provider=?",
                (str(merchant), provider),
            ).fetchone()
            if payload.expected_revision != (row["revision"] if row else 0):
                raise StoreError(409, "Connection changed; reload before saving")
            if (
                row
                and provider == "zendesk"
                and json.loads(row["config_json"]).get("subdomain")
                != config.get("subdomain")
            ):
                if (
                    db.execute(
                        "SELECT 1 FROM platform_imports WHERE merchant_id=? LIMIT 1",
                        (str(merchant),),
                    ).fetchone()
                    or db.execute(
                        "SELECT 1 FROM platform_webhook_jobs WHERE merchant_id=? LIMIT 1",
                        (str(merchant),),
                    ).fetchone()
                ):
                    raise StoreError(
                        409,
                        "Imported ticket identity belongs to the saved Zendesk account; use a separate workspace for another account",
                    )
            secrets = self.decrypt(row) if row else {}
            secrets.update(
                {
                    k: v.get_secret_value()
                    for k, v in payload.credentials.items()
                    if v.get_secret_value()
                }
            )
            required = private - {"webhook_secret"}
            if payload.enabled and any(not secrets.get(k) for k in required):
                raise StoreError(
                    422, "Fill the provider's required credentials before enabling"
                )
            encrypted = self.cipher().encrypt(json.dumps(secrets).encode()).decode()
            db.execute(
                "INSERT INTO platform_connections VALUES (?,?,?,?,?,?,NULL,'not_checked',?) ON CONFLICT(merchant_id,provider) DO UPDATE SET config_json=excluded.config_json,credentials_ciphertext=excluded.credentials_ciphertext,enabled=excluded.enabled,revision=excluded.revision,checked_at=NULL,check_status='not_checked',updated_at=excluded.updated_at",
                (
                    str(merchant),
                    provider,
                    json.dumps(config),
                    encrypted,
                    int(payload.enabled),
                    payload.expected_revision + 1,
                    now(),
                ),
            )
            audit(
                db,
                merchant,
                actor,
                "connection_saved",
                provider,
                enabled=payload.enabled,
            )
            from app.services.payments.approvals import invalidate_approvals

            for capture in db.execute(
                "SELECT DISTINCT capture_id FROM cases WHERE merchant_id=?",
                (str(merchant),),
            ).fetchall():
                invalidate_approvals(
                    db,
                    merchant,
                    capture[0],
                    "Provider connection configuration changed; review fresh evidence",
                )
        return self.view(self.get(merchant, provider))

    def settings_for(self, merchant):
        changes = {}
        if str(self.settings.resolution_connector_merchant_id) != str(merchant):
            # Shopify and EasyPost share a legacy owner setting. Never inherit
            # another workspace credential while rebinding just one connector.
            changes.update(
                shopify_shop_domain=None,
                shopify_admin_token=None,
                easypost_api_key=None,
            )
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM platform_connections WHERE merchant_id=?",
                (str(merchant),),
            ).fetchall()
        for row in rows:
            cfg, secrets = json.loads(row["config_json"]), self.decrypt(row)
            enabled, provider = bool(row["enabled"]), row["provider"]
            if provider == "paypal":
                changes.update(
                    paypal_resolve_merchant_id=UUID(str(merchant)),
                    paypal_sandbox_enabled=enabled,
                    paypal_sandbox_client_id=SecretStr(secrets.get("client_id", "")),
                    paypal_sandbox_client_secret=SecretStr(
                        secrets.get("client_secret", "")
                    ),
                    paypal_sandbox_merchant_id=cfg.get("merchant_id"),
                    paypal_sandbox_refunds_enabled=enabled
                    and cfg.get("refunds_enabled", False),
                    paypal_sandbox_partial_refunds_enabled=enabled
                    and cfg.get("partial_refunds_enabled", False),
                )
            elif provider == "zendesk":
                changes.update(
                    helpdesk_merchant_id=UUID(str(merchant)) if enabled else None,
                    zendesk_subdomain=cfg.get("subdomain"),
                    zendesk_oauth_token=SecretStr(secrets.get("oauth_token", "")),
                )
            elif provider == "shopify":
                changes.update(
                    resolution_connector_merchant_id=UUID(str(merchant)),
                    shopify_shop_domain=cfg.get("shop_domain") if enabled else None,
                    shopify_admin_token=SecretStr(secrets.get("admin_token", ""))
                    if enabled
                    else None,
                )
            elif provider == "easypost":
                changes.update(
                    resolution_connector_merchant_id=UUID(str(merchant)),
                    easypost_api_key=SecretStr(secrets.get("api_key", ""))
                    if enabled
                    else None,
                )
        return self.settings.model_copy(update=changes)

    def check(self, merchant, actor, provider, http):
        row = self.get(merchant, provider)
        if not row or not row["enabled"]:
            raise StoreError(409, "Enable and save this connection first")
        cfg, secret = json.loads(row["config_json"]), self.decrypt(row)
        try:
            if provider == "paypal":
                from app.integrations.paypal.client import PayPalSandboxClient

                client = PayPalSandboxClient(self.settings_for(merchant), http)
                client._access_token(client.configuration())
                status = "credentials_valid_seller_unverified"
            elif provider == "zendesk":
                result = provider_json(
                    http,
                    "https://" + cfg["subdomain"] + ".zendesk.com/api/v2/users/me.json",
                    headers={"Authorization": "Bearer " + secret["oauth_token"]},
                )
                if result.get("user", {}).get("role") not in ("agent", "admin"):
                    raise StoreError(502, "Zendesk agent access is required")
                status = "read_verified"
            elif provider == "shopify":
                result = provider_json(
                    http,
                    "https://" + cfg["shop_domain"] + "/admin/api/2026-10/graphql.json",
                    method="POST",
                    headers={"X-Shopify-Access-Token": secret["admin_token"]},
                    json={"query": "{ shop { id } }"},
                )
                if not result.get("data", {}).get("shop", {}).get("id"):
                    raise StoreError(502, "Shopify did not confirm this shop")
                status = "read_verified"
            else:
                result = provider_json(
                    http,
                    "https://api.easypost.com/v2/trackers",
                    auth=(secret["api_key"], ""),
                    params={"page_size": 1},
                )
                if not isinstance(result.get("trackers"), list):
                    raise StoreError(502, "EasyPost did not confirm tracker access")
                status = "read_verified"
        except StoreError:
            with self.store.transaction(write=True) as db:
                db.execute(
                    "UPDATE platform_connections SET checked_at=?,check_status='failed' WHERE merchant_id=? AND provider=? AND revision=?",
                    (now(), str(merchant), provider, row["revision"]),
                )
            raise
        with self.store.transaction(write=True) as db:
            changed = db.execute(
                "UPDATE platform_connections SET checked_at=?,check_status=? WHERE merchant_id=? AND provider=? AND revision=?",
                (now(), status, str(merchant), provider, row["revision"]),
            )
            if not changed.rowcount:
                raise StoreError(409, "Connection changed during the check")
            audit(db, merchant, actor, "connection_checked", provider, status=status)
        return self.view(self.get(merchant, provider))


def provider_json(http, url, *, method="GET", **kwargs):
    try:
        with http.stream(
            method, url, follow_redirects=False, timeout=15, **kwargs
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise StoreError(
                    503, "Provider unavailable or rate limited; retry later"
                )
            if response.status_code != 200:
                raise StoreError(
                    502, "Provider did not authorize or confirm this request"
                )
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 2_000_000:
                    raise StoreError(502, "Provider response is too large")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError()
            return value
    except (httpx.HTTPError, ValueError, KeyError):
        raise StoreError(502, "Provider response could not be verified") from None


settings_for = _request_settings_for
