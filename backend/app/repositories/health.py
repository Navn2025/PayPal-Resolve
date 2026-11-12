"""Read-only database liveness without exposing storage failure details."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.repositories.base import ResolveStore


def database_ready(store: ResolveStore) -> bool:
    try:
        with store.transaction() as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception:
        return False
    return True
