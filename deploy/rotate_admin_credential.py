"""Rotate the private operations-monitor password without printing it."""

from __future__ import annotations

import re
import secrets
import subprocess
from pathlib import Path


ENV_PATH = Path("/opt/meteostation/.env")
CREDENTIAL_PATH = Path("/tmp/meteostation-admin-credential.txt")


def main() -> None:
    password = secrets.token_urlsafe(32)
    content = ENV_PATH.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"^METEOSTATION_ADMIN_PASSWORD=.*$",
        "METEOSTATION_ADMIN_PASSWORD=" + password,
        content,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise SystemExit("admin password setting not found")
    ENV_PATH.write_text(updated, encoding="utf-8")
    CREDENTIAL_PATH.write_text(
        "username=cloudylake\npassword=" + password + "\n",
        encoding="utf-8",
    )
    CREDENTIAL_PATH.chmod(0o600)
    subprocess.run(
        ["systemctl", "restart", "meteostation-web"],
        check=True,
    )


if __name__ == "__main__":
    main()
