"""PostgreSQL transaction driver for the shared Resolve repository."""

from contextlib import contextmanager
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import re

import psycopg
from psycopg import errors, sql
from pydantic import SecretStr

from .errors import StoreError
from .storage import ResolveStore


MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "postgres"
# A brief revision of 003 added claimed_at inline. Accept that exact recorded
# checksum only against the restored 003; 004 handles both starting schemas.
_LEGACY_003 = "eb6e217bdade284267610657924ef64e70198a21eefca840f0233edea2cc3e64"
_INTERIM_003 = "930815d19dd63d32ca11991c9ced6409e6f0617e4cbe34a094896a0c5daf676a"
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
        self, database_url: SecretStr, *, schema="resolve", timeout: float = 5.0
    ):
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema)
            or schema.startswith("pg_")
            or schema == "public"
        ):
            raise ValueError("Use a dedicated Resolve database schema")
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
            with self._connect() as raw:
                if write:
                    # Lock before reading any application state, as BEGIN IMMEDIATE did in SQLite.
                    raw.execute(
                        "SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE"
                    )
                    self._lock(raw)
                else:
                    raw.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                self._search_path(raw)
                yield _Connection(raw)
        except (
            errors.LockNotAvailable,
            errors.SerializationFailure,
            errors.DeadlockDetected,
        ):
            raise StoreError(503, "Database is busy; retry the request") from None
        except psycopg.OperationalError:
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
                interim_003 = (
                    version == 3
                    and expected == _LEGACY_003
                    and recorded == _INTERIM_003
                )
                if version != index + 1 or (recorded != expected and not interim_003):
                    raise RuntimeError(
                        "Unsupported or modified PostgreSQL migration history "
                        f"at version {index + 1:03d}; check the deployed release "
                        "and restore the original migration files."
                    )
            for index in range(len(applied), len(scripts)):
                db.execute(scripts[index])
                db.execute(
                    "INSERT INTO schema_migrations VALUES (?,?)",
                    (index + 1, digests[index]),
                )
