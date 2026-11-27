#!/usr/bin/env python3
# Version: 1.7.0
# Date: 27.11.2026
"""Generate odoodev server playbooks that rebuild the test instance from the newest live backup.

One playbook per data state (<state>.yaml) and passwoerter.yaml (one common password, 2FA off).
A test instance is overwritten on every run, so by default nothing is saved beforehand.
With --safety-backup every state playbook first saves the test instance to
/opt/backups/prerestore, and wiederherstellen.yaml puts that state back. Those archives
are never deleted automatically (about the size of a full backup each).
Target is the test instance (default test-odoo / test-db), source the live instance's
backups (default live-odoo) as written by container2backup.py.

Server values are read from ~/docker2update.yaml (database name, data directory of the
test container) and ~/container2backup.yaml (backup directory, live database name,
archive format). Every value can be overridden on the command line.

Run as root on the server:  python3 generate.py --out ~/playbooks
Needs odoodev >= 0.75.7 (temp_dir; with EBICS also server.uninstall).

Optional: modules the test instance gets on top after every restore. They are listed per
container in docker2update.yaml (install_modules: [eq_module_a, eq_module_b]) or given with
--install-modules a,b. With modules every restore playbook installs them (server.install,
odoodev >= 0.78.0); without, the playbooks are unchanged.

Optional: EBICS handling, only for a server that uses EBICS. With ebics: true on the test
container in docker2update.yaml, or --ebics, every restore playbook switches EBICS off before
Odoo starts and uninstalls the EBICS modules afterwards (server.uninstall). --no-ebics overrides
the YAML. Default: no EBICS steps.

Cron jobs: server.restore switches them off, but the module update of the rebuild (and an
install step) re-enables those whose cron XML is not noupdate. Every restore playbook therefore
switches all cron jobs off again after the rebuild, and after the install step if there is one.

Test settings (test-after-restore.sql): applied right after the restore, before the rebuild
starts Odoo on the copy - otherwise the copy would run with live's web.base.url and FastReport
server until the end of the playbook - and again at the end, because neutralize empties the
FastReport token. The file must therefore be safe to run twice.

New server: the first step (stop the test container) may fail because the container does not
exist yet; the playbook carries on and the rebuild creates it.
"""

import argparse
import os
import re
import sys

SCRIPT_VERSION = "1.7.0"
SCRIPT_DATE = "27.11.2026"

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
# SQL that only the test instance needs after every restore: its own web.base.url,
# its own FastReport server and token (eq_fr_core's neutralize empties the token),
# an admin login without 2FA. Server-only, root-only (0600) - it holds secrets and
# never goes into a playbook or a repository; odoodev reads it at run time.
AFTER_RESTORE_SQL = "/root/.config/odoodev/test-after-restore.sql"

# Only generated with ebics: true / --ebics.
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

# Mirrors odoodev's deactivate_cron sanitize (odoodev/core/database.py, deactivate_cronjobs):
# the same ir_cron statement, no exclusions. The module update of server.rebuild (-u all) and
# server.install re-activate cron jobs whose XML is not noupdate; they are due at once, would
# block the next module operation (Odoo refuses it while a cron holds ir_cron) and would run
# jobs such as report mails on a copy of live data. So the step is repeated after both.
CRON_OFF_SQL = "UPDATE ir_cron SET active = false;"
CRON_OFF_STEP = [
    '  - name: "Switch cron jobs off again (the module update re-enabled them)"',
    "    command: sql.execute",
    "    args:",
    "      target: test",
    "      statements:",
    f'        - "{CRON_OFF_SQL}"',
    "",
]

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
MODULE_RE = re.compile(r"^[a-z0-9_]+$")

# Minimum odoodev: temp_dir + server.uninstall (the latter only with EBICS, same version kept); with install_modules also server.install.
MIN_ODOODEV = "0.75.7"
MIN_ODOODEV_INSTALL = "0.78.0"


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


def parse_modules(text):
    """'a, b' -> ['a', 'b']; empty items are dropped."""
    return [part.strip() for part in str(text).split(",") if part.strip()]


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
        ebics = entry.get("ebics")
        if args.ebics is None and ebics is not None:
            if isinstance(ebics, bool):
                args.ebics = ebics
                if ebics:
                    found.append(f"EBICS steps enabled ({args.update_config})")
            else:
                print("Warning: ebics must be true or false — treated as false", file=sys.stderr)
        configured = entry.get("install_modules")
        if args.install_modules is None and configured:
            if isinstance(configured, list) and all(isinstance(name, str) for name in configured):
                args.install_modules = list(configured)
                found.append(f"modules to install {', '.join(configured)} ({args.update_config})")
            else:
                print("Warning: install_modules must be a list of module names — ignored", file=sys.stderr)

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
    args.install_modules = args.install_modules or []
    args.ebics = bool(args.ebics)
    return found


def header(state, label, version, filename, minimum=MIN_ODOODEV):
    return [
        f"# Test instance <- newest live backup, state '{state}'. Odoo {version}.",
        f"# Result: {label}.",
        f"# Generated by generate.py {SCRIPT_VERSION}. Needs odoodev >= {minimum}.",
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
    modules = getattr(args, "install_modules", None) or []
    ebics = getattr(args, "ebics", False)
    minimum = MIN_ODOODEV_INSTALL if modules else MIN_ODOODEV
    lines = header(state, label, args.version, filename, minimum) + targets(args)
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
        "  # on_error: continue - on a new server the test container does not exist yet;",
        "  # the rebuild creates it. A container that is still running is caught by",
        "  # server.restore, which refuses to drop a database under a running Odoo.",
        f'  - name: "Stop {args.test_container}"',
        "    command: container.stop",
        "    args: { target: test, component: odoo }",
        "    on_error: continue",
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
    ]
    after_sql = getattr(args, "after_restore_sql", "") or ""
    if after_sql:
        lines += [
            "  # Before Odoo first starts on the copy: until here the database still holds",
            "  # live's settings, and the rebuild starts the container - with live's",
            "  # FastReport URL and token it would send reports to the live server. Applied",
            "  # again at the end, because neutralize empties the FastReport token.",
            '  - name: "Apply the settings of the test instance (before Odoo starts)"',
            "    command: sql.execute",
            "    args:",
            "      target: test",
            f"      file: {after_sql}",
            "",
        ]
    if ebics:
        lines += [
            '  - name: "Switch off EBICS (before Odoo starts)"',
            "    command: sql.execute",
            "    args:",
            "      target: test",
            "      statements:",
            f'        - "{EBICS_OFF_SQL}"',
            "",
        ]
    lines += [
        "  # update_docker_odoo.py (doup): builds the image, updates all modules on the",
        "  # restored database and starts the container. --type F forces the full update.",
        f'  - name: "Rebuild image, update all modules, start {args.test_container}"',
        "    command: server.rebuild",
        "    args:",
        "      target: test",
        '      extra_args: ["--type", "F"]',
        "",
    ]
    lines += CRON_OFF_STEP
    if ebics:
        lines += [
            "  # A no-op when the database has no EBICS.",
            '  - name: "Uninstall EBICS"',
            "    command: server.uninstall",
            "    args:",
            "      target: test",
            f"      modules: [{', '.join(EBICS_MODULES)}]",
            "",
        ]
    lines += [
        '  - name: "Neutralize (odoo-bin neutralize in the container)"',
        "    command: server.neutralize",
        "    args: { target: test }",
        "",
    ]
    if modules:
        lines += [
            '  - name: "Install additional modules"',
            "    command: server.install",
            "    args:",
            "      target: test",
            f"      modules: [{', '.join(modules)}]",
            "",
        ]
        lines += CRON_OFF_STEP
    if after_sql:
        lines += [
            "  # Last, so neutralize cannot undo it. Odoo caches configuration parameters,",
            "  # so the container restarts afterwards.",
            '  - name: "Apply the settings of the test instance"',
            "    command: sql.execute",
            "    args:",
            "      target: test",
            f"      file: {after_sql}",
            "",
            f'  - name: "Restart {args.test_container} with these settings"',
            "    command: container.stop",
            "    args: { target: test, component: odoo }",
            "",
            f'  - name: "Start {args.test_container}"',
            "    command: container.start",
            "    args: { target: test, component: odoo }",
            "",
        ]
    lines += [
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
    parser.add_argument(
        "--install-modules",
        type=parse_modules,
        help="Modules to install after every restore, comma-separated "
        "(default: install_modules of the test container in docker2update.yaml; empty = none)",
    )
    parser.add_argument(
        "--ebics",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Add the EBICS steps (switch off before Odoo starts, uninstall afterwards) to every restore "
        "playbook (default: ebics of the test container in docker2update.yaml, else off)",
    )
    parser.add_argument(
        "--safety-backup",
        action="store_true",
        help=f"Save the test instance to {SAFETY_DIR} before every restore and write wiederherstellen.yaml "
        "(default: off - a test instance is overwritten anyway)",
    )
    parser.add_argument(
        "--after-restore-sql",
        help=f"SQL file run before Odoo first starts on the copy and again after neutralizing, e.g. web.base.url, FastReport token, admin login "
        f"(default: {AFTER_RESTORE_SQL} if it exists; empty = none). Keep it mode 0600",
    )
    parser.add_argument("--update-config", default="~/docker2update.yaml")
    parser.add_argument("--backup-config", default="~/container2backup.yaml")
    parser.add_argument("--no-detect", action="store_true", help="Do not read the server's YAML files")
    args = parser.parse_args()

    if args.no_detect:
        args.update_config = args.backup_config = "/nonexistent"
    found = detect(args)
    if args.after_restore_sql is None:
        args.after_restore_sql = "" if args.no_detect or not os.path.isfile(AFTER_RESTORE_SQL) else AFTER_RESTORE_SQL
    if args.after_restore_sql:
        if not re.match(r"^[A-Za-z0-9_./~-]+$", args.after_restore_sql):
            parser.error(f"invalid path for --after-restore-sql: {args.after_restore_sql!r}")
        sql_path = os.path.expanduser(args.after_restore_sql)
        if not os.path.isfile(sql_path):
            parser.error(f"--after-restore-sql: {sql_path} does not exist")
        if os.stat(sql_path).st_mode & 0o077:
            print(f"Warning: {sql_path} is readable by others - it may hold passwords and tokens: chmod 600",
                  file=sys.stderr)

    for value in (args.test_container, args.test_db_container, args.live_container, args.test_db, args.live_db):
        if not NAME_RE.match(value):
            parser.error(f"invalid container or database name: {value!r}")
    for module in args.install_modules:
        if not MODULE_RE.match(module):
            parser.error(f"invalid module name: {module!r}")
    if not re.match(r"^[a-z0-9.]+$", args.backup_suffix):
        parser.error(f"invalid backup suffix: {args.backup_suffix!r}")

    # The timestamp spelled out, not "*": since 19.11.2026 the 14:00 run is
    # databases only and its archive ends in "_sql_only" - a "*" would make
    # that the newest backup and restore a test instance without filestore.
    live_pattern = (f"{args.live_db}_{args.live_container}_dockerbackup_"
                    f"????-??-??_??-??-??.{args.backup_suffix}")
    safety_pattern = f"{args.test_db}_{args.test_container}_prerestore_*.tar.zst"

    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)
    files = {}
    for state, (label, active) in STATES.items():
        files[f"{state}.yaml"] = render_restore(
            args, state, label, active, args.backup_dir, live_pattern, args.safety_backup
        )
    if args.safety_backup:
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
    if args.after_restore_sql:
        print(f"test settings: {args.after_restore_sql} is applied before {args.test_container} starts and again at the end, then it restarts")
    if args.install_modules:
        print(f"extra modules: {', '.join(args.install_modules)} (needs odoodev >= {MIN_ODOODEV_INSTALL})")
    if args.ebics:
        print("EBICS: steps included (switch off + uninstall)")
    else:
        print("EBICS: no steps (enable with ebics: true or --ebics)")
    if args.safety_backup:
        print(f"safety backup: on - every run first saves the test instance to {SAFETY_DIR} (never pruned)")
    else:
        print("safety backup: off - the test instance is overwritten without a copy (--safety-backup to keep one)")
        stale = os.path.join(out, "wiederherstellen.yaml")
        if os.path.exists(stale):
            print(f"note: {stale} is from an earlier run with --safety-backup; it is left alone")
    print(f"written: {len(files)} playbooks to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
