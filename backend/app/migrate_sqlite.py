"""Copy a read-only snapshot of a Resolve SQLite database into an empty Postgres schema."""

import argparse
from contextlib import closing
from itertools import zip_longest
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from psycopg import Error, sql
from pydantic import ValidationError

from .errors import StoreError
from .postgres import PostgresStore
from .settings import Settings
from .storage import LEGACY_MERCHANT_ID, SQLiteStore


BATCH_SIZE = 64


def _quoted(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _copy(source, destination):
    if not source.is_file():
        raise RuntimeError("The SQLite source file does not exist")
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as current:
        with closing(sqlite3.connect(destination)) as snapshot:
            current.backup(snapshot, pages=256, sleep=0.05)
    # Old SQLite versions are upgraded only in the snapshot.
    SQLiteStore(destination).initialize()


def _columns(source, table):
    columns = source.execute(f"PRAGMA table_info({_quoted(table)})").fetchall()
    names = [column[1] for column in columns]
    keys = sorted(
        (column for column in columns if column[5]), key=lambda column: column[5]
    )
    if not names or not keys:
        raise RuntimeError("Unexpected SQLite table structure")
    return names, keys


def _copy_table(source, raw, table, names):
    source_sql = f"SELECT {','.join(map(_quoted, names))} FROM {_quoted(table)}"
    target_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, names)),
        sql.SQL(",").join(sql.Placeholder() for _ in names),
    )
    rows = source.execute(source_sql)
    copied = 0
    with raw.cursor() as destination:
        while batch := rows.fetchmany(BATCH_SIZE):
            destination.executemany(target_sql, batch)
            copied += len(batch)
    return copied


def _verify_table(source, raw, table, names, keys, count):
    ordered_keys = ",".join(_quoted(column[1]) for column in keys)
    source_sql = f"SELECT {','.join(map(_quoted, names))} FROM {_quoted(table)} ORDER BY {ordered_keys}"
    order = [
        sql.SQL('{} COLLATE "C"').format(sql.Identifier(column[1]))
        if column[2].upper() == "TEXT"
        else sql.Identifier(column[1])
        for column in keys
    ]
    target_sql = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
        sql.SQL(",").join(map(sql.Identifier, names)),
        sql.Identifier(table),
        sql.SQL(",").join(order),
    )
    checked = 0
    sentinel = object()
    with raw.cursor(name="resolve_import_check") as target:
        target.itersize = BATCH_SIZE
        target.execute(target_sql)
        for left, right in zip_longest(
            source.execute(source_sql), target, fillvalue=sentinel
        ):
            if left is sentinel or right is sentinel or left != tuple(right):
                raise RuntimeError(f"Copied rows did not match in table {table}")
            checked += 1
    if checked != count:
        raise RuntimeError(f"Copied row count did not match in table {table}")


def _import(snapshot, target):
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)) as source:
        if (
            source.execute("PRAGMA quick_check").fetchone()[0] != "ok"
            or source.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise RuntimeError("The SQLite snapshot did not pass integrity checks")
        tables = [
            row[0]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND substr(name,1,7)!='sqlite_' ORDER BY name"
            )
        ]
        metadata = {table: _columns(source, table) for table in tables}
        sequences = dict(source.execute("SELECT name,seq FROM sqlite_sequence"))
        with target.transaction(write=True) as db:
            pg_tables = {
                row[0]
                for row in db.execute(
                    """SELECT table_name FROM information_schema.tables WHERE table_schema=?
                   AND table_type='BASE TABLE' AND table_name!='schema_migrations'""",
                    (target.schema,),
                )
            }
            if set(tables) != pg_tables:
                raise RuntimeError("SQLite and PostgreSQL table sets do not match")
            for table in tables:
                check = sql.SQL("SELECT 1 FROM {}").format(sql.Identifier(table))
                if table == "merchants":
                    check += sql.SQL(" WHERE id<>%s")
                    existing = db.execute(
                        check + sql.SQL(" LIMIT 1"), (str(LEGACY_MERCHANT_ID),)
                    )
                else:
                    existing = db.execute(check + sql.SQL(" LIMIT 1"))
                if existing.fetchone() is not None:
                    raise RuntimeError(
                        "PostgreSQL target is not empty; use a fresh Resolve database"
                    )
            db.execute("SET CONSTRAINTS ALL DEFERRED")
            db.execute("DELETE FROM merchants WHERE id=?", (str(LEGACY_MERCHANT_ID),))
            counts = {
                table: _copy_table(source, db.raw, table, metadata[table][0])
                for table in tables
            }
            db.execute("SET CONSTRAINTS ALL IMMEDIATE")
            identities = db.execute(
                """SELECT table_name,column_name FROM information_schema.columns
                   WHERE table_schema=? AND is_identity='YES'""",
                (target.schema,),
            ).fetchall()
            for row in identities:
                table, column = row[0], row[1]
                highest = db.execute(
                    sql.SQL("SELECT COALESCE(max({}),0) FROM {}").format(
                        sql.Identifier(column), sql.Identifier(table)
                    )
                ).fetchone()[0]
                next_id = max(highest, sequences.get(table, 0)) + 1
                db.execute(
                    sql.SQL("ALTER TABLE {} ALTER COLUMN {} RESTART WITH {}").format(
                        sql.Identifier(table),
                        sql.Identifier(column),
                        sql.Literal(next_id),
                    )
                )
            for table, (names, keys) in metadata.items():
                _verify_table(source, db.raw, table, names, keys, counts[table])
        return counts


def migrate(source: Path, target: PostgresStore):
    with TemporaryDirectory(prefix="resolve-sqlite-copy-") as folder:
        snapshot = Path(folder) / "snapshot.sqlite3"
        _copy(source.resolve(), snapshot)
        target.initialize()
        return _import(snapshot, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        help="Source SQLite file (defaults to RESOLVE_DATABASE_PATH)",
    )
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        if not settings.database_url:
            raise RuntimeError(
                "Set RESOLVE_DATABASE_URL to the empty PostgreSQL target"
            )
        counts = migrate(
            args.source or settings.database_path, PostgresStore(settings.database_url)
        )
    except (RuntimeError, StoreError) as error:
        print(
            str(error) if isinstance(error, RuntimeError) else error.detail,
            file=sys.stderr,
        )
        return 1
    except (sqlite3.Error, Error, OSError, ValidationError):
        print(
            "Database import failed; the copied rows were not committed. Check access and schema compatibility.",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "verified_tables": len(counts),
                "verified_rows": sum(counts.values()),
                "counts": counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
