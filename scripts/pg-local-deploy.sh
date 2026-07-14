#!/usr/bin/env bash
#
# pg-local-deploy.sh — interaktives On-Premise-Deploy für PostgreSQL-Docker.
#
# Version: 1.0.0 — 14.07.2026
#
# Spiegelt das Ansible-Playbook
#   semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml
# auf der lokalen Maschine, damit PostgreSQL-Instanzen auch ohne
# Semaphore/Ansible-Setup (Kunden-On-Premise) ausgerollt werden können.
#
# Eingaben (interaktiv): Container-Name, Basis-Verzeichnis, DB-User/-Name,
# Passwort (Pflicht), PostgreSQL-Version, Conf-Profil (2cpu4gb/2cpu8gb/
# 4cpu16gb/8cpu32gb), optionaler Host-Port.
#
# Sicherheits-Hygiene: KEINE Secrets im Skript hinterlegt — das DB-Passwort
# wird zwingend interaktiv (silent, mit Wiederholung) abgefragt.
#
# Volume-Layout identisch zur Ansible-Produktion:
#   {base}/{name}          → PGDATA (999:999, 0700)
#   {base}/{name}-deploy/  → docker-compose.yml + postgresql.conf.src
#
# Die vier PostgreSQL-Conf-Profile sind 1:1 als Heredocs eingebettet
# (Quelle: semaphore/playbooks/odoo/pg/postgresql_*.conf) — das Skript ist
# damit self-contained und kann als einzelne Datei mitgenommen werden.
#
# Ablauf wie im Playbook: Container starten (initdb) → pg_isready → stoppen →
# Profil-Conf als PGDATA/postgresql.conf einspielen → starten → verifizieren.

set -o pipefail

# ── Fixe Konfiguration ───────────────────────────────────────────────────────
CONTAINER_PORT=5432
DEFAULT_PG_USER="ownerp"
DEFAULT_PG_DB="postgres"

# ── Farben (nur bei Terminal) ────────────────────────────────────────────────
if [ -t 1 ]; then
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_CYAN=$'\033[36m'
    C_GRAY=$'\033[90m'
    C_RESET=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_CYAN=""; C_GRAY=""; C_RESET=""
fi

# ── Helpers ──────────────────────────────────────────────────────────────────
_err()  { printf '%s✗ %s%s\n' "$C_RED"   "$*" "$C_RESET" >&2; }
_ok()   { printf '%s✓ %s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
_info() { printf '%s➜ %s%s\n' "$C_CYAN"  "$*" "$C_RESET"; }
_hr()   { printf '%s────────────────────────────────────────────────%s\n' "$C_GRAY" "$C_RESET"; }

# Doppelte Passwort-Eingabe mit Verifikation — Pflichtfeld, KEIN Default
# (keine Secrets im Skript). Gibt das Passwort auf stdout aus. Prompts gehen
# nach stderr (read -p), damit command substitution nur den Wert einfängt.
_read_pwd_twice() {
    local label="$1"
    local pwd1 pwd2
    while true; do
        read -rsp "  $label: " pwd1
        echo >&2
        if [ -z "$pwd1" ]; then
            _err "$label ist Pflicht — bitte eingeben."
            continue
        fi
        read -rsp "  $label (Wiederholung): " pwd2
        echo >&2
        if [ "$pwd1" = "$pwd2" ]; then
            echo "$pwd1"
            return 0
        fi
        _err "Eingaben verschieden — bitte erneut."
    done
}

main() {

# ── Step 1: Pre-Flight Checks ────────────────────────────────────────────────
_info "Step 1: Pre-Flight Checks"
if ! command -v docker >/dev/null 2>&1; then
    _err "Fehlende Abhängigkeit: docker"
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    _err "Docker-Daemon nicht erreichbar — läuft Docker? Rechte vorhanden (docker-Gruppe)?"
    exit 1
fi
# Compose-Verfügbarkeit ermitteln (v2-Plugin bevorzugt, v1-Binary als Fallback)
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    DC=""
fi
if [ -n "$DC" ]; then
    _ok "Alle Tools vorhanden (docker, $DC)"
else
    _ok "docker vorhanden"
    _info "Hinweis: kein docker compose verfügbar — Start erfolgt via 'docker run' (Compose-File wird trotzdem hinterlegt)."
fi

# ── Step 2: Interaktive Parameter ────────────────────────────────────────────
_hr
_info "Step 2: Parameter"

read -rp "  Container-Name [live-db]: " pg_name
[ -z "$pg_name" ] && pg_name="live-db"
if ! [[ "$pg_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
    _err "Ungültiger Container-Name: $pg_name"
    exit 1
fi

read -rp "  Basis-Verzeichnis [/opt/postgresql]: " pg_basedir
[ -z "$pg_basedir" ] && pg_basedir="/opt/postgresql"
# read expandiert '~' nicht — manuell auflösen.
case "$pg_basedir" in
    "~")   pg_basedir="$HOME" ;;
    "~/"*) pg_basedir="$HOME/${pg_basedir#\~/}" ;;
esac
# Docker-Volume-Mounts erfordern absolute Pfade — relative auflösen.
case "$pg_basedir" in
    /*) : ;;
    *)  pg_basedir="$PWD/$pg_basedir" ;;
esac

echo
read -rp "  DB-User [$DEFAULT_PG_USER]: " pg_user
[ -z "$pg_user" ] && pg_user="$DEFAULT_PG_USER"

read -rp "  DB-Name [$DEFAULT_PG_DB]: " pg_db
[ -z "$pg_db" ] && pg_db="$DEFAULT_PG_DB"

echo
echo "  Hinweis: POSTGRES_PASSWORD greift nur beim ERSTEN Start (initdb)."
echo "  Bei bestehendem Datenverzeichnis wird die Eingabe von PostgreSQL ignoriert."
pg_pass="$(_read_pwd_twice "DB-Passwort")"

echo
read -rp "  PostgreSQL-Version (z.B. 16.9): " pg_version
if [ -z "$pg_version" ]; then
    _err "PostgreSQL-Version ist Pflicht"
    exit 1
fi
if ! [[ "$pg_version" =~ ^[0-9]+(\.[0-9]+)*$ ]]; then
    _err "Ungültige Version: $pg_version (erwartet z.B. 16 oder 16.9)"
    exit 1
fi

echo
echo "  Conf-Profil (Spiegel der Ansible-Profile):"
echo "    1) 2cpu4gb   — 2 CPU,  4 GB RAM (kleine Systeme)"
echo "    2) 2cpu8gb   — 2 CPU,  8 GB RAM (Standard)"
echo "    3) 4cpu16gb  — 4 CPU, 16 GB RAM (Produktiv)"
echo "    4) 8cpu32gb  — 8 CPU, 32 GB RAM (High-Performance)"
read -rp "  Auswahl [2]: " conf_choice
[ -z "$conf_choice" ] && conf_choice="2"
case "$conf_choice" in
    1) pg_conf_version="2cpu4gb"  ; conf_func="_conf_2cpu4gb"  ;;
    2) pg_conf_version="2cpu8gb"  ; conf_func="_conf_2cpu8gb"  ;;
    3) pg_conf_version="4cpu16gb" ; conf_func="_conf_4cpu16gb" ;;
    4) pg_conf_version="8cpu32gb" ; conf_func="_conf_8cpu32gb" ;;
    *) _err "Ungültige Auswahl: $conf_choice"; exit 1 ;;
esac
_ok "Conf-Profil: $pg_conf_version"

echo
echo "  Optional — Host-Port für externen Zugriff (Publish auf 127.0.0.1)."
echo "  Enter = kein Port-Publishing (wie Ansible; Odoo-Container nutzt das Docker-Netz)."
read -rp "  Host-Port [keiner]: " pg_port
if [ -n "$pg_port" ]; then
    if ! [[ "$pg_port" =~ ^[0-9]+$ ]] || [ "$pg_port" -lt 1 ] || [ "$pg_port" -gt 65535 ]; then
        _err "Port muss numerisch (1-65535) sein: $pg_port"
        exit 1
    fi
fi

docker_network="${pg_name}-net"
host_pgdata="$pg_basedir/$pg_name"
deploy_dir="$pg_basedir/${pg_name}-deploy"
image="postgres:$pg_version"

# ── Step 3: Verzeichnisse ────────────────────────────────────────────────────
_hr
_info "Step 3: Verzeichnisse anlegen"

# Privileg-Strategie: erst ohne sudo versuchen; nur falls nötig + verfügbar
# auf sudo zurückfallen. Beschreibbares Unterverzeichnis = kein sudo nötig.
SUDO=""
if ! mkdir -p "$host_pgdata" "$deploy_dir" 2>/dev/null; then
    if command -v sudo >/dev/null 2>&1 && sudo mkdir -p "$host_pgdata" "$deploy_dir" 2>/dev/null; then
        SUDO="sudo"
        # Deploy-Verzeichnis gehört uns (Compose-File muss schreibbar sein);
        # PGDATA bleibt für 999:999 reserviert.
        $SUDO chown "$(id -u):$(id -g)" "$deploy_dir"
    else
        _err "Kann Verzeichnisse nicht anlegen: $host_pgdata"
        echo "    Kein Schreibrecht und kein (funktionierendes) sudo vorhanden."
        echo "    Erneut starten und einen beschreibbaren Pfad wählen (z.B. unter \$HOME)."
        exit 1
    fi
fi

# Re-Deploy-Erkennung: bestehendes PGDATA → initdb läuft nicht erneut,
# POSTGRES_USER/PASSWORD/DB greifen dann nicht.
existing_data=0
if [ -f "$host_pgdata/PG_VERSION" ] || [ -n "$(ls -A "$host_pgdata" 2>/dev/null)" ]; then
    existing_data=1
    _info "PGDATA enthält bereits Daten ($host_pgdata) — Re-Deploy."
    echo "    POSTGRES_USER/PASSWORD/DB werden von PostgreSQL ignoriert (kein initdb)."
fi

# Ownership/Mode wie Ansible (owner 999, group 999, mode 0700). chown braucht
# i.d.R. root — bei Fehlschlag nur Hinweis: der offizielle postgres-Entrypoint
# (läuft als root) korrigiert die Ownership beim Container-Start selbst.
if $SUDO chown 999:999 "$host_pgdata" 2>/dev/null || sudo -n chown 999:999 "$host_pgdata" 2>/dev/null; then
    $SUDO chmod 0700 "$host_pgdata" 2>/dev/null || sudo -n chmod 0700 "$host_pgdata" 2>/dev/null
    _ok "PGDATA vorbereitet: $host_pgdata (999:999, 0700)"
else
    chmod 0700 "$host_pgdata" 2>/dev/null
    _info "chown 999:999 nicht möglich (kein root/sudo) — der postgres-Entrypoint übernimmt das beim Start."
    _ok "PGDATA vorbereitet: $host_pgdata"
fi
_ok "Deploy-Verzeichnis bereit: $deploy_dir"

# ── Step 4: Conf-Profil extrahieren ──────────────────────────────────────────
_hr
_info "Step 4: Conf-Profil '$pg_conf_version' extrahieren"
conf_src="$deploy_dir/postgresql.conf.src"
if ! "$conf_func" > "$conf_src"; then
    _err "Konnte Conf-Profil nicht schreiben: $conf_src"
    exit 1
fi
chmod 0644 "$conf_src"
_ok "Profil geschrieben: $conf_src ($(wc -l < "$conf_src" | tr -d ' ') Zeilen)"

# ── Step 5: Image-Pull ───────────────────────────────────────────────────────
_hr
_info "Step 5: Image-Pull ($image)"
if ! docker pull "$image"; then
    _err "Image-Pull fehlgeschlagen: $image"
    echo "    Existiert der Tag? Verfügbare Tags: https://hub.docker.com/_/postgres/tags"
    echo "    Offline/Air-Gapped: Image vorab laden mit 'docker load -i postgres_$pg_version.tar'"
    exit 1
fi
_ok "Image vorhanden: $image"

# ── Step 6: docker-compose.yml generieren ────────────────────────────────────
_hr
_info "Step 6: docker-compose.yml generieren"
compose_file="$deploy_dir/docker-compose.yml"

# Optionaler ports-Block (nur bei gewähltem Host-Port)
ports_block=""
if [ -n "$pg_port" ]; then
    ports_block="    ports:
      - \"127.0.0.1:$pg_port:$CONTAINER_PORT\"
"
fi

# Compose-File schreiben — kapselt alle Run-Parameter, ermöglicht späteres
# start/stop/restart ohne dieses Skript. Enthält das DB-Passwort → 0600.
cat > "$compose_file" <<EOF
# Generiert von pg-local-deploy.sh — PostgreSQL Deployment "$pg_name".
# Spiegel von semaphore/playbooks/odoo/pg/pb_pg_docker_start.yaml.
# Steuerung (verzeichnis-unabhängig via -f):
#   docker compose -f "$compose_file" up -d     # starten / aktualisieren
#   docker compose -f "$compose_file" stop      # anhalten
#   docker compose -f "$compose_file" start     # wieder anlaufen
#   docker compose -f "$compose_file" down      # entfernen (PGDATA bleibt)
services:
  postgres:
    image: "$image"
    container_name: "$pg_name"
    restart: always
    shm_size: 1g
    environment:
      POSTGRES_USER: "$pg_user"
      POSTGRES_PASSWORD: "$pg_pass"
      POSTGRES_DB: "$pg_db"
    volumes:
      - "$host_pgdata:/var/lib/postgresql/data/"
${ports_block}    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $pg_user"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
networks:
  default:
    name: "$docker_network"
EOF
chmod 0600 "$compose_file"
_ok "Compose-File geschrieben: $compose_file (0600 — enthält Passwort)"

# ── Step 7: Idempotenz + Erststart ───────────────────────────────────────────
_hr
_info "Step 7: Container starten (initdb-Phase)"

# Idempotenz — Bestätigungs-Prompt bei existierendem Container
if docker ps -a --format '{{.Names}}' | grep -qx "$pg_name"; then
    read -rp "  Container '$pg_name' existiert bereits. Entfernen und neu deployen? (y/N) " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        [ -n "$DC" ] && $DC -f "$compose_file" down >/dev/null 2>&1
        docker stop "$pg_name" >/dev/null 2>&1
        docker rm "$pg_name" >/dev/null 2>&1
        _ok "Alter Container entfernt (PGDATA bleibt erhalten)"
    else
        _info "Abbruch — kein Re-Deploy. PGDATA + Compose-File bleiben erhalten."
        exit 0
    fi
fi

# Start — bevorzugt via Compose, sonst 'docker run' (Compose-File bleibt für später).
if [ -n "$DC" ]; then
    if ! $DC -f "$compose_file" up -d; then
        _err "$DC up fehlgeschlagen"
        exit 1
    fi
    _ok "Container via Compose gestartet ($DC)"
else
    # Netzwerk manuell anlegen (Compose übernimmt das sonst selbst)
    if ! docker network inspect "$docker_network" >/dev/null 2>&1; then
        if ! docker network create "$docker_network" >/dev/null; then
            _err "Konnte Docker-Netzwerk nicht anlegen: $docker_network"
            exit 1
        fi
    fi
    port_args=()
    [ -n "$pg_port" ] && port_args=(-p "127.0.0.1:$pg_port:$CONTAINER_PORT")
    if ! docker run -d \
        --name "$pg_name" \
        --restart always \
        --shm-size 1g \
        --network "$docker_network" \
        -e POSTGRES_USER="$pg_user" \
        -e POSTGRES_PASSWORD="$pg_pass" \
        -e POSTGRES_DB="$pg_db" \
        -v "$host_pgdata:/var/lib/postgresql/data/" \
        "${port_args[@]}" \
        --health-cmd "pg_isready -U $pg_user" \
        --health-interval 10s \
        --health-timeout 5s \
        --health-retries 5 \
        --health-start-period 30s \
        "$image" >/dev/null; then
        _err "docker run fehlgeschlagen"
        exit 1
    fi
    _ok "Container via docker run gestartet"
fi

# Warten auf pg_isready — wie Playbook (retries: 12, delay: 5)
_info "Warte auf PostgreSQL (pg_isready) …"
pg_ready=0
for i in $(seq 1 12); do
    if docker exec "$pg_name" pg_isready -U "$pg_user" >/dev/null 2>&1; then
        pg_ready=1
        break
    fi
    sleep 5
done
if [ "$pg_ready" -eq 0 ]; then
    _err "PostgreSQL nach 60s nicht bereit. Logs: docker logs $pg_name"
    exit 1
fi
_ok "PostgreSQL ist bereit (initdb abgeschlossen)"

# ── Step 8: Conf-Update-Zyklus (wie Playbook) ────────────────────────────────
_hr
_info "Step 8: Conf-Profil einspielen (Stop → Copy → Start)"

if [ -n "$DC" ]; then
    $DC -f "$compose_file" stop >/dev/null
else
    docker stop "$pg_name" >/dev/null
fi
_ok "Container gestoppt"

# Copy via Docker-root-Container — funktioniert ohne sudo, da PGDATA dem
# Container-User 999 gehört. Backup der bisherigen Conf wie Ansible (backup: yes).
ts="$(date +%s)"
if ! docker run --rm \
    -v "$host_pgdata:/data" \
    -v "$deploy_dir:/src:ro" \
    --entrypoint sh "$image" -c "
        if [ -f /data/postgresql.conf ]; then
            cp -a /data/postgresql.conf /data/postgresql.conf.bak-$ts
        fi
        cp /src/postgresql.conf.src /data/postgresql.conf &&
        chown 999:999 /data/postgresql.conf &&
        chmod 600 /data/postgresql.conf
    "; then
    _err "Conf-Copy fehlgeschlagen — Container wird ohne neues Profil wieder gestartet."
    if [ -n "$DC" ]; then $DC -f "$compose_file" start >/dev/null; else docker start "$pg_name" >/dev/null; fi
    exit 1
fi
_ok "postgresql.conf eingespielt (Profil $pg_conf_version, Backup: postgresql.conf.bak-$ts)"

if [ -n "$DC" ]; then
    $DC -f "$compose_file" start >/dev/null
else
    docker start "$pg_name" >/dev/null
fi
_ok "Container wieder gestartet"

# Warten auf pg_isready — wie Playbook (retries: 6, delay: 5)
_info "Warte auf PostgreSQL nach Conf-Update …"
pg_ready=0
for i in $(seq 1 6); do
    if docker exec "$pg_name" pg_isready -U "$pg_user" >/dev/null 2>&1; then
        pg_ready=1
        break
    fi
    sleep 5
done
if [ "$pg_ready" -eq 0 ]; then
    _err "PostgreSQL nach Conf-Update nicht bereit — Konfiguration prüfen!"
    echo "    Logs:     docker logs $pg_name"
    echo "    Rollback: Backup postgresql.conf.bak-$ts in $host_pgdata zurückkopieren"
    exit 1
fi
_ok "PostgreSQL läuft mit neuem Conf-Profil"

# ── Step 9: Verifikation + Abschluss-Banner ──────────────────────────────────
_hr
_info "Step 9: Verifikation"

server_version="$(docker exec "$pg_name" psql -U "$pg_user" -d "$pg_db" -tAc 'SELECT version();' 2>/dev/null)"
if [ -z "$server_version" ]; then
    _err "Smoke-Test fehlgeschlagen — psql SELECT version() lieferte nichts"
    exit 1
fi
_ok "Smoke-Test: $server_version"

shared_buffers="$(docker exec "$pg_name" psql -U "$pg_user" -d "$pg_db" -tAc 'SHOW shared_buffers;' 2>/dev/null)"
[ -n "$shared_buffers" ] && _ok "Conf aktiv: shared_buffers = $shared_buffers"

_hr
echo
_ok "PostgreSQL Deployment erfolgreich"
echo
echo "  Container:   $pg_name"
echo "  Image:       $image"
echo "  Netzwerk:    $docker_network"
echo "  PGDATA:      $host_pgdata"
echo "  Conf-Profil: $pg_conf_version"
echo "  Compose:     $compose_file"
if [ -n "$pg_port" ]; then
    echo "  Host-Port:   127.0.0.1:$pg_port → $CONTAINER_PORT"
else
    echo "  Host-Port:   keiner (Zugriff nur via Docker-Netz)"
fi
echo
echo "  Odoo-Container anbinden (DB-Host = '$pg_name', Port $CONTAINER_PORT):"
echo "    docker network connect $docker_network <odoo-container>"
echo
if [ -n "$DC" ]; then
    echo "  Logs anzeigen:   $DC -f \"$compose_file\" logs -f"
    echo "  Stoppen:         $DC -f \"$compose_file\" stop"
    echo "  Starten:         $DC -f \"$compose_file\" start"
    echo "  Neu starten:     $DC -f \"$compose_file\" restart"
    echo "  Entfernen:       $DC -f \"$compose_file\" down   (PGDATA bleibt)"
else
    echo "  Logs anzeigen:   docker logs -f $pg_name"
    echo "  Stoppen:         docker stop $pg_name"
    echo "  Starten:         docker start $pg_name"
    echo "  Neu starten:     docker restart $pg_name"
    echo "  Entfernen:       docker rm -f $pg_name   (PGDATA bleibt)"
fi
echo

}

# ── Eingebettete PostgreSQL-Conf-Profile ─────────────────────────────────────
# 1:1-Kopien aus semaphore/playbooks/odoo/pg/postgresql_*.conf.
# Quoted Heredocs — keinerlei Shell-Expansion der Conf-Inhalte.

_conf_2cpu4gb() {
cat <<'EOF_CONF_2cpu4gb'
# PostgreSQL 16 Configuration File - Optimized for Odoo
# Hardware: 2 CPU cores, 4GB RAM, SSD storage
# Target: Odoo ERP workloads with light to moderate concurrent users
# Generated for PostgreSQL 16.x with modern optimizations

#------------------------------------------------------------------------------
# CONNECTIONS AND AUTHENTICATION
#------------------------------------------------------------------------------

listen_addresses = '*'
max_connections = 100                   # Reduced for 4GB RAM system
superuser_reserved_connections = 3

# TCP Keepalive settings for better connection management
tcp_keepalives_idle = 600              # 10 minutes
tcp_keepalives_interval = 30           # 30 seconds
tcp_keepalives_count = 3

#------------------------------------------------------------------------------
# RESOURCE USAGE (MEMORY)
#------------------------------------------------------------------------------

# Memory allocation optimized for 4GB system
shared_buffers = 1GB                   # 25% of total RAM
work_mem = 4MB                         # Reduced for lower memory system
maintenance_work_mem = 512MB           # Half of 8GB config
effective_cache_size = 3GB             # 75% of total RAM

# New PostgreSQL 16 memory settings
hash_mem_multiplier = 2.0              # Allow larger hash tables
huge_pages = try                       # Enable if system supports it

# Temp file management
temp_file_limit = 1GB                  # Limit temp files to prevent disk issues

#------------------------------------------------------------------------------
# QUERY TUNING - OPTIMIZED FOR ODOO
#------------------------------------------------------------------------------

# Cost parameters optimized for SSD and Odoo workloads
random_page_cost = 1.1                 # Low value for SSD storage
seq_page_cost = 1.0
cpu_tuple_cost = 0.01
cpu_index_tuple_cost = 0.005
cpu_operator_cost = 0.0025

# Parallel query settings (PostgreSQL 16 improvements)
max_parallel_workers_per_gather = 2    # Use both CPU cores
max_parallel_workers = 4               # Allow more parallel workers
max_parallel_maintenance_workers = 2    # For VACUUM, CREATE INDEX
parallel_leader_participation = on

# Statistics for better query planning
default_statistics_target = 150        # Increased from 100 for better statistics
constraint_exclusion = partition       # Better for partitioned tables

# JIT compilation settings (PostgreSQL 16 improvements)
jit = on
jit_above_cost = 100000                # Enable JIT for expensive queries
jit_inline_above_cost = 500000
jit_optimize_above_cost = 500000

#------------------------------------------------------------------------------
# WAL AND CHECKPOINTS
#------------------------------------------------------------------------------

# WAL configuration for performance and reliability
wal_level = replica                     # Enable replication capability
wal_compression = on                    # Compress WAL (PostgreSQL 16 improvement)
wal_buffers = 16MB                     # Reduced for 4GB system
wal_writer_delay = 200ms
wal_writer_flush_after = 1MB

# Checkpoint settings for SSD and 4GB RAM
checkpoint_timeout = 10min             # Longer interval for better performance
checkpoint_completion_target = 0.9
checkpoint_flush_after = 0             # Disable for SSDs
max_wal_size = 2GB                     # Reduced for smaller system
min_wal_size = 512MB

# Recovery prefetching (PostgreSQL 16 feature)
recovery_prefetch = on                  # Improve recovery performance
wal_decode_buffer_size = 512kB

#------------------------------------------------------------------------------
# I/O AND CONCURRENCY
#------------------------------------------------------------------------------

# SSD optimizations
effective_io_concurrency = 300         # Higher for NVMe SSDs
maintenance_io_concurrency = 10        # For maintenance operations
backend_flush_after = 0                # Disable for SSDs

# Background writer settings
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0
bgwriter_flush_after = 0               # Disable for SSDs

#------------------------------------------------------------------------------
# AUTOVACUUM - TUNED FOR ODOO
#------------------------------------------------------------------------------

autovacuum = on
autovacuum_max_workers = 2              # Reduced for 4GB system
autovacuum_naptime = 30s                # More frequent runs for Odoo's write patterns

# Vacuum thresholds optimized for Odoo tables
autovacuum_vacuum_threshold = 100       # Increased base threshold
autovacuum_vacuum_scale_factor = 0.15   # Reduced scale factor for frequent updates
autovacuum_vacuum_insert_threshold = 1000
autovacuum_vacuum_insert_scale_factor = 0.2

# Analyze thresholds
autovacuum_analyze_threshold = 100
autovacuum_analyze_scale_factor = 0.05  # More frequent analyze for better stats

# Vacuum cost settings (allow more aggressive cleanup)
autovacuum_vacuum_cost_delay = 10ms     # Reduced delay
autovacuum_vacuum_cost_limit = 400      # Increased limit

# Freeze settings
autovacuum_freeze_max_age = 200000000
autovacuum_multixact_freeze_max_age = 400000000

#------------------------------------------------------------------------------
# LOGGING - PRODUCTION OPTIMIZED
#------------------------------------------------------------------------------

# Minimal logging for production performance
logging_collector = on
log_destination = 'stderr'
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_truncate_on_rotation = off

# Log only important events
log_min_messages = warning
log_min_error_statement = error
log_min_duration_statement = 5000      # Log queries > 5 seconds
log_checkpoints = on                   # Monitor checkpoint performance
log_connections = off                  # Disable for performance
log_disconnections = off
log_lock_waits = on                    # Important for Odoo deadlock detection
log_temp_files = 10MB                  # Log large temp files

# Enhanced log format for troubleshooting
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_timezone = 'UTC'

#------------------------------------------------------------------------------
# STATISTICS AND MONITORING
#------------------------------------------------------------------------------

# Query monitoring
track_activities = on
track_counts = on
track_io_timing = on                   # Enable I/O timing statistics
track_wal_io_timing = on               # PostgreSQL 16 feature
track_functions = pl                   # Track PL/pgSQL functions

# Query ID tracking for pg_stat_statements
compute_query_id = on

#------------------------------------------------------------------------------
# ODOO-SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Shared library preloading for extensions commonly used with Odoo
shared_preload_libraries = 'pg_stat_statements'

# Lock management - important for Odoo's concurrent operations
deadlock_timeout = 1s
max_locks_per_transaction = 128        # Increased for complex Odoo transactions

# Statement timeout to prevent runaway queries
statement_timeout = 30min             # 30 minutes max query time
lock_timeout = 30s                    # Prevent long lock waits
idle_in_transaction_session_timeout = 10min

# Memory settings for large Odoo operations
temp_buffers = 16MB                   # Reduced for 4GB system

#------------------------------------------------------------------------------
# LOCALE AND FORMATTING
#------------------------------------------------------------------------------

datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'en_US.utf8'
lc_monetary = 'en_US.utf8'
lc_numeric = 'en_US.utf8'
lc_time = 'en_US.utf8'
default_text_search_config = 'pg_catalog.english'

#------------------------------------------------------------------------------
# REPLICATION READINESS
#------------------------------------------------------------------------------

# Basic replication settings (ready for future use)
max_wal_senders = 3
max_replication_slots = 3
wal_keep_size = 512MB                  # Reduced for 4GB system

#------------------------------------------------------------------------------
# POSTGRESQL 16 SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Enhanced monitoring
log_startup_progress_interval = 10s    # Monitor long startup operations

# Improved vacuum settings
vacuum_cost_delay = 0                  # Disable vacuum delays for SSDs
vacuum_cost_page_hit = 1
vacuum_cost_page_miss = 2
vacuum_cost_page_dirty = 20
vacuum_cost_limit = 200

# I/O concurrency is already configured above with:
# effective_io_concurrency = 300 (for regular operations)
# maintenance_io_concurrency = 10 (for maintenance operations)

#------------------------------------------------------------------------------
# PERFORMANCE MONITORING QUERIES
#------------------------------------------------------------------------------

# Uncomment for performance analysis:
# log_statement = 'mod'                # Log all modifications
# log_duration = on                    # Log all query durations
# auto_explain.log_min_duration = 5000 # Auto-explain slow queries (requires extension)

#------------------------------------------------------------------------------
# NOTES FOR ODOO DEPLOYMENT
#------------------------------------------------------------------------------

# 1. Install pg_stat_statements extension:
#    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
#
# 2. Consider partitioning for large Odoo tables (account_move_line, etc.)
#
# 3. Monitor these key metrics:
#    - Checkpoint frequency and duration
#    - Lock waits and deadlocks
#    - Autovacuum effectiveness
#    - Query performance via pg_stat_statements
#
# 4. For high-load Odoo instances on 4GB systems, consider:
#    - Connection pooling (PgBouncer) - highly recommended
#    - Read replicas for reporting
#    - Archiving old data to reduce active dataset size
#
# 5. Regular maintenance commands:
#    - ANALYZE after data loads
#    - REINDEX CONCURRENTLY for heavily updated indexes
#    - Monitor table bloat and vacuum effectiveness
#
# 6. Memory optimization tips for 4GB systems:
#    - Use connection pooling to reduce memory per connection
#    - Monitor temp file creation and adjust work_mem if needed
#    - Consider reducing max_connections if memory pressure occurs
EOF_CONF_2cpu4gb
}

_conf_2cpu8gb() {
cat <<'EOF_CONF_2cpu8gb'
# PostgreSQL 16 Configuration File - Optimized for Odoo
# Hardware: 2 CPU cores, 8GB RAM, SSD storage
# Target: Odoo ERP workloads with moderate concurrent users
# Generated for PostgreSQL 16.x with modern optimizations

#------------------------------------------------------------------------------
# CONNECTIONS AND AUTHENTICATION
#------------------------------------------------------------------------------

listen_addresses = '*'
max_connections = 150                   # Reduced from 200 - better for Odoo with connection pooling
superuser_reserved_connections = 3

# TCP Keepalive settings for better connection management
tcp_keepalives_idle = 600              # 10 minutes
tcp_keepalives_interval = 30           # 30 seconds
tcp_keepalives_count = 3

#------------------------------------------------------------------------------
# RESOURCE USAGE (MEMORY)
#------------------------------------------------------------------------------

# Memory allocation optimized for 8GB system
shared_buffers = 2GB                   # 25% of total RAM
work_mem = 8MB                         # Increased from 5MB for complex Odoo queries
maintenance_work_mem = 1GB             # Doubled for better VACUUM/REINDEX performance
effective_cache_size = 6GB             # 75% of total RAM

# New PostgreSQL 16 memory settings
hash_mem_multiplier = 2.0              # Allow larger hash tables
huge_pages = try                       # Enable if system supports it

# Temp file management
temp_file_limit = 2GB                  # Limit temp files to prevent disk issues

#------------------------------------------------------------------------------
# QUERY TUNING - OPTIMIZED FOR ODOO
#------------------------------------------------------------------------------

# Cost parameters optimized for SSD and Odoo workloads
random_page_cost = 1.1                 # Low value for SSD storage
seq_page_cost = 1.0
cpu_tuple_cost = 0.01
cpu_index_tuple_cost = 0.005
cpu_operator_cost = 0.0025

# Parallel query settings (PostgreSQL 16 improvements)
max_parallel_workers_per_gather = 2    # Use both CPU cores
max_parallel_workers = 4               # Allow more parallel workers
max_parallel_maintenance_workers = 2    # For VACUUM, CREATE INDEX
parallel_leader_participation = on

# Statistics for better query planning
default_statistics_target = 150        # Increased from 100 for better statistics
constraint_exclusion = partition       # Better for partitioned tables

# JIT compilation settings (PostgreSQL 16 improvements)
jit = on
jit_above_cost = 100000                # Enable JIT for expensive queries
jit_inline_above_cost = 500000
jit_optimize_above_cost = 500000

#------------------------------------------------------------------------------
# WAL AND CHECKPOINTS
#------------------------------------------------------------------------------

# WAL configuration for performance and reliability
wal_level = replica                     # Enable replication capability
wal_compression = on                    # Compress WAL (PostgreSQL 16 improvement)
wal_buffers = 32MB                     # Increased for better WAL performance
wal_writer_delay = 200ms
wal_writer_flush_after = 1MB

# Checkpoint settings for SSD and 8GB RAM
checkpoint_timeout = 10min             # Longer interval for better performance
checkpoint_completion_target = 0.9
checkpoint_flush_after = 0             # Disable for SSDs
max_wal_size = 4GB                     # Allow larger WAL for bulk operations
min_wal_size = 1GB

# Recovery prefetching (PostgreSQL 16 feature)
recovery_prefetch = on                  # Improve recovery performance
wal_decode_buffer_size = 512kB

#------------------------------------------------------------------------------
# I/O AND CONCURRENCY
#------------------------------------------------------------------------------

# SSD optimizations
effective_io_concurrency = 300         # Higher for NVMe SSDs
maintenance_io_concurrency = 10        # For maintenance operations
backend_flush_after = 0                # Disable for SSDs

# Background writer settings
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0
bgwriter_flush_after = 0               # Disable for SSDs

#------------------------------------------------------------------------------
# AUTOVACUUM - TUNED FOR ODOO
#------------------------------------------------------------------------------

autovacuum = on
autovacuum_max_workers = 3              # Increased for better table maintenance
autovacuum_naptime = 30s                # More frequent runs for Odoo's write patterns

# Vacuum thresholds optimized for Odoo tables
autovacuum_vacuum_threshold = 100       # Increased base threshold
autovacuum_vacuum_scale_factor = 0.15   # Reduced scale factor for frequent updates
autovacuum_vacuum_insert_threshold = 1000
autovacuum_vacuum_insert_scale_factor = 0.2

# Analyze thresholds
autovacuum_analyze_threshold = 100
autovacuum_analyze_scale_factor = 0.05  # More frequent analyze for better stats

# Vacuum cost settings (allow more aggressive cleanup)
autovacuum_vacuum_cost_delay = 10ms     # Reduced delay
autovacuum_vacuum_cost_limit = 400      # Increased limit

# Freeze settings
autovacuum_freeze_max_age = 200000000
autovacuum_multixact_freeze_max_age = 400000000

#------------------------------------------------------------------------------
# LOGGING - PRODUCTION OPTIMIZED
#------------------------------------------------------------------------------

# Minimal logging for production performance
logging_collector = on
log_destination = 'stderr'
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_truncate_on_rotation = off

# Log only important events
log_min_messages = warning
log_min_error_statement = error
log_min_duration_statement = 5000      # Log queries > 5 seconds
log_checkpoints = on                   # Monitor checkpoint performance
log_connections = off                  # Disable for performance
log_disconnections = off
log_lock_waits = on                    # Important for Odoo deadlock detection
log_temp_files = 10MB                  # Log large temp files

# Enhanced log format for troubleshooting
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_timezone = 'UTC'

#------------------------------------------------------------------------------
# STATISTICS AND MONITORING
#------------------------------------------------------------------------------

# Query monitoring
track_activities = on
track_counts = on
track_io_timing = on                   # Enable I/O timing statistics
track_wal_io_timing = on               # PostgreSQL 16 feature
track_functions = pl                   # Track PL/pgSQL functions

# Query ID tracking for pg_stat_statements
compute_query_id = on

#------------------------------------------------------------------------------
# ODOO-SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Shared library preloading for extensions commonly used with Odoo
shared_preload_libraries = 'pg_stat_statements'

# Lock management - important for Odoo's concurrent operations
deadlock_timeout = 1s
max_locks_per_transaction = 128        # Increased for complex Odoo transactions

# Statement timeout to prevent runaway queries
statement_timeout = 30min             # 30 minutes max query time
lock_timeout = 30s                    # Prevent long lock waits
idle_in_transaction_session_timeout = 10min

# Memory settings for large Odoo operations
temp_buffers = 32MB                   # Increased for complex queries

#------------------------------------------------------------------------------
# LOCALE AND FORMATTING
#------------------------------------------------------------------------------

datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'en_US.utf8'
lc_monetary = 'en_US.utf8'
lc_numeric = 'en_US.utf8'
lc_time = 'en_US.utf8'
default_text_search_config = 'pg_catalog.english'

#------------------------------------------------------------------------------
# REPLICATION READINESS
#------------------------------------------------------------------------------

# Basic replication settings (ready for future use)
max_wal_senders = 3
max_replication_slots = 3
wal_keep_size = 1GB

#------------------------------------------------------------------------------
# POSTGRESQL 16 SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Enhanced monitoring
log_startup_progress_interval = 10s    # Monitor long startup operations

# Improved vacuum settings
vacuum_cost_delay = 0                  # Disable vacuum delays for SSDs
vacuum_cost_page_hit = 1
vacuum_cost_page_miss = 2
vacuum_cost_page_dirty = 20
vacuum_cost_limit = 200

# I/O concurrency is already configured above with:
# effective_io_concurrency = 300 (for regular operations)
# maintenance_io_concurrency = 10 (for maintenance operations)

#------------------------------------------------------------------------------
# PERFORMANCE MONITORING QUERIES
#------------------------------------------------------------------------------

# Uncomment for performance analysis:
# log_statement = 'mod'                # Log all modifications
# log_duration = on                    # Log all query durations
# auto_explain.log_min_duration = 5000 # Auto-explain slow queries (requires extension)

#------------------------------------------------------------------------------
# NOTES FOR ODOO DEPLOYMENT
#------------------------------------------------------------------------------

# 1. Install pg_stat_statements extension:
#    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
#
# 2. Consider partitioning for large Odoo tables (account_move_line, etc.)
#
# 3. Monitor these key metrics:
#    - Checkpoint frequency and duration
#    - Lock waits and deadlocks
#    - Autovacuum effectiveness
#    - Query performance via pg_stat_statements
#
# 4. For high-load Odoo instances, consider:
#    - Connection pooling (PgBouncer)
#    - Read replicas for reporting
#    - Table partitioning for historical data
#
# 5. Regular maintenance commands:
#    - ANALYZE after data loads
#    - REINDEX CONCURRENTLY for heavily updated indexes
#    - Monitor table bloat and vacuum effectiveness
EOF_CONF_2cpu8gb
}

_conf_4cpu16gb() {
cat <<'EOF_CONF_4cpu16gb'
# PostgreSQL 16 Configuration File - Optimized for Odoo
# Hardware: 4 CPU cores, 16GB RAM, SSD storage
# Target: Odoo ERP workloads with high concurrent users
# Generated for PostgreSQL 16.x with modern optimizations

#------------------------------------------------------------------------------
# CONNECTIONS AND AUTHENTICATION
#------------------------------------------------------------------------------

listen_addresses = '*'
max_connections = 200                   # Standard for 16GB system
superuser_reserved_connections = 3

# TCP Keepalive settings for better connection management
tcp_keepalives_idle = 600              # 10 minutes
tcp_keepalives_interval = 30           # 30 seconds
tcp_keepalives_count = 3

#------------------------------------------------------------------------------
# RESOURCE USAGE (MEMORY)
#------------------------------------------------------------------------------

# Memory allocation optimized for 16GB system
shared_buffers = 4GB                   # 25% of total RAM
work_mem = 16MB                        # Increased for complex queries
maintenance_work_mem = 2GB             # For VACUUM, CREATE INDEX
effective_cache_size = 12GB            # 75% of total RAM

# New PostgreSQL 16 memory settings
hash_mem_multiplier = 2.0              # Allow larger hash tables
huge_pages = try                       # Enable if system supports it

# Temp file management
temp_file_limit = 4GB                  # Limit temp files to prevent disk issues

#------------------------------------------------------------------------------
# QUERY TUNING - OPTIMIZED FOR ODOO
#------------------------------------------------------------------------------

# Cost parameters optimized for SSD and Odoo workloads
random_page_cost = 1.1                 # Low value for SSD storage
seq_page_cost = 1.0
cpu_tuple_cost = 0.01
cpu_index_tuple_cost = 0.005
cpu_operator_cost = 0.0025

# Parallel query settings (PostgreSQL 16 improvements)
max_parallel_workers_per_gather = 4    # Use all CPU cores
max_parallel_workers = 8               # Double the CPU count
max_parallel_maintenance_workers = 4    # For VACUUM, CREATE INDEX
parallel_leader_participation = on

# Statistics for better query planning
default_statistics_target = 150        # Increased from 100 for better statistics
constraint_exclusion = partition       # Better for partitioned tables

# JIT compilation settings (PostgreSQL 16 improvements)
jit = on
jit_above_cost = 100000                # Enable JIT for expensive queries
jit_inline_above_cost = 500000
jit_optimize_above_cost = 500000

#------------------------------------------------------------------------------
# WAL AND CHECKPOINTS
#------------------------------------------------------------------------------

# WAL configuration for performance and reliability
wal_level = replica                     # Enable replication capability
wal_compression = on                    # Compress WAL (PostgreSQL 16 improvement)
wal_buffers = 64MB                     # Increased for better WAL performance
wal_writer_delay = 200ms
wal_writer_flush_after = 1MB

# Checkpoint settings for SSD and 16GB RAM
checkpoint_timeout = 15min             # Longer interval for better performance
checkpoint_completion_target = 0.9
checkpoint_flush_after = 0             # Disable for SSDs
max_wal_size = 8GB                     # Allow larger WAL for bulk operations
min_wal_size = 2GB

# Recovery prefetching (PostgreSQL 16 feature)
recovery_prefetch = on                  # Improve recovery performance
wal_decode_buffer_size = 512kB

#------------------------------------------------------------------------------
# I/O AND CONCURRENCY
#------------------------------------------------------------------------------

# SSD optimizations
effective_io_concurrency = 300         # Higher for NVMe SSDs
maintenance_io_concurrency = 10        # For maintenance operations
backend_flush_after = 0                # Disable for SSDs

# Background writer settings
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0
bgwriter_flush_after = 0               # Disable for SSDs

#------------------------------------------------------------------------------
# AUTOVACUUM - TUNED FOR ODOO
#------------------------------------------------------------------------------

autovacuum = on
autovacuum_max_workers = 4              # Increased for better table maintenance
autovacuum_naptime = 30s                # More frequent runs for Odoo's write patterns

# Vacuum thresholds optimized for Odoo tables
autovacuum_vacuum_threshold = 100       # Increased base threshold
autovacuum_vacuum_scale_factor = 0.15   # Reduced scale factor for frequent updates
autovacuum_vacuum_insert_threshold = 1000
autovacuum_vacuum_insert_scale_factor = 0.2

# Analyze thresholds
autovacuum_analyze_threshold = 100
autovacuum_analyze_scale_factor = 0.05  # More frequent analyze for better stats

# Vacuum cost settings (allow more aggressive cleanup)
autovacuum_vacuum_cost_delay = 5ms      # Very low delay for powerful system
autovacuum_vacuum_cost_limit = 800      # Increased limit for faster vacuum

# Freeze settings
autovacuum_freeze_max_age = 200000000
autovacuum_multixact_freeze_max_age = 400000000

#------------------------------------------------------------------------------
# LOGGING - PRODUCTION OPTIMIZED
#------------------------------------------------------------------------------

# Minimal logging for production performance
logging_collector = on
log_destination = 'stderr'
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 200MB              # Increased for busier system
log_truncate_on_rotation = off

# Log only important events
log_min_messages = warning
log_min_error_statement = error
log_min_duration_statement = 3000      # Log queries > 3 seconds
log_checkpoints = on                   # Monitor checkpoint performance
log_connections = off                  # Disable for performance
log_disconnections = off
log_lock_waits = on                    # Important for Odoo deadlock detection
log_temp_files = 10MB                  # Log large temp files

# Enhanced log format for troubleshooting
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_timezone = 'UTC'

#------------------------------------------------------------------------------
# STATISTICS AND MONITORING
#------------------------------------------------------------------------------

# Query monitoring
track_activities = on
track_counts = on
track_io_timing = on                   # Enable I/O timing statistics
track_wal_io_timing = on               # PostgreSQL 16 feature
track_functions = pl                   # Track PL/pgSQL functions

# Query ID tracking for pg_stat_statements
compute_query_id = on

#------------------------------------------------------------------------------
# ODOO-SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Shared library preloading for extensions commonly used with Odoo
shared_preload_libraries = 'pg_stat_statements'

# Lock management - important for Odoo's concurrent operations
deadlock_timeout = 1s
max_locks_per_transaction = 256        # Increased for complex Odoo transactions

# Statement timeout to prevent runaway queries
statement_timeout = 30min             # 30 minutes max query time
lock_timeout = 30s                    # Prevent long lock waits
idle_in_transaction_session_timeout = 10min

# Memory settings for large Odoo operations
temp_buffers = 64MB                   # Increased for complex queries

#------------------------------------------------------------------------------
# LOCALE AND FORMATTING
#------------------------------------------------------------------------------

datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'en_US.utf8'
lc_monetary = 'en_US.utf8'
lc_numeric = 'en_US.utf8'
lc_time = 'en_US.utf8'
default_text_search_config = 'pg_catalog.english'

#------------------------------------------------------------------------------
# REPLICATION READINESS
#------------------------------------------------------------------------------

# Basic replication settings (ready for future use)
max_wal_senders = 5                    # Increased for replication
max_replication_slots = 5
wal_keep_size = 2GB

#------------------------------------------------------------------------------
# POSTGRESQL 16 SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Enhanced monitoring
log_startup_progress_interval = 10s    # Monitor long startup operations

# Improved vacuum settings
vacuum_cost_delay = 0                  # Disable vacuum delays for SSDs
vacuum_cost_page_hit = 1
vacuum_cost_page_miss = 2
vacuum_cost_page_dirty = 20
vacuum_cost_limit = 200

# Worker processes
max_worker_processes = 8               # Increased for 4 CPU cores

# I/O concurrency is already configured above with:
# effective_io_concurrency = 300 (for regular operations)
# maintenance_io_concurrency = 10 (for maintenance operations)

#------------------------------------------------------------------------------
# PERFORMANCE MONITORING QUERIES
#------------------------------------------------------------------------------

# Uncomment for performance analysis:
# log_statement = 'mod'                # Log all modifications
# log_duration = on                    # Log all query durations
# auto_explain.log_min_duration = 3000 # Auto-explain slow queries (requires extension)

#------------------------------------------------------------------------------
# NOTES FOR ODOO DEPLOYMENT
#------------------------------------------------------------------------------

# 1. Install pg_stat_statements extension:
#    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
#
# 2. Consider partitioning for large Odoo tables (account_move_line, etc.)
#
# 3. Monitor these key metrics:
#    - Checkpoint frequency and duration
#    - Lock waits and deadlocks
#    - Autovacuum effectiveness
#    - Query performance via pg_stat_statements
#
# 4. For high-load Odoo instances, consider:
#    - Connection pooling (PgBouncer) for > 100 active connections
#    - Read replicas for reporting
#    - Table partitioning for historical data
#
# 5. Regular maintenance commands:
#    - ANALYZE after data loads
#    - REINDEX CONCURRENTLY for heavily updated indexes
#    - Monitor table bloat and vacuum effectiveness
#
# 6. Performance optimization tips for 4CPU/16GB systems:
#    - Use parallel query execution for large reports
#    - Consider increasing work_mem for specific reporting queries
#    - Monitor parallel worker usage and adjust if needed
EOF_CONF_4cpu16gb
}

_conf_8cpu32gb() {
cat <<'EOF_CONF_8cpu32gb'
# PostgreSQL 16 Configuration File - Optimized for Odoo
# Hardware: 8 CPU cores, 32GB RAM, SSD storage
# Target: Odoo ERP workloads with maximum performance and high concurrent users
# Generated for PostgreSQL 16.x with modern optimizations

#------------------------------------------------------------------------------
# CONNECTIONS AND AUTHENTICATION
#------------------------------------------------------------------------------

listen_addresses = '*'
max_connections = 300                   # Increased for high-performance system
superuser_reserved_connections = 5

# TCP Keepalive settings for better connection management
tcp_keepalives_idle = 600              # 10 minutes
tcp_keepalives_interval = 30           # 30 seconds
tcp_keepalives_count = 3

#------------------------------------------------------------------------------
# RESOURCE USAGE (MEMORY)
#------------------------------------------------------------------------------

# Memory allocation optimized for 32GB system
shared_buffers = 8GB                   # 25% of total RAM
work_mem = 32MB                        # Increased for complex queries and many cores
maintenance_work_mem = 4GB             # Large for VACUUM, CREATE INDEX
effective_cache_size = 24GB            # 75% of total RAM

# New PostgreSQL 16 memory settings
hash_mem_multiplier = 2.0              # Allow larger hash tables
huge_pages = on                        # Enable for large memory system

# Temp file management
temp_file_limit = 8GB                  # Limit temp files to prevent disk issues

#------------------------------------------------------------------------------
# QUERY TUNING - OPTIMIZED FOR ODOO
#------------------------------------------------------------------------------

# Cost parameters optimized for SSD and Odoo workloads
random_page_cost = 1.1                 # Low value for SSD storage
seq_page_cost = 1.0
cpu_tuple_cost = 0.01
cpu_index_tuple_cost = 0.005
cpu_operator_cost = 0.0025

# Parallel query settings (PostgreSQL 16 improvements)
max_parallel_workers_per_gather = 8    # Use all CPU cores
max_parallel_workers = 16              # Double the CPU count for maximum parallelism
max_parallel_maintenance_workers = 8    # For VACUUM, CREATE INDEX
parallel_leader_participation = on

# Statistics for better query planning
default_statistics_target = 200        # High value for complex workloads
constraint_exclusion = partition       # Better for partitioned tables

# JIT compilation settings (PostgreSQL 16 improvements)
jit = on
jit_above_cost = 50000                 # More aggressive JIT compilation
jit_inline_above_cost = 500000
jit_optimize_above_cost = 500000

#------------------------------------------------------------------------------
# WAL AND CHECKPOINTS
#------------------------------------------------------------------------------

# WAL configuration for performance and reliability
wal_level = replica                     # Enable replication capability
wal_compression = on                    # Compress WAL (PostgreSQL 16 improvement)
wal_buffers = 128MB                    # High value for busy system
wal_writer_delay = 200ms
wal_writer_flush_after = 1MB

# Checkpoint settings for SSD and 32GB RAM
checkpoint_timeout = 20min             # Longer interval for maximum performance
checkpoint_completion_target = 0.9
checkpoint_flush_after = 0             # Disable for SSDs
max_wal_size = 16GB                    # Very large WAL for bulk operations
min_wal_size = 4GB

# Recovery prefetching (PostgreSQL 16 feature)
recovery_prefetch = on                  # Improve recovery performance
wal_decode_buffer_size = 512kB

#------------------------------------------------------------------------------
# I/O AND CONCURRENCY
#------------------------------------------------------------------------------

# SSD optimizations
effective_io_concurrency = 300         # Higher for NVMe SSDs
maintenance_io_concurrency = 20        # Increased for 8 CPU system
backend_flush_after = 0                # Disable for SSDs

# Background writer settings
bgwriter_delay = 200ms
bgwriter_lru_maxpages = 100
bgwriter_lru_multiplier = 2.0
bgwriter_flush_after = 0               # Disable for SSDs

#------------------------------------------------------------------------------
# AUTOVACUUM - TUNED FOR ODOO
#------------------------------------------------------------------------------

autovacuum = on
autovacuum_max_workers = 8              # Maximum for 8 CPU system
autovacuum_naptime = 20s                # Very frequent runs for high-load system

# Vacuum thresholds optimized for Odoo tables
autovacuum_vacuum_threshold = 100       # Increased base threshold
autovacuum_vacuum_scale_factor = 0.1    # More aggressive for high-performance
autovacuum_vacuum_insert_threshold = 1000
autovacuum_vacuum_insert_scale_factor = 0.2

# Analyze thresholds
autovacuum_analyze_threshold = 100
autovacuum_analyze_scale_factor = 0.05  # More frequent analyze for better stats

# Vacuum cost settings (allow very aggressive cleanup)
autovacuum_vacuum_cost_delay = 0        # No delay for maximum performance
autovacuum_vacuum_cost_limit = 2000     # Very high limit for powerful system

# Freeze settings
autovacuum_freeze_max_age = 200000000
autovacuum_multixact_freeze_max_age = 400000000

#------------------------------------------------------------------------------
# LOGGING - PRODUCTION OPTIMIZED
#------------------------------------------------------------------------------

# Minimal logging for production performance
logging_collector = on
log_destination = 'stderr'
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
log_rotation_age = 1d
log_rotation_size = 500MB              # Large files for busy system
log_truncate_on_rotation = off

# Log only important events
log_min_messages = warning
log_min_error_statement = error
log_min_duration_statement = 2000      # Log queries > 2 seconds
log_checkpoints = on                   # Monitor checkpoint performance
log_connections = off                  # Disable for performance
log_disconnections = off
log_lock_waits = on                    # Important for Odoo deadlock detection
log_temp_files = 10MB                  # Log large temp files

# Enhanced log format for troubleshooting
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_timezone = 'UTC'

#------------------------------------------------------------------------------
# STATISTICS AND MONITORING
#------------------------------------------------------------------------------

# Query monitoring
track_activities = on
track_counts = on
track_io_timing = on                   # Enable I/O timing statistics
track_wal_io_timing = on               # PostgreSQL 16 feature
track_functions = pl                   # Track PL/pgSQL functions

# Query ID tracking for pg_stat_statements
compute_query_id = on

#------------------------------------------------------------------------------
# ODOO-SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Shared library preloading for extensions commonly used with Odoo
shared_preload_libraries = 'pg_stat_statements'

# Lock management - important for Odoo's concurrent operations
deadlock_timeout = 1s
max_locks_per_transaction = 512        # Very high for complex Odoo transactions

# Statement timeout to prevent runaway queries
statement_timeout = 30min             # 30 minutes max query time
lock_timeout = 30s                    # Prevent long lock waits
idle_in_transaction_session_timeout = 10min

# Memory settings for large Odoo operations
temp_buffers = 128MB                  # Large for complex queries

#------------------------------------------------------------------------------
# LOCALE AND FORMATTING
#------------------------------------------------------------------------------

datestyle = 'iso, mdy'
timezone = 'UTC'
lc_messages = 'en_US.utf8'
lc_monetary = 'en_US.utf8'
lc_numeric = 'en_US.utf8'
lc_time = 'en_US.utf8'
default_text_search_config = 'pg_catalog.english'

#------------------------------------------------------------------------------
# REPLICATION READINESS
#------------------------------------------------------------------------------

# Basic replication settings (ready for future use)
max_wal_senders = 10                   # High for master/slave setups
max_replication_slots = 10
wal_keep_size = 4GB                    # Large for high-volume systems

#------------------------------------------------------------------------------
# POSTGRESQL 16 SPECIFIC OPTIMIZATIONS
#------------------------------------------------------------------------------

# Enhanced monitoring
log_startup_progress_interval = 10s    # Monitor long startup operations

# Improved vacuum settings
vacuum_cost_delay = 0                  # Disable vacuum delays for SSDs
vacuum_cost_page_hit = 1
vacuum_cost_page_miss = 2
vacuum_cost_page_dirty = 20
vacuum_cost_limit = 200

# Worker processes
max_worker_processes = 16              # Double the CPU count for maximum concurrency

# I/O concurrency is already configured above with:
# effective_io_concurrency = 300 (for regular operations)
# maintenance_io_concurrency = 20 (for maintenance operations)

#------------------------------------------------------------------------------
# ADVANCED PERFORMANCE SETTINGS
#------------------------------------------------------------------------------

# Aggressive settings for high-performance systems
wal_sync_method = fdatasync            # Most efficient on Linux
fsync = on                             # Keep enabled for data safety
synchronous_commit = on                # Keep enabled for consistency

# Memory optimization for large systems
min_dynamic_shared_memory = 100MB      # Pre-allocate shared memory

#------------------------------------------------------------------------------
# PERFORMANCE MONITORING QUERIES
#------------------------------------------------------------------------------

# Uncomment for performance analysis:
# log_statement = 'mod'                # Log all modifications
# log_duration = on                    # Log all query durations
# auto_explain.log_min_duration = 2000 # Auto-explain slow queries (requires extension)

#------------------------------------------------------------------------------
# NOTES FOR ODOO DEPLOYMENT
#------------------------------------------------------------------------------

# 1. Install pg_stat_statements extension:
#    CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
#
# 2. Consider partitioning for large Odoo tables (account_move_line, etc.)
#
# 3. Monitor these key metrics:
#    - Checkpoint frequency and duration
#    - Lock waits and deadlocks
#    - Autovacuum effectiveness
#    - Query performance via pg_stat_statements
#    - Parallel worker utilization
#
# 4. For enterprise Odoo instances, consider:
#    - Connection pooling (PgBouncer) for > 200 active connections
#    - Read replicas for reporting workloads
#    - Table partitioning for historical data
#    - Query optimization and index tuning
#
# 5. Regular maintenance commands:
#    - ANALYZE after data loads
#    - REINDEX CONCURRENTLY for heavily updated indexes
#    - Monitor table bloat and vacuum effectiveness
#
# 6. Performance optimization tips for 8CPU/32GB systems:
#    - Maximize parallel query execution for reports
#    - Use parallel maintenance operations for large datasets
#    - Monitor memory usage and adjust work_mem per query if needed
#    - Consider NUMA topology for very large systems
#    - Use pg_prewarm extension for frequently accessed data
#
# 7. High-availability considerations:
#    - Set up streaming replication
#    - Consider logical replication for selective data sync
#    - Implement proper backup and recovery strategies
#    - Monitor replication lag and synchronization
EOF_CONF_8cpu32gb
}

main "$@"
