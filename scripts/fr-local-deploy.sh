#!/usr/bin/env bash
#
# local-deploy.sh — interaktives lokales Deploy-Skript für fr-api.
#
# Bash-Portierung von local-deploy.fish. Verhalten 1:1 identisch.
#
# Spiegelt das Ansible-Playbook
#   semaphore/playbooks/fr/pb_fr_docker_start.yaml
# auf der lokalen Maschine, damit Deployment-Probleme reproduzierbar gemacht
# werden können, ohne Semaphore + Vault-Setup zu involvieren.
#
# Eingaben (interaktiv): Container-Name, Port, Image-Tag, Registry-Token,
# optional neue Admin-/Superuser-/JWT-Secrets.
#
# Volume-Layout identisch zur Produktion: /opt/fast-report/{name}/{Reports,
# ReportsData,Logfiles,settings}/
#
# Sicherheits-Hygiene: Passwort-/Token-Eingaben silent, bcrypt-Hash über stdin,
# Image-Inhalts-Audit nach Pull (siehe Step 9 — fängt versehentlich ins Image
# gewanderte appsettings.Development.json ab).
#
# Hinweis: erwartet GNU-Tools (md5sum, stat -c). Auf Linux-Deploy-Hosts gegeben;
# auf macOS sind 'md5sum'/'stat -c' nicht nativ vorhanden.

set -o pipefail

# ── Fixe Konfiguration ───────────────────────────────────────────────────────
REGISTRY_URL="registry.gitlab.ownerp.io"
REGISTRY_USER="release"
IMAGE_REPO="ci-myodoo/fr-api"
IMAGE_BASE="$REGISTRY_URL/$IMAGE_REPO"
GITLAB_JWT_AUTH="https://gitlab.ownerp.io/jwt/auth"
CONTAINER_PORT=5001

# Keine Baked-Default-Secrets im Skript (Security): fixe, über alle Deployments
# geteilte Hashes/Keys wären bei Repo-Zugriff kompromittiert. Fehlen Override
# UND bestehende appsettings.json, werden Admin-/Superuser-Passwort und JWT-Key
# pro Deployment ZUFÄLLIG erzeugt und am Ende einmalig angezeigt.
#
# Klartext der generierten Secrets für das Abschluss-Banner (leer = nichts
# generiert, weil Override oder bestehende Datei griff).
GENERATED_ADMIN_PWD=""
GENERATED_SUPERUSER_PWD=""
GENERATED_JWT_KEY=0

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

# HTTP-Client-Abstraktion — curl bevorzugt, wget als Fallback.
# HTTP_TOOL wird in Step 1 (Pre-Flight) gesetzt.
HTTP_TOOL=""

# Body auf stdout, exit != 0 bei HTTP-/Netzwerk-Fehler.
# Credentials werden NICHT als CLI-Argument übergeben (wären via ps aux /
# /proc/<pid>/cmdline sichtbar): curl liest sie via '-K -' (Config-Datei) von
# stdin, wget aus einer temporären WGETRC (0600), die sofort wieder gelöscht wird.
_http_get_basic() {  # url user pass
    local url="$1" user="$2" pass="$3"
    if [ "$HTTP_TOOL" = "curl" ]; then
        printf 'user = "%s:%s"\n' "$user" "$pass" | curl -fsS -K - "$url" 2>/dev/null
    else
        local rc rc_ret
        rc="$(mktemp)" || return 1
        chmod 600 "$rc"
        printf 'user=%s\npassword=%s\n' "$user" "$pass" > "$rc"
        WGETRC="$rc" wget -q -O - --auth-no-challenge "$url" 2>/dev/null
        rc_ret=$?
        rm -f "$rc"
        return $rc_ret
    fi
}

_http_get_bearer() {  # url jwt
    local url="$1" jwt="$2"
    if [ "$HTTP_TOOL" = "curl" ]; then
        curl -fsS -H "Authorization: Bearer $jwt" "$url" 2>/dev/null
    else
        wget -q -O - --header="Authorization: Bearer $jwt" "$url" 2>/dev/null
    fi
}

# Erreichbarkeits-/Smoke-Check — exit 0 nur bei HTTP 2xx.
_http_check() {  # url
    local url="$1"
    if [ "$HTTP_TOOL" = "curl" ]; then
        curl -fsS "$url" >/dev/null 2>&1
    else
        wget -q -O /dev/null "$url" 2>/dev/null
    fi
}

# Silent single-char read loop with '*' feedback per typed character.
# Echoes '*' to stderr (keeps command substitution clean), supports backspace.
_read_masked() {  # prompt -> value on stdout
    local prompt="$1" value="" ch
    printf '%s' "$prompt" >&2
    while IFS= read -rs -n1 ch; do
        [ -z "$ch" ] && break                      # Enter
        if [ "$ch" = $'\x7f' ] || [ "$ch" = $'\b' ]; then
            if [ -n "$value" ]; then
                value="${value%?}"
                printf '\b \b' >&2
            fi
        else
            value+="$ch"
            printf '*' >&2
        fi
    done
    echo >&2
    printf '%s' "$value"
}

# Doppelte Passwort-Eingabe mit Verifikation. Gibt Passwort (oder leer für
# "Default nehmen") auf stdout aus. Prompts + '*'-Feedback gehen nach stderr,
# damit command substitution nur den Wert einfängt.
_read_pwd_twice() {
    local label="$1"
    local pwd1 pwd2
    while true; do
        pwd1="$(_read_masked "  $label (Enter = Default behalten): ")"
        if [ -z "$pwd1" ]; then
            echo ""
            return 0
        fi
        pwd2="$(_read_masked "  $label (Wiederholung): ")"
        if [ "$pwd1" = "$pwd2" ]; then
            echo "$pwd1"
            return 0
        fi
        _err "Eingaben verschieden — bitte erneut."
    done
}

# Cryptographically secure random values via Python's secrets module (python3
# is a hard dependency checked in Step 1). Used for per-deployment fallback
# secrets instead of shared baked defaults.
_gen_secret()  { python3 -c 'import secrets; print(secrets.token_urlsafe(18))'; }
_gen_jwt_key() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }

# Ensures a Python interpreter with the bcrypt module and sets BCRYPT_PYTHON to
# its path. Order: 1) system python3 if it already has bcrypt, 2) a uv-managed
# venv (created + cached under $HOME/.cache/fr-local-deploy/venv) with bcrypt.
# Returns 1 (with guidance) if neither works. bcrypt is only needed to hash a
# new/generated superuser password, so this runs lazily (Step 5), not up front.
BCRYPT_PYTHON=""
_ensure_bcrypt_python() {
    [ -n "$BCRYPT_PYTHON" ] && return 0

    # 1) System python3 already carries bcrypt.
    if python3 -c 'import bcrypt' 2>/dev/null; then
        BCRYPT_PYTHON="python3"
        return 0
    fi

    # 2) Provision a dedicated uv venv with bcrypt (project standard: uv, not pip).
    if ! command -v uv >/dev/null 2>&1; then
        _err "Python-Modul 'bcrypt' fehlt und 'uv' ist nicht installiert."
        echo "    bcrypt wird für den Superuser-Hash benötigt. Installiere uv"
        echo "    (https://docs.astral.sh/uv/) — dann erzeugt dieses Skript das"
        echo "    venv automatisch. Alternativ manuell bereitstellen:"
        echo "      python3 -m venv ~/.frvenv && ~/.frvenv/bin/pip install bcrypt"
        echo "      danach: PATH=\"\$HOME/.frvenv/bin:\$PATH\" ./$(basename "$0")"
        return 1
    fi

    local venv_dir="${XDG_CACHE_HOME:-$HOME/.cache}/fr-local-deploy/venv"
    local venv_py="$venv_dir/bin/python"

    # Reuse a previously built venv if it still imports bcrypt.
    if [ -x "$venv_py" ] && "$venv_py" -c 'import bcrypt' 2>/dev/null; then
        BCRYPT_PYTHON="$venv_py"
        _info "bcrypt aus vorhandenem uv-venv ($venv_dir)"
        return 0
    fi

    _info "Erzeuge uv-venv für bcrypt ($venv_dir) …"
    if ! uv venv "$venv_dir" >/dev/null 2>&1; then
        _err "uv venv konnte nicht erstellt werden: $venv_dir"
        return 1
    fi
    if ! uv pip install --python "$venv_py" bcrypt >/dev/null 2>&1; then
        _err "bcrypt-Installation ins uv-venv fehlgeschlagen"
        return 1
    fi
    if ! "$venv_py" -c 'import bcrypt' 2>/dev/null; then
        _err "bcrypt im uv-venv nicht importierbar"
        return 1
    fi
    BCRYPT_PYTHON="$venv_py"
    _ok "bcrypt via uv-venv bereitgestellt ($venv_dir)"
    return 0
}

# ── JSON-Helfer (Ersatz für jq via Python-Standardlib) ───────────────────────
# Validiert eine JSON-Datei — exit 0 wenn parsebar.
_json_valid() {  # file
    python3 -c 'import sys, json; json.load(open(sys.argv[1], encoding="utf-8"))' "$1" 2>/dev/null
}

# Roher Wert eines Dotted-Path; leere Ausgabe wenn fehlt/null. Ersatz: jq -r "<path> // empty"
_json_get_raw() {  # file dotted.path
    python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, json
try:
    cur = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(0)
for k in sys.argv[2].split('.'):
    if isinstance(cur, dict) and k in cur:
        cur = cur[k]
    else:
        sys.exit(0)
if cur is None:
    sys.exit(0)
sys.stdout.write(cur if isinstance(cur, str) else json.dumps(cur, ensure_ascii=False))
PY
}

# Kompaktes JSON eines Dotted-Path; "null" wenn fehlt/null. Ersatz: jq -c "<path> // null"
_json_get_json() {  # file dotted.path
    python3 - "$1" "$2" <<'PY' 2>/dev/null
import sys, json
try:
    cur = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("null"); sys.exit(0)
for k in sys.argv[2].split('.'):
    if isinstance(cur, dict) and k in cur:
        cur = cur[k]
    else:
        print("null"); sys.exit(0)
print(json.dumps(cur, separators=(',', ':'), ensure_ascii=False))
PY
}

# ── Step 1: Pre-Flight Checks ────────────────────────────────────────────────
_info "Step 1: Pre-Flight Checks"
for cmd in docker python3 md5sum awk; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        _err "Fehlende Abhängigkeit: $cmd"
        exit 1
    fi
done
# HTTP-Client: curl bevorzugt, wget als Fallback (Build-VMs ohne curl).
if command -v curl >/dev/null 2>&1; then
    HTTP_TOOL="curl"
elif command -v wget >/dev/null 2>&1; then
    HTTP_TOOL="wget"
else
    _err "Weder 'curl' noch 'wget' vorhanden — ein HTTP-Client ist erforderlich"
    exit 1
fi
# bcrypt wird NUR für einen NEUEN/generierten Superuser-Hash benötigt. Nicht
# hier hart prüfen — bei Bedarf stellt _ensure_bcrypt_python() es via uv-venv
# bereit (Lazy, erst in Step 5).
_ok "Alle Tools vorhanden (docker, python3, $HTTP_TOOL, md5sum, awk)"
if ! python3 -c 'import bcrypt' 2>/dev/null; then
    if command -v uv >/dev/null 2>&1; then
        _info "Hinweis: 'bcrypt' fehlt im System-Python — wird bei Bedarf automatisch via uv-venv bereitgestellt."
    else
        _info "Hinweis: 'bcrypt' fehlt und 'uv' ist nicht installiert — nur nötig, wenn ein neues/generiertes Superuser-Passwort gehasht wird."
    fi
fi

# ── Step 2: Interaktive Parameter ────────────────────────────────────────────
_hr
_info "Step 2: Parameter"

read -rp "  Container-Name [fr-local]: " fr_name
[ -z "$fr_name" ] && fr_name="fr-local"
# Whitelist — fr_name landet in generierter Compose-YAML (container_name);
# Sonderzeichen (z.B. ") könnten die YAML-Struktur aufbrechen.
if ! [[ "$fr_name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
    _err "Ungültiger Container-Name: $fr_name"
    exit 1
fi

read -rp "  Basis-Verzeichnis für Volumes [/opt/fast-report]: " fr_basedir
[ -z "$fr_basedir" ] && fr_basedir="/opt/fast-report"
# read expandiert '~' nicht — manuell auflösen.
case "$fr_basedir" in
    "~")   fr_basedir="$HOME" ;;
    "~/"*) fr_basedir="$HOME/${fr_basedir#\~/}" ;;
esac
# Docker-Volume-Mounts erfordern absolute Pfade — relative auflösen.
case "$fr_basedir" in
    /*) : ;;
    *)  fr_basedir="$PWD/$fr_basedir" ;;
esac

read -rp "  Host-Port [8899]: " fr_port
[ -z "$fr_port" ] && fr_port="8899"
if ! [[ "$fr_port" =~ ^[0-9]+$ ]]; then
    _err "Port muss numerisch sein: $fr_port"
    exit 1
fi

read -rp "  Image-Tag (z.B. 2026.2.3-3.2.7): " fr_version
if [ -z "$fr_version" ]; then
    _err "Image-Tag ist Pflicht"
    exit 1
fi
# Whitelist — fr_version landet in generierter Compose-YAML (image-Tag) und in
# der Registry-URL. Docker-Tag-Grammatik: [a-zA-Z0-9_][a-zA-Z0-9_.-]*.
if ! [[ "$fr_version" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$ ]]; then
    _err "Ungültiger Image-Tag: $fr_version"
    exit 1
fi

registry_token="$(_read_masked "  GitLab Registry Token (User: $REGISTRY_USER): ")"
if [ -z "$registry_token" ]; then
    _err "Token ist Pflicht"
    exit 1
fi

echo
echo "  Optional — leere Eingabe übernimmt bestehende Werte aus appsettings.json"
echo "  bzw. fällt auf Baked Defaults zurück."
echo
fr_admin_password="$(_read_pwd_twice "Admin-Passwort")"
fr_superuser_password="$(_read_pwd_twice "Superuser-Passwort")"
fr_jwt_key="$(_read_pwd_twice "JWT-Key (raw String)")"

# ── Step 3: Container-Path-Auflösung ─────────────────────────────────────────
_hr
_info "Step 3: Container-Path-Auflösung"
# Logik 1:1 aus pb_fr_docker_start.yaml:9
if [[ "$fr_version" == *2026* ]]; then
    container_base_path="/app/wwwroot"
else
    container_base_path="/app/fr_api/wwwroot"
fi
_ok "Container Base-Path: $container_base_path"

# ── Step 4: Volume-Verzeichnisse ─────────────────────────────────────────────
_hr
_info "Step 4: Volume-Verzeichnisse"
host_base="$fr_basedir/$fr_name"

# Privileg-Strategie: erst ohne sudo versuchen; nur falls nötig + verfügbar
# auf sudo zurückfallen. Beschreibbares Unterverzeichnis = kein sudo nötig.
SUDO=""
if ! mkdir -p "$host_base" 2>/dev/null; then
    if command -v sudo >/dev/null 2>&1 && sudo mkdir -p "$host_base" 2>/dev/null; then
        SUDO="sudo"
    else
        _err "Kann Basis-Verzeichnis nicht anlegen: $host_base"
        echo "    Kein Schreibrecht und kein (funktionierendes) sudo vorhanden."
        echo "    Erneut starten und einen beschreibbaren Pfad wählen (z.B. unter \$HOME)."
        exit 1
    fi
fi

for sub in Reports ReportsData Logfiles settings dp-keys; do
    p="$host_base/$sub"
    if [ ! -d "$p" ]; then
        if ! $SUDO mkdir -p "$p"; then
            _err "mkdir $p fehlgeschlagen"
            exit 1
        fi
    fi
done
# Ownership nur zurückholen, wenn via sudo (als root) angelegt.
[ -n "$SUDO" ] && $SUDO chown -R "$(id -u):$(id -g)" "$host_base"

# Ownership-Reset bei Docker-Volume-UID-Konflikt: ein früherer fr-api-Container
# kann Volume-Dateien als seinem User (UID 10000) hinterlassen haben → lokaler
# User kann sie nicht mehr überschreiben. Erkennen + via Docker-root-Container
# (läuft als root, daher chown-fähig) zurücksetzen. Nutzt ein bereits lokal
# vorhandenes Image — kein Pull/Login nötig.
if [ -n "$(find "$host_base" ! -uid "$(id -u)" 2>/dev/null | head -n1)" ]; then
    _info "Volume-Dateien gehören teils einem anderen User (vermutlich Container-UID 10000)."
    reset_image=""
    for cand in "$IMAGE_BASE:$fr_version" busybox alpine; do
        if docker image inspect "$cand" >/dev/null 2>&1; then
            reset_image="$cand"
            break
        fi
    done
    if [ -n "$reset_image" ]; then
        read -rp "  Owner aller Volume-Dateien auf dich ($(id -u):$(id -g)) zurücksetzen? (Y/n) " ans
        if [ "$ans" != "n" ] && [ "$ans" != "N" ]; then
            if docker run --rm -v "$host_base:/data" --entrypoint chown "$reset_image" \
                -R "$(id -u):$(id -g)" /data >/dev/null 2>&1; then
                _ok "Ownership zurückgesetzt (via $reset_image)"
            else
                _err "Ownership-Reset fehlgeschlagen — bitte manuell ausführen:"
                echo "    docker run --rm -v \"$host_base:/data\" --entrypoint chown \\"
                echo "      \"$reset_image\" -R $(id -u):$(id -g) /data"
                exit 1
            fi
        else
            _info "Reset übersprungen — Schreiben kann in Step 6 fehlschlagen."
        fi
    else
        _info "Kein lokales Image für den Reset gefunden — verfügbar nach erstem Image-Pull,"
        echo "    oder manuell mit busybox/alpine, falls vorhanden:"
        echo "      docker run --rm -v \"$host_base:/data\" --entrypoint chown \\"
        echo "        busybox -R $(id -u):$(id -g) /data"
    fi
fi

# dp-keys hält DataProtection-Schlüssel (unverschlüsselt auf Disk, da DPAPI
# auf Linux nicht verfügbar) — auf 0700 restriktivieren. Nach evtl. Reset gehört
# es uns; falls nicht (Reset abgelehnt), nur Hinweis statt Abbruch.
if ! chmod 0700 "$host_base/dp-keys" 2>/dev/null; then
    _info "dp-keys: chmod übersprungen (gehört anderem User, z.B. Container-UID 10000)"
fi
_ok "Verzeichnisse unter $host_base bereit"

# ── Step 5: Secret-Cascade ───────────────────────────────────────────────────
_hr
_info "Step 5: Secret-Cascade auflösen (Override > Existing > Baked Default)"
settings_file="$host_base/settings/appsettings.json"

# Existierende Werte auslesen (default = leer/null)
existing_admin_pwd=""
existing_superuser_pwd=""
existing_jwt_key=""
existing_jwt_audience="null"
existing_jwt_authtoken="null"
existing_jwt_created="null"
existing_jwt_expires="null"
existing_twofactor="null"
existing_twofactor_su="null"
existing_smtp="null"

if [ -r "$settings_file" ]; then
    if _json_valid "$settings_file"; then
        existing_admin_pwd="$(_json_get_raw "$settings_file" "Settings.password")"
        existing_superuser_pwd="$(_json_get_raw "$settings_file" "Settings.superuser_pwd")"
        existing_jwt_key="$(_json_get_raw "$settings_file" "Settings.JWT.Key")"
        existing_jwt_audience="$(_json_get_json "$settings_file" "Settings.JWT.Audience")"
        existing_jwt_authtoken="$(_json_get_json "$settings_file" "Settings.JWT.Authtoken")"
        existing_jwt_created="$(_json_get_json "$settings_file" "Settings.JWT.AuthtokenCreatedAt")"
        existing_jwt_expires="$(_json_get_json "$settings_file" "Settings.JWT.AuthtokenExpiresAt")"
        existing_twofactor="$(_json_get_json "$settings_file" "Settings.TwoFactor")"
        existing_twofactor_su="$(_json_get_json "$settings_file" "Settings.TwoFactorSuperuser")"
        existing_smtp="$(_json_get_json "$settings_file" "Settings.Smtp")"
        _ok "Bestehende appsettings.json eingelesen"
    else
        _err "Bestehende appsettings.json ist kein valides JSON — wird ignoriert"
    fi
else
    _info "Keine bestehende appsettings.json — Baked Defaults greifen bei leerer Eingabe"
fi

# Admin-Hash (MD5 — vom fr-api-Legacy-Login vorgegeben, nicht wählbar)
if [ -n "$fr_admin_password" ]; then
    final_admin_hash="$(printf '%s' "$fr_admin_password" | md5sum | awk '{print $1}')"
    _ok "Admin-Hash neu generiert (MD5)"
elif [ -n "$existing_admin_pwd" ]; then
    final_admin_hash="$existing_admin_pwd"
    _info "Admin-Hash aus bestehender Datei übernommen"
else
    GENERATED_ADMIN_PWD="$(_gen_secret)"
    final_admin_hash="$(printf '%s' "$GENERATED_ADMIN_PWD" | md5sum | awk '{print $1}')"
    _info "Admin-Passwort zufällig generiert (wird am Ende einmalig angezeigt)"
fi

# Superuser-Hash (bcrypt via stdin — Passwort niemals als CLI-Argument)
if [ -n "$fr_superuser_password" ]; then
    _ensure_bcrypt_python || exit 1
    final_superuser_hash="$(printf '%s' "$fr_superuser_password" \
        | "$BCRYPT_PYTHON" -c 'import sys, bcrypt; pwd=sys.stdin.read().encode(); print(bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12)).decode())')"
    if [ $? -ne 0 ] || [ -z "$final_superuser_hash" ]; then
        _err "bcrypt-Hashing fehlgeschlagen"
        exit 1
    fi
    _ok "Superuser-Hash neu generiert (bcrypt, \$2b\$12\$…)"
elif [ -n "$existing_superuser_pwd" ]; then
    final_superuser_hash="$existing_superuser_pwd"
    _info "Superuser-Hash aus bestehender Datei übernommen"
else
    # Kein Override, keine bestehende Datei → Zufallspasswort. Superuser-Hash
    # ist zwingend bcrypt (Baked-Default-Hashes wurden aus Sicherheitsgründen
    # entfernt); _ensure_bcrypt_python stellt bcrypt bei Bedarf via uv-venv bereit.
    _ensure_bcrypt_python || exit 1
    GENERATED_SUPERUSER_PWD="$(_gen_secret)"
    final_superuser_hash="$(printf '%s' "$GENERATED_SUPERUSER_PWD" \
        | "$BCRYPT_PYTHON" -c 'import sys, bcrypt; pwd=sys.stdin.read().encode(); print(bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12)).decode())')"
    if [ $? -ne 0 ] || [ -z "$final_superuser_hash" ]; then
        _err "bcrypt-Hashing fehlgeschlagen"
        exit 1
    fi
    _info "Superuser-Passwort zufällig generiert (wird am Ende einmalig angezeigt)"
fi

# JWT-Key (raw String)
if [ -n "$fr_jwt_key" ]; then
    final_jwt_key="$fr_jwt_key"
    _ok "JWT-Key neu gesetzt"
elif [ -n "$existing_jwt_key" ]; then
    final_jwt_key="$existing_jwt_key"
    _info "JWT-Key aus bestehender Datei übernommen"
else
    final_jwt_key="$(_gen_jwt_key)"
    GENERATED_JWT_KEY=1
    _info "JWT-Key zufällig generiert (32-Byte hex)"
fi

# ── Step 6: appsettings.json rendern ─────────────────────────────────────────
_hr
_info "Step 6: appsettings.json rendern"

# Schreibbarkeit prüfen — häufigste Fehlerquelle: ein früherer fr-api-Container
# hat settings/ + appsettings.json als seinem User (UID 10000) angelegt; der
# lokale User kann dann nicht überschreiben. Klare Diagnose statt Errno 13.
settings_dir="$(dirname "$settings_file")"
if ! { [ -w "$settings_dir" ] && { [ ! -e "$settings_file" ] || [ -w "$settings_file" ]; }; }; then
    _err "Kein Schreibrecht auf $settings_file"
    echo "    Ursache: Dateien gehören vermutlich dem Container-User (UID 10000),"
    echo "    nachdem fr-api hier schon einmal lief. Lösung ohne sudo — Owner via"
    echo "    Docker-root-Container auf dich zurücksetzen:"
    echo
    echo "      docker run --rm -v \"$host_base:/data\" --entrypoint chown \\"
    echo "        \"$IMAGE_BASE:$fr_version\" -R $(id -u):$(id -g) /data"
    echo
    echo "    Danach dieses Skript erneut starten. Alternativ einen frischen"
    echo "    Container-Namen wählen (legt ein neues, leeres Volume-Verzeichnis an)."
    exit 1
fi

if [ -f "$settings_file" ]; then
    if cp -a "$settings_file" "$settings_file.bak" 2>/dev/null; then
        _ok "Backup: $settings_file.bak"
    else
        _info "Backup übersprungen (kein Schreibrecht für .bak) — fahre fort"
    fi
fi

# Render via Python (json-Standardlib) — sicher gegen Quoting-Bugs.
# Werte über Umgebungsvariablen übergeben (Strings) bzw. als kompaktes JSON
# (die existing_*-Werte). Struktur 1:1 Spiegel von templates/appsettings.json.j2.
ADMIN_HASH="$final_admin_hash" \
SUPER_HASH="$final_superuser_hash" \
JWT_KEY="$final_jwt_key" \
J_AUDIENCE="$existing_jwt_audience" \
J_AUTHTOKEN="$existing_jwt_authtoken" \
J_CREATED="$existing_jwt_created" \
J_EXPIRES="$existing_jwt_expires" \
J_TWOFACTOR="$existing_twofactor" \
J_TWOFACTOR_SU="$existing_twofactor_su" \
J_SMTP="$existing_smtp" \
OUT_FILE="$settings_file" \
python3 - <<'PY'
import os, json, sys

def jload(name):
    raw = os.environ.get(name, "null")
    return json.loads(raw) if raw not in (None, "") else None

jwt = {
    "Key": os.environ["JWT_KEY"],
    "Issuer": "EQ_FR_API",
    "Audience": jload("J_AUDIENCE"),
    "Authtoken": jload("J_AUTHTOKEN"),
}
created = jload("J_CREATED")
expires = jload("J_EXPIRES")
if created is not None:
    jwt["AuthtokenCreatedAt"] = created
if expires is not None:
    jwt["AuthtokenExpiresAt"] = expires

doc = {
    "BasePath": "",
    "ConnectionStrings": {
        "AppDb": "Data Source=wwwroot/App_Data/app.db;Cache=Shared"
    },
    "Settings": {
        "frxPath": "wwwroot/App_Data/Reports/",
        "dataPath": "wwwroot/App_Data/ReportsData/",
        "logPath": "wwwroot/App_Data/Logfiles/",
        "username": "admin",
        "password": os.environ["ADMIN_HASH"],
        "superuser": "superuser",
        "superuser_pwd": os.environ["SUPER_HASH"],
        "tmpLifetime": 1,
        "historyLifetime": 7,
        "useLogs": True,
        "logLevel": "Warning",
        "JWT": jwt,
        "ErrorReportName": "odoo2fr_crash_report.frx",
        "TwoFactor": jload("J_TWOFACTOR"),
        "TwoFactorSuperuser": jload("J_TWOFACTOR_SU"),
        "Smtp": jload("J_SMTP"),
        "Ai": {"Enabled": False},
    },
    "Logging": {
        "LogLevel": {
            "Default": "Information",
            "Microsoft.AspNetCore": "Warning",
        }
    },
    "Serilog": {
        "MinimumLevel": {
            "Override": {
                "Microsoft.AspNetCore": "Warning",
                "System": "Warning",
            },
        },
        "Enrich": ["FromLogContext", "WithMachineName", "WithThreadId"],
        "Properties": {"Application": "fr-api"},
        "WriteTo": [
            {
                "Name": "Console",
                "Args": {
                    "formatter": "Serilog.Formatting.Compact.CompactJsonFormatter, Serilog.Formatting.Compact"
                },
            },
            {
                "Name": "File",
                "Args": {
                    "path": "wwwroot/App_Data/Logfiles/FastReportsAPI-.json",
                    "formatter": "Serilog.Formatting.Compact.CompactJsonFormatter, Serilog.Formatting.Compact",
                    "rollingInterval": "Day",
                    "retainedFileCountLimit": 30,
                    "hooks": "Serilog.Sinks.File.Archive.ArchiveHooks, Serilog.Sinks.File.Archive",
                },
            },
        ],
    },
    "AllowedHosts": "*",
}

try:
    with open(os.environ["OUT_FILE"], "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
except Exception as e:
    sys.stderr.write(str(e) + "\n")
    sys.exit(1)
PY
if [ $? -ne 0 ]; then
    _err "appsettings.json Rendern fehlgeschlagen"
    exit 1
fi

# 0600 — enthält den JWT-Signing-Key im Klartext (Settings.JWT.Key); world-
# readable wäre ein Auth-Bypass-Risiko (JWT-Forgery durch jeden lokalen User).
chmod 0600 "$settings_file"

if ! _json_valid "$settings_file"; then
    _err "Gerenderte appsettings.json ist kein valides JSON"
    exit 1
fi
_ok "appsettings.json gerendert + validiert: $settings_file"

# ── Step 7: Docker-Registry-Login ────────────────────────────────────────────
_hr
_info "Step 7: Docker-Registry-Login"
# --password-stdin statt -p: hält den Token aus der Prozessliste (ps aux /
# /proc/<pid>/cmdline), wo -p ihn für jeden lokalen User sichtbar machen würde.
if ! printf '%s' "$registry_token" | docker login -u "$REGISTRY_USER" --password-stdin "$REGISTRY_URL"; then
    _err "Docker-Login fehlgeschlagen"
    exit 1
fi
_ok "Login OK"

# ── Step 8: Image-Existenz prüfen + Pull ─────────────────────────────────────
_hr
image="$IMAGE_BASE:$fr_version"
_info "Step 8: Image-Existenz prüfen + Pull"

if ! docker manifest inspect "$image" >/dev/null 2>&1; then
    _err "Image '$image' existiert nicht (oder ist nicht zugänglich)."

    _info "Versuche, verfügbare Tags aus der Registry zu listen …"

    # Docker Registry V2 API mit GitLab JWT-Auth
    jwt_resp="$(_http_get_basic \
        "$GITLAB_JWT_AUTH?service=container_registry&scope=repository:$IMAGE_REPO:pull&client_id=docker" \
        "$REGISTRY_USER" "$registry_token")"
    jwt="$(printf '%s' "$jwt_resp" | python3 -c 'import sys, json
try:
    sys.stdout.write(json.load(sys.stdin).get("token") or "")
except Exception:
    pass' 2>/dev/null)"

    if [ -n "$jwt" ]; then
        tags_json="$(_http_get_bearer \
            "https://$REGISTRY_URL/v2/$IMAGE_REPO/tags/list" "$jwt")"
        tags="$(printf '%s' "$tags_json" | python3 -c 'import sys, json
try:
    for t in (json.load(sys.stdin).get("tags") or []):
        print(t)
except Exception:
    pass' 2>/dev/null | sort -V)"

        if [ -n "$tags" ]; then
            echo
            echo "  Verfügbare Tags in $IMAGE_BASE:"
            while IFS= read -r t; do
                echo "    • $t"
            done <<< "$tags"
            echo
            echo "  Erneut ausführen und passenden Tag angeben."
        else
            _err "Konnte Tags-Liste nicht parsen. Rohausgabe:"
            echo "$tags_json"
        fi
    else
        _err "Konnte JWT für Registry-Auth nicht beziehen ($GITLAB_JWT_AUTH)."
        echo "  Token korrekt? Hat das PAT 'read_registry' Scope?"
        echo "  Manuell prüfbar:"
        echo "    curl -u $REGISTRY_USER:\$TOKEN '$GITLAB_JWT_AUTH?service=container_registry&scope=repository:$IMAGE_REPO:pull&client_id=docker'"
    fi
    exit 1
fi
_ok "Image '$image' existiert in Registry"

if ! docker pull "$image"; then
    _err "Image Pull fehlgeschlagen"
    exit 1
fi

# ── Step 9: Image-Hygiene-Audit ──────────────────────────────────────────────
_hr
_info "Step 9: Image-Hygiene-Audit"

# Scan auf appsettings.Development.* und andere Entwicklungs-Indikatoren.
leaked="$(docker run --rm --entrypoint sh "$image" -c '
    find /app \( \
        -name "appsettings.Development.json" -o \
        -name "appsettings.Development.*" -o \
        -name "*.csproj" -o \
        -name "*.cs" -o \
        -name "launchSettings.json" \
    \) 2>/dev/null
' 2>/dev/null)"

if [ -n "$leaked" ]; then
    _err "KRITISCH: Entwicklungs-Artefakte im Image gefunden:"
    echo "$leaked"
    echo
    _err "Deploy abgebrochen — Image ist nicht produktionsreif."
    exit 2
fi
_ok "Keine Entwicklungs-Artefakte im Image"

# dp-keys-Verzeichnis muss im Image vorhanden, mode 0700, owner frapi:frapi sein
# (DataProtection-Keys-Persistenz, ab Build 3.0.4 erforderlich).
dpkeys_stat="$(docker run --rm --entrypoint sh "$image" -c '
    if [ -d /app/wwwroot/App_Data/dp-keys ]; then
        stat -c "%a %U:%G" /app/wwwroot/App_Data/dp-keys
    else
        echo MISSING
    fi
' 2>/dev/null)"
case "$dpkeys_stat" in
    MISSING)
        _err "dp-keys-Verzeichnis fehlt im Image — Dockerfile-Regression?"
        exit 2
        ;;
    "700 frapi:frapi")
        _ok "dp-keys-Verzeichnis im Image vorhanden (0700, frapi:frapi)"
        ;;
    *)
        _err "dp-keys-Permissions/Owner unerwartet: '$dpkeys_stat' (erwartet '700 frapi:frapi')"
        exit 2
        ;;
esac

audit_log="$host_base/image-history-$fr_version.log"
docker history --no-trunc "$image" > "$audit_log" 2>/dev/null
_ok "Image-History gespeichert: $audit_log"

# ── Step 10: Compose-File + Container-Lifecycle ──────────────────────────────
_hr
_info "Step 10: docker-compose.yml generieren + Container starten"

compose_file="$host_base/docker-compose.yml"

# Compose-File schreiben — kapselt alle Run-Parameter, ermöglicht späteres
# start/stop/restart ohne dieses Skript. Pfade in doppelten Quotes gegen
# Sonderzeichen/Spaces im Basis-Verzeichnis.
cat > "$compose_file" <<EOF
# Generiert von local-deploy.sh — fr-api Deployment "$fr_name".
# Steuerung (verzeichnis-unabhängig via -f):
#   docker compose -f "$compose_file" up -d     # starten / aktualisieren
#   docker compose -f "$compose_file" stop      # anhalten
#   docker compose -f "$compose_file" start     # wieder anlaufen
#   docker compose -f "$compose_file" down      # entfernen (Volumes bleiben)
services:
  fr-api:
    image: "$image"
    container_name: "$fr_name"
    restart: always
    shm_size: 1g
    ports:
      - "127.0.0.1:$fr_port:$CONTAINER_PORT"
    volumes:
      - "$host_base/Reports:$container_base_path/App_Data/Reports/"
      - "$host_base/ReportsData:$container_base_path/App_Data/ReportsData/"
      - "$host_base/Logfiles:$container_base_path/App_Data/Logfiles/"
      - "$host_base/settings:$container_base_path/App_Data/settings/"
      - "$host_base/dp-keys:$container_base_path/App_Data/dp-keys/"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:$CONTAINER_PORT/health"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
EOF
_ok "Compose-File geschrieben: $compose_file"

# Compose-Verfügbarkeit ermitteln (v2-Plugin bevorzugt, v1-Binary als Fallback)
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    DC=""
fi

# Idempotenz — Bestätigungs-Prompt bei existierendem Container
if docker ps -a --format '{{.Names}}' | grep -qx "$fr_name"; then
    read -rp "  Container '$fr_name' existiert bereits. Entfernen und neu deployen? (y/N) " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        [ -n "$DC" ] && $DC -f "$compose_file" down >/dev/null 2>&1
        docker stop "$fr_name" >/dev/null 2>&1
        docker rm "$fr_name" >/dev/null 2>&1
        _ok "Alter Container entfernt"
    else
        _info "Abbruch — kein Re-Deploy. Volumes + appsettings.json bleiben erhalten."
        exit 0
    fi
fi

# Start — bevorzugt via Compose, sonst 'docker run' (Compose-File bleibt für später).
if [ -n "$DC" ]; then
    if ! $DC -f "$compose_file" up -d >/dev/null; then
        _err "$DC up fehlgeschlagen"
        exit 1
    fi
    _ok "Container via Compose gestartet ($DC)"
else
    _info "Kein docker compose verfügbar — Start via 'docker run' (Compose-File für später hinterlegt)"
    if ! docker run -d \
        --name "$fr_name" \
        --restart always \
        --shm-size 1g \
        -p "127.0.0.1:$fr_port:$CONTAINER_PORT" \
        -v "$host_base/Reports:$container_base_path/App_Data/Reports/" \
        -v "$host_base/ReportsData:$container_base_path/App_Data/ReportsData/" \
        -v "$host_base/Logfiles:$container_base_path/App_Data/Logfiles/" \
        -v "$host_base/settings:$container_base_path/App_Data/settings/" \
        -v "$host_base/dp-keys:$container_base_path/App_Data/dp-keys/" \
        --health-cmd "curl -fsS http://localhost:$CONTAINER_PORT/health" \
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

# Healthcheck-Wait (max 60s)
_info "Warte auf Healthcheck …"
healthy=0
for i in $(seq 1 30); do
    st="$(docker inspect --format '{{.State.Health.Status}}' "$fr_name" 2>/dev/null)"
    if [ "$st" = "healthy" ]; then
        healthy=1
        break
    fi
    if [ "$st" = "unhealthy" ]; then
        _err "Container ist unhealthy. Logs: docker logs $fr_name"
        exit 1
    fi
    sleep 2
done

if [ "$healthy" -eq 0 ]; then
    _err "Healthcheck nach 60s nicht erfolgreich. Logs: docker logs $fr_name"
    exit 1
fi
_ok "Container ist healthy"

# Smoke-Test
if _http_check "http://localhost:$fr_port/health"; then
    _ok "Smoke-Test: GET /health → 200 OK"
else
    _err "Smoke-Test fehlgeschlagen — /health nicht erreichbar"
    exit 1
fi

# ── Abschluss-Banner ─────────────────────────────────────────────────────────
_hr
echo
_ok "fr-api Deployment erfolgreich"
echo
echo "  Container:   $fr_name"
echo "  Image:       $image"
echo "  URL:         http://localhost:$fr_port"
echo "  Health:      http://localhost:$fr_port/health"
echo "  Login (UI):  http://localhost:$fr_port/Login"
echo "  Volumes:     $host_base/{Reports,ReportsData,Logfiles,settings}"
echo "  Settings:    $settings_file"
echo "  Compose:     $compose_file"
echo "  Audit-Log:   $audit_log"
echo

# Generierte Secrets EINMALIG anzeigen (kein Baked Default mehr). Nur hier —
# danach nur noch als Hash in appsettings.json (0600) vorhanden.
if [ -n "$GENERATED_ADMIN_PWD" ] || [ -n "$GENERATED_SUPERUSER_PWD" ] || [ "$GENERATED_JWT_KEY" -eq 1 ]; then
    _info "Automatisch generierte Zugangsdaten — JETZT sicher notieren:"
    [ -n "$GENERATED_ADMIN_PWD" ]     && echo "  Admin-Passwort (User 'admin'):          $GENERATED_ADMIN_PWD"
    [ -n "$GENERATED_SUPERUSER_PWD" ] && echo "  Superuser-Passwort (User 'superuser'):  $GENERATED_SUPERUSER_PWD"
    [ "$GENERATED_JWT_KEY" -eq 1 ]    && echo "  JWT-Signing-Key:                        (zufällig, liegt nur in appsettings.json)"
    echo "  Werden nicht erneut angezeigt (nur als Hash in appsettings.json gespeichert)."
    echo
fi
if [ -n "$DC" ]; then
    echo "  Logs anzeigen:   $DC -f \"$compose_file\" logs -f"
    echo "  Stoppen:         $DC -f \"$compose_file\" stop"
    echo "  Starten:         $DC -f \"$compose_file\" start"
    echo "  Neu starten:     $DC -f \"$compose_file\" restart"
    echo "  Entfernen:       $DC -f \"$compose_file\" down"
else
    echo "  Logs anzeigen:   docker logs -f $fr_name"
    echo "  Stoppen:         docker stop $fr_name"
    echo "  Starten:         docker start $fr_name"
    echo "  Neu starten:     docker restart $fr_name"
    echo "  Entfernen:       docker rm -f $fr_name"
fi
echo
