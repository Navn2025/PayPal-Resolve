"""Compatibility import; implementation: app.cli.migrate_sqlite."""

if __name__ == "__main__":
    from runpy import run_module

    run_module("app.cli.migrate_sqlite", run_name="__main__")
else:
    from app._compat import redirect

    redirect(__name__, "app.cli.migrate_sqlite")
