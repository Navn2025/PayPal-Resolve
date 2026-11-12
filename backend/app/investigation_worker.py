"""Compatibility import; implementation: app.workers.investigation."""

if __name__ == "__main__":
    from runpy import run_module

    run_module("app.workers.investigation", run_name="__main__")
else:
    from app._compat import redirect

    redirect(__name__, "app.workers.investigation")
