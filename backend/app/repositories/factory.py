"""Select the configured storage engine without opening a connection."""

from app.repositories.base import ResolveStore


def configured_store(settings, *, sqlite_path=None) -> ResolveStore:
    from app.repositories.sqlite import SQLiteStore

    if sqlite_path is not None:
        return SQLiteStore(sqlite_path)
    if settings.database_url is not None:
        from app.repositories.postgres import PostgresStore

        return PostgresStore(settings.database_url)
    return SQLiteStore(settings.database_path)
