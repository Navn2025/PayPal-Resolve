"""PostgreSQL transaction driver for the shared Resolve repository."""

from app.core.config import BACKEND_DIR


from contextlib import contextmanager
from functools import lru_cache
from hashlib import sha256
from threading import Lock
import re

import psycopg
from psycopg import errors, sql
from pydantic import SecretStr
from psycopg_pool import ConnectionPool, PoolTimeout, TooManyRequests

from app.core.exceptions import StoreError
from app.repositories.base import ResolveStore


MIGRATIONS = BACKEND_DIR / "migrations" / "postgres"
# The only known interim scripts that were applied before their changes were
# split into forward migrations. Key by original digest as well as version,
# so an additional edit does not silently accept an old checksum.
_INTERIM_CHECKSUMS = {
    (
        3,
        "eb6e217bdade284267610657924ef64e70198a21eefca840f0233edea2cc3e64",
    ): "930815d19dd63d32ca11991c9ced6409e6f0617e4cbe34a094896a0c5daf676a",
    (
        5,
        "f35198f84e02a31e1a364d945b25507e685415c6c8401cfdc41e811f0829a1bc",
    ): "a40a7fd1a6d29de6d8a5ce8e2a4ae6e8db7a664701b47850ebdba363f8cd4c54",
}
_SQL_TOKEN = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|\?""")


@lru_cache(maxsize=1024)
def _bind(statement):
    # Shared statements use SQLite's question marks. Never turn a literal '?' into a parameter.
    escaped = statement.replace("%", "%%")
    return _SQL_TOKEN.sub(
        lambda token: "%s" if token.group() == "?" else token.group(), escaped
    )


class _Row:
    """Support the repository's name, index and tuple access to database rows."""

    def __init__(self, index, values):
        self._index = index
        self._values = tuple(values)

    def keys(self):
        return self._index.keys()

    def __getitem__(self, key):
        return self._values[self._index[key] if isinstance(key, str) else key]

    def __iter__(self):
        return iter(self._values)


def _rows(cursor):
    index = {column.name: i for i, column in enumerate(cursor.description or ())}
    return lambda values: _Row(index, values)


class _Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, statement, parameters=None):
        if isinstance(statement, str) and parameters is not None:
            statement = _bind(statement)
        return self.raw.execute(statement, parameters)


class PostgresStore(ResolveStore):
    def __init__(
        self,
        database_url: SecretStr,
        *,
        schema="resolve",
        timeout: float = 5.0,
        pool_size: int = 8,
    ):
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema)
            or schema.startswith("pg_")
            or schema == "public"
        ):
            raise ValueError("Use a dedicated Resolve database schema")
        if not 1 <= pool_size <= 32:
            raise ValueError("Use a PostgreSQL pool size between 1 and 32")
        self._pool = None
        self._pool_lock = Lock()
        self._pool_size = pool_size
        self._database_url = database_url
        self.schema = schema
        self.timeout = timeout
        self._lock_key = int.from_bytes(
            sha256(("resolve-store:" + schema).encode()).digest()[:8],
            "big",
            signed=True,
        )

    def _connect(self):
        try:
            return psycopg.connect(
                self._database_url.get_secret_value(),
                connect_timeout=8,
                prepare_threshold=None,
                row_factory=_rows,
            )
        except psycopg.Error:
            raise StoreError(503, "PostgreSQL connection is unavailable") from None

    def _connections(self):
        # One bounded pool per store/process; never cache tenant data or sessions.
        with self._pool_lock:
            if self._pool is None:
                pool = ConnectionPool(
                    self._database_url.get_secret_value(),
                    kwargs={
                        "connect_timeout": 8,
                        "prepare_threshold": None,
                        "row_factory": _rows,
                    },
                    min_size=0,
                    max_size=self._pool_size,
                    max_waiting=32,
                    timeout=8,
                    max_idle=60,
                    max_lifetime=600,
                    reconnect_timeout=8,
                    name="resolve-store",
                    open=False,
                )
                pool.open()
                self._pool = pool
            return self._pool

    def close(self):
        with self._pool_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.close()

    def _lock(self, raw):
        raw.execute(
            "SELECT set_config('lock_timeout', %s, true)",
            (f"{int(self.timeout * 1000)}ms",),
        )
        raw.execute("SELECT pg_advisory_xact_lock(%s)", (self._lock_key,))

    def _search_path(self, raw):
        raw.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema))
        )

    @contextmanager
    def transaction(self, *, write=False):
        try:
            with self._connections().connection() as raw:
                if write:
                    # Lock before reading any application state, as BEGIN IMMEDIATE did in SQLite.
                    raw.execute(
                        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                    )
                    self._lock(raw)
                    self._search_path(raw)
                else:
                    # One setup round trip; both statements are transaction-local.
                    raw.execute(
                        sql.SQL(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY; SET LOCAL search_path TO {}"
                        ).format(sql.Identifier(self.schema))
                    )
                yield _Connection(raw)
        except (
            errors.LockNotAvailable,
            errors.SerializationFailure,
            errors.DeadlockDetected,
        ):
            raise StoreError(503, "Database is busy; retry the request") from None
        except (psycopg.OperationalError, PoolTimeout, TooManyRequests):
            raise StoreError(503, "PostgreSQL connection is unavailable") from None

    def initialize(self):
        files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
        if not files or [int(file.name[:3]) for file in files] != list(
            range(1, len(files) + 1)
        ):
            raise RuntimeError("PostgreSQL migration sequence is invalid")
        scripts = [file.read_text(encoding="utf-8") for file in files]
        digests = [sha256(script.encode()).hexdigest() for script in scripts]
        with self.transaction(write=True) as db:
            db.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(self.schema)
                )
            )
            db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations
                          (version INTEGER PRIMARY KEY, checksum TEXT NOT NULL)""")
            applied = [
                (row[0], row[1])
                for row in db.execute(
                    "SELECT version,checksum FROM schema_migrations ORDER BY version"
                )
            ]
            for index, (version, recorded) in enumerate(applied):
                expected = digests[index] if index < len(digests) else None
                interim = _INTERIM_CHECKSUMS.get((version, expected))
                if (
                    version != index + 1
                    or expected is None
                    or recorded not in (expected, interim)
                ):
                    raise RuntimeError(
                        "Unsupported or modified PostgreSQL migration history "
                        f"at version {index + 1:03d}; check the deployed release "
                        "and restore the original migration files."
                    )
            for index in range(len(applied), len(scripts)):
                if files[index].name == "010_investigations.sql":
                    db.execute(
                        (
                            MIGRATIONS.parent / "investigation_prerequisite.sql"
                        ).read_text(encoding="utf-8")
                    )
                db.execute(scripts[index])
                db.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)",
                    (index + 1, digests[index]),
                )
