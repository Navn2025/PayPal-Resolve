"""Compatibility import; implementation: app.cli.manage."""

if __name__ == "__main__":
    from runpy import run_module

    run_module("app.cli.manage", run_name="__main__")
else:
    from app._compat import redirect

    redirect(__name__, "app.cli.manage")
