"""Explicit synthetic browser scenarios, after the isolated runner clears secrets."""
import os
from pathlib import Path
import runpy
import sys

if os.environ.get("RESOLVE_ISOLATED_TEST") != "1":
    raise RuntimeError("Use backend/scripts/isolated.py")
scenario = sys.argv[1] if len(sys.argv) > 1 else ""
if scenario == "paypal-email":
    for flag in ("PAYPAL_SIMULATION", "PAYPAL_LOGIN", "EMAIL_FIXTURE"):
        os.environ["RESOLVE_UI_" + flag] = "1"
elif scenario == "google":
    os.environ["RESOLVE_UI_GOOGLE_FIXTURE"] = "1"
elif scenario:
    raise RuntimeError("Unknown isolated browser scenario")
runpy.run_path(str(Path(__file__).with_name("fixture_backend.py")), run_name="__main__")
