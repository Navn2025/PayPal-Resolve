"""SQLite transaction and immutable migration implementation."""

from app.repositories.base import from_cents as from_cents, to_cents as to_cents

from app.core.config import BACKEND_DIR
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app.core.exceptions import StoreError
from app.repositories.base import (
    ResolveStore as ResolveStore,
    IssuedMerchantKey as IssuedMerchantKey,
    LEGACY_MERCHANT_ID as LEGACY_MERCHANT_ID,
)
from app.repositories.factory import configured_store as configured_store

_SQLITE_FORWARD_ADDITIONS = {
    "015_merchant_paypal_flow_claim.sql": (("merchant_paypal_flows", "claimed_at"),),
    "017_customer_email_notifications.sql": (
        ("customer_intake_invites", "email_notifications"),
        ("customer_case_contacts", "email_notifications"),
    ),
}


def _already_added(connection, migration, statement):
    # SQLite lacks ADD COLUMN IF NOT EXISTS. Skip only the exact forward
    # additions that some databases already received from an interim script.
    return any(
        statement.lstrip().startswith(f"ALTER TABLE {table} ADD COLUMN {column} ")
        and connection.execute(
            "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (table, column)
        ).fetchone()
        for table, column in _SQLITE_FORWARD_ADDITIONS.get(migration, ())
    )


class _SQLiteTransactions:
    def __init__(self, path: Path, timeout: float = 5.0):
        self.path = Path(path).resolve()
        self.timeout = timeout

    @contextmanager
    def transaction(self, *, write: bool = False):
        connection = sqlite3.connect(
            self.path, timeout=self.timeout, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.OperationalError as error:
            connection.rollback()
            if error.sqlite_errorcode in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise StoreError(503, "Database is busy; retry the request") from error
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        directory = BACKEND_DIR / "migrations"
        migrations = [
            directory / "001_initial.sql",
            directory / "002_merchants.sql",
            directory / "003_refund_approvals.sql",
            directory / "004_capture_verifications.sql",
            directory / "005_refund_executions.sql",
            directory / "006_execution_identity.sql",
            directory / "007_case_events.sql",
            directory / "008_refund_history_and_case_lifecycle.sql",
            directory / "009_resolution_workspace.sql",
            directory / "010_customer_portal.sql",
            directory / "011_customer_intake_and_triage.sql",
            directory / "012_hosted_followup.sql",
            directory / "013_case_order.sql",
            directory / "014_merchant_web_auth.sql",
            directory / "015_merchant_paypal_flow_claim.sql",
            directory / "016_customer_google_and_smtp.sql",
            directory / "017_customer_email_notifications.sql",
            directory / "018_resolution_evidence_sdk.sql",
            directory / "019_commerce_evidence.sql",
            directory / "020_merchant_orders.sql",
            directory / "021_investigations.sql",
            directory / "022_investigation_commerce.sql",
            directory / "023_investigation_payment_facts.sql",
            directory / "024_investigation_financial_state.sql",
            directory / "025_investigation_queue_audit.sql",
            directory / "026_merchant_operations.sql",
            directory / "027_embedded_aftercare.sql",
            directory / "028_resolution_assurance.sql",
        ]
        with self.transaction(write=True) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in range(len(migrations) + 1):
                raise RuntimeError(f"Unsupported database schema version: {version}")
            for index in range(version, len(migrations)):
                migration = migrations[index]
                if migration.name == "021_investigations.sql":
                    connection.execute(
                        (directory / "investigation_prerequisite.sql").read_text(
                            encoding="utf-8"
                        )
                    )
                statement = ""
                for line in migration.read_text(encoding="utf-8").splitlines(True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        if not _already_added(connection, migration.name, statement):
                            connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Incomplete migration: {migration.name}")
                connection.execute(f"PRAGMA user_version = {index + 1}")


class SQLiteStore(_SQLiteTransactions, ResolveStore):
    """File-backed store for local development and the SQLite test suite."""
