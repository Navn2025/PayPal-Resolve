"""Disposable UI service. Run only through backend/scripts/isolated.py."""
import os
from pathlib import Path

from cryptography.fernet import Fernet
import uvicorn

from app.main import create_app
from app.settings import Settings

if os.environ.get("RESOLVE_ISOLATED_TEST") != "1":
    raise RuntimeError("Use the isolated runner; never load existing local configuration")

app = create_app(
    Path(os.environ["RESOLVE_DATABASE_PATH"]),
    settings=Settings(_env_file=None, platform_encryption_key=Fernet.generate_key().decode()),
)
uvicorn.run(app, host="127.0.0.1", port=8025, access_log=False)
