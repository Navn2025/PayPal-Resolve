"""Run the optional Nodemailer transport without putting secrets in arguments."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from .errors import StoreError


MAILER = Path(__file__).resolve().parent.parent / "mailer"
TIMEOUT = 25


def smtp_runtime():
    executable = shutil.which("node")
    if not executable or not (MAILER / "node_modules" / "nodemailer").is_dir():
        raise StoreError(503, "Install Node.js and run npm ci in backend/mailer")
    return executable


def send_smtp(executable, settings, message, identifier):
    message_id = f"<resolve.{identifier}@{message['from'].rsplit('@', 1)[1]}>"
    payload = {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "secure": settings.smtp_secure,
        "user": settings.smtp_user,
        "password": settings.smtp_password.get_secret_value(),
        "message": {**message, "messageId": message_id},
    }
    # Preserve local CA configuration but keep unrelated API and DB credentials
    # and Node runtime flags out of the mail subprocess.
    env = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "NODE_EXTRA_CA_CERTS"}
    }
    try:
        result = subprocess.run(
            [executable, str(MAILER / "send.mjs")],
            input=json.dumps(payload),
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        response = json.loads(result.stdout) if result.returncode == 0 else {}
        status = response.get("status") if isinstance(response, dict) else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        status = None
    if status == "accepted":
        return "accepted", None
    if status == "retry":
        return "retry", None
    return "failed", None
