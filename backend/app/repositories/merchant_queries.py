"""Merchant-scoped queries shared by HTTP adapters and atomic key workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.repositories.base import ResolveStore


def audit_history(store: ResolveStore, merchant_id: UUID) -> dict:
    with store.transaction() as connection:
        return {
            "items": [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM platform_audit WHERE merchant_id=? ORDER BY recorded_at DESC,id DESC LIMIT 200",
                    (str(merchant_id),),
                )
            ]
        }


def sdk_keys(store: ResolveStore, merchant_id: UUID) -> dict:
    with store.transaction() as connection:
        return {
            "items": [
                dict(row)
                for row in connection.execute(
                    "SELECT k.id,k.created_at,a.source AS support_source FROM merchant_api_keys k LEFT JOIN aftercare_apps a ON a.key_id=k.id AND a.merchant_id=k.merchant_id WHERE k.merchant_id=? AND k.scope='commerce' AND k.revoked_at IS NULL ORDER BY k.created_at DESC",
                    (str(merchant_id),),
                )
            ]
        }


def active_key_count(connection, merchant_id: UUID) -> int:
    return connection.execute(
        "SELECT count(*) FROM merchant_api_keys WHERE merchant_id=? AND scope='commerce' AND revoked_at IS NULL",
        (str(merchant_id),),
    ).fetchone()[0]


def add_support_grant(
    connection, key_id: UUID, merchant_id: UUID, source: str, created_at: str
) -> None:
    connection.execute(
        "INSERT INTO aftercare_apps VALUES (?,?,?,?)",
        (str(key_id), str(merchant_id), source, created_at),
    )


def find_commerce_key(connection, key_id: UUID, merchant_id: UUID):
    return connection.execute(
        "SELECT id FROM merchant_api_keys WHERE id=? AND merchant_id=? AND scope='commerce'",
        (str(key_id), str(merchant_id)),
    ).fetchone()


def revoke_key(connection, key_id: str, revoked_at: str) -> None:
    connection.execute(
        "UPDATE merchant_api_keys SET revoked_at=? WHERE id=?", (revoked_at, key_id)
    )


def has_connection(store: ResolveStore, merchant_id: UUID) -> bool:
    with store.transaction() as connection:
        return bool(
            connection.execute(
                "SELECT 1 FROM platform_connections WHERE merchant_id=?",
                (str(merchant_id),),
            ).fetchone()
        )
