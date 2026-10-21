#!/usr/bin/env python3
# Version: 1.0.0
# Date: 21.10.2026
"""Generate odoodev server playbooks that rebuild the test instance from the newest live backup.

One playbook per data state (<state>.yaml), plus wiederherstellen.yaml (puts back the
state saved before the last run) and passwoerter.yaml (one common password, 2FA off).
Target is the test instance (default test-odoo / test-db), source the live instance's
backups (default live-odoo) as written by container2backup.py.

Server values are read from ~/docker2update.yaml (database name, data directory of the
test container) and ~/container2backup.yaml (backup directory, live database name,
archive format). Every value can be overridden on the command line.

Run as root on the server:  python3 generate.py --out ~/playbooks
Needs odoodev >= 0.75.7 (server.uninstall, temp_dir).
"""

import argparse
import os
import re
import sys

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "21.10.2026"

FLAGS = ("deactivate_cron", "neutralize", "anonymize", "wipe", "purge_transactions", "purge_master_data")
NEUTRALIZE_ONLY = ("deactivate_cron", "neutralize")

STATES = {
    "neutral": ("Real data, neutralized only", NEUTRALIZE_ONLY),
    "anonym": (
        "Neutralized, personal data replaced by fake values (logins kept)",
        ("deactivate_cron", "neutralize", "anonymize"),
    ),
    "anonym-leer": (
        "Neutralized, anonymized, chatter and attachments deleted",
        ("deactivate_cron", "neutralize", "anonymize", "wipe"),
    ),
    "stammdaten": (
        "Neutralized, all transactional data deleted (partners, products, pricelists kept)",
        ("deactivate_cron", "neutralize", "purge_transactions"),
    ),
    "vorlage": (
        "Neutralized, transactions and customer/vendor/contact partners deleted "
        "(products, pricelists, users, company, config kept)",
        ("deactivate_cron", "neutralize", "purge_master_data"),
    ),
}

# Archive suffix per container2backup compression format. Encrypted backups
# (BACKUP_ENCRYPTION_ENABLED in the .env, suffix .gpg) and SQL-only backups
# cannot be restored by server.restore.
SUFFIX_BY_FORMAT = {"7z": "7z", "zip": "zip", "gzip": "tar.gz", "zstd": "tar.zst"}

SAFETY_DIR = "/opt/backups/prerestore"
# Where server.restore unpacks the backup — a local disk, because the backup
# directory may be a read-only network share.
RESTORE_TMP = "/opt/backups/restore-tmp"
ENV_FILE = "/root/.config/odoodev/test-passwords.env"

# EBICS only works with the bank keys of the live system. Right after the restore,
# before Odoo starts, the copy is switched off and its stored passphrases are
# cleared (no-op without EBICS). After the rebuild the modules are uninstalled
# with server.uninstall (Odoo's own uninstall in the running container). Do not
# replace that with SQL 'to remove' + -u: the rebuild's -u all resets the state,
# and odoo-bin -u next to the serving process deadlocks.
EBICS_OFF_SQL = (
    "DO $$ BEGIN "
    "IF to_regclass('ebics_config') IS NOT NULL THEN UPDATE ebics_config SET active = false; END IF; "
    "IF to_regclass('ebics_userid') IS NOT NULL THEN "
    "UPDATE ebics_userid SET active = false, ebics_passphrase = NULL, ebics_sig_passphrase = NULL; END IF; "
    "END $$;"
)
EBICS_MODULES = ("account_ebics", "account_ebics_batch", "account_ebics_oe")

# Same users as `odoodev db reset-auth --passwords`: everyone except the technical
# accounts. A missing or malformed hash aborts before anything changes.
EXCLUDED_LOGINS = "('__system__', 'default', 'public', 'portaltemplate')"
PASSWORD_SQL = (
    "DO $reset$ BEGIN "
    "IF '{{ env.TEST_PASSWORD_HASH }}' NOT LIKE '$pbkdf2-sha512$%' THEN "
    "RAISE EXCEPTION 'TEST_PASSWORD_HASH missing or invalid - run python3 passwort-setzen.py first'; END IF; "
    "UPDATE res_users SET password = '{{ env.TEST_PASSWORD_HASH }}' "
    f"WHERE id > 0 AND login NOT IN {EXCLUDED_LOGINS}; "
    "END $reset$;"
)
TOTP_SQL = (
    "DO $totp$ BEGIN "
    "IF EXISTS (SELECT 1 FROM information_schema.columns "
    "WHERE table_name = 'res_users' AND column_name = 'totp_secret') THEN "
    "UPDATE res_users SET totp_secret = NULL WHERE totp_secret IS NOT NULL; END IF; "
    "IF to_regclass('auth_totp_device') IS NOT NULL THEN DELETE FROM auth_totp_device; END IF; "
    "DELETE FROM ir_config_parameter WHERE key = 'auth_totp.policy'; "
    "END $totp$;"
)

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def load_yaml(path):
    """Return the parsed YAML file, or None if it is missing or PyYAML is not installed."""
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return None
    try:
        import yaml
    except ImportError:
        print(f"Note: python3-yaml missing, {path} not read", file=sys.stderr)
        return None
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def detect(args):
    """Fill unset values from docker2update.yaml / container2backup.yaml, then from the templates' defaults."""
    found = []
    update_cfg = load_yaml(args.update_config) or {}
    for entry in update_cfg.get("containers") or []:
        if entry.get("container_name") != args.test_container:
            continue
        if not args.test_db and entry.get("database_name"):
            args.test_db = entry["database_name"]
            found.append(f"test database '{args.test_db}' ({args.update_config})")
        match = re.search(r"-v\s+(\S+):/opt/odoo/data\b", str(entry.get("volume", "")))
        if not args.data_dir and match:
            args.data_dir = match.group(1)
            found.append(f"data directory {args.data_dir} ({args.update_config})")

    backup_cfg = load_yaml(args.backup_config) or {}
    defaults = backup_cfg.get("defaults") or {}
    live_entry = next(
        (db for db in backup_cfg.get("databases") or [] if db.get("data_container") == args.live_container), {}
    )
    if not args.backup_dir and defaults.get("backup_path"):
        args.backup_dir = os.path.join(str(defaults["backup_path"]), "docker")
        found.append(f"backup directory {args.backup_dir} ({args.backup_config})")
    if not args.live_db and live_entry.get("name"):
        args.live_db = live_entry["name"]
        found.append(f"live database '{args.live_db}' ({args.backup_config})")
    if not args.backup_suffix and (live_entry or defaults):
        stream = live_entry.get("stream", defaults.get("stream", False))
        compression = {**(defaults.get("compression") or {}), **(live_entry.get("compression") or {})}
        args.backup_suffix = "tar.zst" if stream else SUFFIX_BY_FORMAT.get(str(compression.get("format", "7z")), "7z")
        found.append(f"archive suffix .{args.backup_suffix} ({args.backup_config})")
        if live_entry.get("only_sql_dump"):
            print("Warning: the live backups are SQL-only — server.restore needs the filestore", file=sys.stderr)

    # Defaults of scripts/docker2update.yaml and scripts/container2backup.yaml.
    args.test_db = args.test_db or "test_db"
    args.live_db = args.live_db or "live_db"
    args.data_dir = args.data_dir or "/opt/odoo/test"
    args.backup_dir = args.backup_dir or "/opt/backups/docker"
    args.backup_suffix = args.backup_suffix or "7z"
    return found


def header(state, label, version, filename):
    return [
        f"# Test instance <- newest live backup, state '{state}'. Odoo {version}.",
        f"# Result: {label}.",
        f"# Generated by generate.py {SCRIPT_VERSION}. Needs odoodev >= 0.75.7.",
        "#",
        f"# Check first without changes: odoodev run {filename} --dry-run",
        f"# Run as root:                 odoodev run {filename}",
        f'version: "{version}"',
        "on_error: stop",
        f'description: "Test instance, state {state}: {label}"',
        "",
    ]


def targets(args):
    return [
        "targets:",
        "  test:",
        f"    db_container: {args.test_db_container}",
        f"    odoo_container: {args.test_container}",
        f"    db_name: {args.test_db}",
        f"    data_dir: {args.data_dir}",
        "",
        "steps:",
    ]


def render_restore(args, state, label, active, source_dir, pattern, safety_backup):
    filename = f"{state}.yaml"
    lines = header(state, label, args.version, filename) + targets(args)
    if safety_backup:
        lines += [
            '  - name: "Save the current state of the test instance"',
            "    command: server.backup",
            "    args:",
            "      target: test",
            f"      backup_dir: {SAFETY_DIR}",
            "      safety: true",
            "",
        ]
    lines += [
        f'  - name: "Stop {args.test_container}"',
        "    command: container.stop",
        "    args: { target: test, component: odoo }",
        "",
        f'  - name: "Restore newest backup ({state})"',
        "    command: server.restore",
        "    args:",
        "      target: test",
        "      backup_source:",
        "        mode: newest_in_dir",
        f"        dir: {source_dir}",
        f'        pattern: "{pattern}"',
        "        select_by: filename_timestamp",
        f"      temp_dir: {RESTORE_TMP}",
        "      drop: true",
        "      template: template0",
    ]
    lines += [f"      {flag}: {'true' if flag in active else 'false'}" for flag in FLAGS]
    lines += [
        "",
        '  - name: "Switch off EBICS (before Odoo starts)"',
        "    command: sql.execute",
        "    args:",
        "      target: test",
        "      statements:",
        f'        - "{EBICS_OFF_SQL}"',
        "",
        "  # update_docker_odoo.py (doup): builds the image, updates all modules on the",
        "  # restored database and starts the container. --type F forces the full update.",
        f'  - name: "Rebuild image, update all modules, start {args.test_container}"',
        "    command: server.rebuild",
        "    args:",
        "      target: test",
        '      extra_args: ["--type", "F"]',
        "",
        "  # A no-op when the database has no EBICS.",
        '  - name: "Uninstall EBICS"',
        "    command: server.uninstall",
        "    args:",
        "      target: test",
        f"      modules: [{', '.join(EBICS_MODULES)}]",
        "",
        '  - name: "Neutralize (odoo-bin neutralize in the container)"',
        "    command: server.neutralize",
        "    args: { target: test }",
        "",
        '  - name: "Verify that the test instance is up on the restored database"',
        "    command: server.verify",
        "    args: { target: test }",
        "",
    ]
    return "\n".join(lines)


def render_passwords(args):
    filename = "passwoerter.yaml"
    label = "common test password for all users, 2FA off"
    lines = header("passwoerter", label, args.version, filename)
    lines.insert(3, "# Prerequisite (once, and whenever the password changes): python3 passwort-setzen.py")
    lines += [f"env_file: {ENV_FILE}", ""] + targets(args)
    lines += [
        '  - name: "Set the common password for every user"',
        "    command: sql.execute",
        "    args:",
        "      target: test",
        "      statements:",
        f'        - "{PASSWORD_SQL}"',
        "",
        '  - name: "Switch off two-factor authentication for every user"',
        "    command: sql.execute",
        "    args:",
        "      target: test",
        "      statements:",
        f'        - "{TOTP_SQL}"',
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", choices=("16", "18", "19"), required=True, help="Odoo version of the test instance")
    parser.add_argument("--out", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--test-container", default="test-odoo")
    parser.add_argument("--test-db-container", default="test-db")
    parser.add_argument("--live-container", default="live-odoo")
    parser.add_argument("--test-db", help="Database of the test instance (default: from docker2update.yaml)")
    parser.add_argument("--live-db", help="Database name in the live backup files (default: from container2backup.yaml)")
    parser.add_argument("--data-dir", help="Host data directory of the test instance (default: from docker2update.yaml)")
    parser.add_argument("--backup-dir", help="Directory of the live backups (default: from container2backup.yaml)")
    parser.add_argument("--backup-suffix", help="Archive suffix, e.g. tar.zst or 7z (default: from container2backup.yaml)")
    parser.add_argument("--update-config", default="~/docker2update.yaml")
    parser.add_argument("--backup-config", default="~/container2backup.yaml")
    parser.add_argument("--no-detect", action="store_true", help="Do not read the server's YAML files")
    args = parser.parse_args()

    if args.no_detect:
        args.update_config = args.backup_config = "/nonexistent"
    found = detect(args)

    for value in (args.test_container, args.test_db_container, args.live_container, args.test_db, args.live_db):
        if not NAME_RE.match(value):
            parser.error(f"invalid container or database name: {value!r}")
    if not re.match(r"^[a-z0-9.]+$", args.backup_suffix):
        parser.error(f"invalid backup suffix: {args.backup_suffix!r}")

    live_pattern = f"{args.live_db}_{args.live_container}_dockerbackup_*.{args.backup_suffix}"
    safety_pattern = f"{args.test_db}_{args.test_container}_prerestore_*.tar.zst"

    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)
    files = {}
    for state, (label, active) in STATES.items():
        files[f"{state}.yaml"] = render_restore(args, state, label, active, args.backup_dir, live_pattern, True)
    # No safety backup here: it would itself become the newest prerestore file.
    files["wiederherstellen.yaml"] = render_restore(
        args,
        "wiederherstellen",
        "State saved before the last playbook run, neutralized",
        NEUTRALIZE_ONLY,
        SAFETY_DIR,
        safety_pattern,
        False,
    )
    files["passwoerter.yaml"] = render_passwords(args)
    for name, content in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8") as handle:
            handle.write(content)

    for line in found:
        print(f"read: {line}")
    print(f"test instance: {args.test_container} / {args.test_db_container}, database {args.test_db}, data {args.data_dir}")
    print(f"live backups:  {os.path.join(args.backup_dir, live_pattern)}")
    print(f"written: {len(files)} playbooks to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
