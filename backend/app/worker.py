"""Compatibility import; implementation: app.workers.refunds."""

if __name__ == "__main__":
    from runpy import run_module

    run_module("app.workers.refunds", run_name="__main__")
else:
    from app._compat import redirect

    redirect(__name__, "app.workers.refunds")
