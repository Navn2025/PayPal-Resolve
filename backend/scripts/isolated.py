"""Run local checks without reading existing dotenv files or inheriting service secrets.

Usage: uv run python scripts/isolated.py -m pytest -q
       uv run python scripts/isolated.py scripts/export_openapi.py
"""

import os
from pathlib import Path
import runpy
import sys
import tempfile


def main():
    if os.name == "nt":
        # Python 3.12's special 0700 ACL omits this managed sandbox identity.
        # Use the workspace's inherited ACL for disposable test directories.
        mkdir = os.mkdir

        def inherited_mkdir(path, mode=0o777, *, dir_fd=None):
            return mkdir(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)

        os.mkdir = inherited_mkdir
    # Examine names only; do not read/copy secret values.
    for name in list(os.environ):
        if name.startswith(("RESOLVE_", "GROQ_", "OPENROUTER_", "PAYPAL_")) or name in (
            "DATABASE_URL",
            "POSTMAN_API_KEY",
        ):
            del os.environ[name]
    scratch = Path(__file__).resolve().parents[2] / ".local" / "isolated"
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(scratch)
    tempfile.tempdir = str(scratch)
    with tempfile.TemporaryDirectory(
        prefix="resolve-isolated-", dir=scratch, ignore_cleanup_errors=True
    ) as directory:
        os.environ["RESOLVE_ISOLATED_TEST"] = "1"
        os.environ["RESOLVE_DATABASE_PATH"] = str(Path(directory) / "resolve.sqlite3")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        args = sys.argv[1:]
        if "--postgres-local" in args:
            args.remove("--postgres-local")
            os.environ["RESOLVE_TEST_DATABASE_URL"] = (
                "postgresql://resolve_synthetic@127.0.0.1:56439/postgres"
            )
        if "--storage-postgres" in args:
            args.remove("--storage-postgres")
            os.environ["RESOLVE_TEST_STORAGE"] = "postgres"
        if args[:1] == ["-m"]:
            if args[1] == "pytest":
                args.extend(["--basetemp", str(Path(directory) / "pytest")])
            sys.argv = args[1:]
            runpy.run_module(args[1], run_name="__main__", alter_sys=True)
        else:
            sys.argv = args
            runpy.run_path(args[0], run_name="__main__")


if __name__ == "__main__":
    main()
