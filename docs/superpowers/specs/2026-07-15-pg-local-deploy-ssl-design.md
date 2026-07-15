# pg-local-deploy.sh — Optional Self-Signed SSL

**Date:** 15.07.2026 · **Script:** `scripts/pg-local-deploy.sh` (1.1.0 → 1.2.0)

## Problem

PostgreSQL containers deployed by `pg-local-deploy.sh` run with `ssl = off`. Odoo
connects with `db_sslmode = prefer`, so traffic on the Docker network is always
plaintext. Deployments should optionally offer TLS without breaking Ansible parity.

## Decision (approved)

Opt-in self-signed SSL, default **off** (`y/N`), keeping deploys identical to the
Ansible playbook unless explicitly enabled.

## Design

1. **Step 2 (parameters):** new interactive prompt after the host-port question:
   `SSL mit Self-Signed-Zertifikat aktivieren? (y/N)` → `pg_ssl` = `yes`/`no`.
2. **Step 4 (conf extraction):** when `pg_ssl=yes`, append a clearly marked
   override block to `postgresql.conf.src`:
   ```
   # --- pg-local-deploy override: self-signed SSL ---
   ssl = on
   ```
   The four embedded conf profiles stay untouched (1:1 Ansible copies).
   PostgreSQL resolves `ssl_cert_file`/`ssl_key_file` to `server.crt`/`server.key`
   in PGDATA by default — no explicit paths needed.
3. **Step 8 (stop → copy → start):** in the existing root-container `docker run`
   that installs `postgresql.conf`, additionally (only when `pg_ssl=yes`):
   - if `/data/server.key` does **not** exist:
     `openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -keyout /data/server.key -out /data/server.crt -subj "/CN=$pg_name"`
   - `chown 999:999`, `chmod 600 server.key`, `chmod 644 server.crt`
   - existing certificates are kept (idempotent re-runs).
   The postgres image ships openssl → no host dependency, script stays self-contained.
4. **Step 9 (banner):** report SSL status (enabled + cert path / disabled). When
   enabled, note that Odoo `db_sslmode = prefer` picks up TLS automatically and
   that the certificate is self-signed (no verification via `verify-ca/full`).
5. **Header:** version 1.2.0, date 15.07.2026, feature mentioned in the header
   comment's input list.

## Error handling

- Certificate generation runs inside the same guarded `docker run` as the conf
  copy: on failure the script restarts the container without the new conf and
  exits non-zero (existing behavior, unchanged).
- No changes to compose file, volumes, or network.

## Out of scope

- Ansible playbook / embedded conf profiles (stay 1:1).
- CA-signed certificates, cert rotation, `verify-ca`/`verify-full` client modes.

## Verification

- Deploy without SSL → behavior byte-identical to 1.1.0 (conf has no override block).
- Deploy with SSL → `psql "sslmode=require"` connects; `SHOW ssl;` returns `on`;
  `server.key` in PGDATA is 0600 999:999.
- Re-run deploy with SSL → certificate not regenerated.
- `bash -n scripts/pg-local-deploy.sh` passes.
