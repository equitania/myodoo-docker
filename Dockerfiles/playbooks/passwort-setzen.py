#!/usr/bin/env python3
# Version: 1.0.0
# Date: 21.10.2026
"""Store the hash of the common test password for passwoerter.yaml.

Asks for the password twice, builds an Odoo-compatible pbkdf2-sha512 hash and
writes it as TEST_PASSWORD_HASH into the playbooks' env_file (mode 600). The
password itself is stored nowhere.

Run as root on the server: python3 passwort-setzen.py
"""

import base64
import getpass
import hashlib
import os
import secrets
import sys

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "21.10.2026"

ENV_FILE = "/root/.config/odoodev/test-passwords.env"
KEY = "TEST_PASSWORD_HASH"
ROUNDS = 600_000  # Odoo 18 default for pbkdf2_sha512
MIN_LENGTH = 8


def pbkdf2_sha512_hash(password: str) -> str:
    """Build a passlib-compatible $pbkdf2-sha512$ hash (as odoodev does) with the stdlib only."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, ROUNDS)

    def ab64(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii").replace("+", ".").rstrip("=")

    return f"$pbkdf2-sha512${ROUNDS}${ab64(salt)}${ab64(digest)}"


def main() -> int:
    password = getpass.getpass("Neues Passwort für alle Benutzer des Testsystems: ")
    if len(password) < MIN_LENGTH:
        print(f"Abgebrochen: Das Passwort muss mindestens {MIN_LENGTH} Zeichen lang sein.", file=sys.stderr)
        return 1
    if getpass.getpass("Passwort wiederholen: ") != password:
        print("Abgebrochen: Die beiden Eingaben stimmen nicht überein.", file=sys.stderr)
        return 1

    line = f"{KEY}='{pbkdf2_sha512_hash(password)}'\n"

    os.makedirs(os.path.dirname(ENV_FILE), mode=0o700, exist_ok=True)
    kept: list[str] = []
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as handle:
            kept = [existing for existing in handle if not existing.startswith(f"{KEY}=")]

    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.writelines(kept + [line])
    os.chmod(ENV_FILE, 0o600)

    print(f"Gespeichert in {ENV_FILE}. Jetzt das Playbook starten, z. B.:")
    print("  odoodev run passwoerter.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
