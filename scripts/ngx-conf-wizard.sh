#!/usr/bin/env bash
#
# ngx-conf-wizard.sh — interactive wizard for nginx-set-conf YAML configs.
#
# Version: 1.0.0 — 15.07.2026
#
# Builds the YAML config consumed by nginx-set-conf (and the 'ngxset' alias:
#   nginx-set-conf --config_path=$HOME/docker-builds/ngx-conf/ )
# entry by entry: pick a config template, answer the template-specific
# questions, repeat ("one more?"), then write the file — optionally deploy.
#
# Sibling of pg-local-deploy.sh / fr-local-deploy.sh: self-contained single
# file, no secrets embedded, whitelist validation for every value that ends
# up in the generated YAML.
#
# Supported templates mirror nginx_set_conf/templates/all_templates.py
# (PyPi-Projects/nginx-set-conf). YAML keys mirror the parser in
# nginx_set_conf.py: port, cert_name, cert_key, pollport, grpcport,
# redirect_domain, auth_file, allowed_ips, backend_ip, root_path,
# disable_domain_listen, enable_http3.

set -o pipefail

DEFAULT_TARGET_DIR="$HOME/docker-builds/ngx-conf"
CONFIG_FILE_NAME="config.yaml"

# ── Colors (terminal only) ───────────────────────────────────────────────────
if [ -t 1 ]; then
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_CYAN=$'\033[36m'
    C_YELLOW=$'\033[33m'
    C_RESET=$'\033[0m'
else
    C_RED=""; C_GREEN=""; C_CYAN=""; C_YELLOW=""; C_RESET=""
fi

# ── Helpers ──────────────────────────────────────────────────────────────────
_err()  { printf '%s✗ %s%s\n' "$C_RED"    "$*" "$C_RESET" >&2; }
_ok()   { printf '%s✓ %s%s\n' "$C_GREEN"  "$*" "$C_RESET"; }
_info() { printf '%s▶ %s%s\n' "$C_CYAN"   "$*" "$C_RESET"; }
_warn() { printf '%s! %s%s\n' "$C_YELLOW" "$*" "$C_RESET"; }
_hr()   { printf '%s\n' "────────────────────────────────────────────────────────"; }

# ── Template registry (mirrors all_templates.py, most-used first) ────────────
# columns: key | needs_cert | needs_port | default_port | extra
# extra: pollport | grpcport | redirect | rootpath | -
TEMPLATES=(
    "odoo_ssl|yes|yes|11000|pollport"
    "odoo_http|no|yes|11000|pollport"
    "fast_report|yes|yes|8899|-"
    "pgadmin|yes|yes|5050|-"
    "mailpit|yes|yes|8025|-"
    "code_server|yes|yes||-"
    "redirect_ssl|yes|no||redirect"
    "redirect|no|no||redirect"
    "static_ssl|yes|no||rootpath"
    "nextcloud|yes|yes||-"
    "portainer|yes|yes||-"
    "flowise|yes|yes|3000|-"
    "qdrant|yes|yes|6333|grpcport"
    "n8n|yes|yes|5678|-"
    "guacamole|yes|yes|8080|-"
    "kasm|yes|yes|8443|-"
    "pwa|yes|yes||-"
    "supabase|yes|yes|8000|-"
    "patchmon|yes|yes|3000|-"
)

# Templates eligible for enable_http3 (see HTTP3_EXCLUDED_TEMPLATES in
# nginx_set_conf/validators.py — gRPC/server-to-server/redirects are excluded).
HTTP3_TEMPLATES=" odoo_ssl flowise n8n nextcloud guacamole kasm pgadmin portainer pwa code_server supabase qdrant static_ssl "

# ── Validators (values end up in generated YAML — whitelist everything) ──────
_valid_domain() { [[ "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]; }
_valid_name()   { [[ "$1" =~ ^[a-zA-Z0-9][a-zA-Z0-9\ ._-]*$ ]]; }
_valid_port()   { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]; }
_valid_path()   { [[ "$1" =~ ^[A-Za-z0-9/._-]+$ ]] && [[ "$1" != *".."* ]]; }
_valid_ip() {
    if [[ "$1" == *:* ]]; then
        [[ "$1" =~ ^[0-9a-fA-F:]+$ ]]
    else
        [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
    fi
}

# ── Step 1: target directory + existing file handling ────────────────────────
_hr
_info "Step 1: Target directory"
read -rp "  Zielverzeichnis [$DEFAULT_TARGET_DIR]: " target_dir
[ -z "$target_dir" ] && target_dir="$DEFAULT_TARGET_DIR"
case "$target_dir" in
    "~")   target_dir="$HOME" ;;
    "~/"*) target_dir="$HOME/${target_dir#\~/}" ;;
esac
if ! _valid_path "$target_dir"; then
    _err "Ungültiges Verzeichnis: $target_dir"
    exit 1
fi
if ! mkdir -p "$target_dir"; then
    _err "Kann Zielverzeichnis nicht anlegen: $target_dir"
    exit 1
fi
config_file="$target_dir/$CONFIG_FILE_NAME"

write_mode="new"
if [ -f "$config_file" ]; then
    entry_count_existing="$(grep -c '^[A-Za-z0-9]' "$config_file" 2>/dev/null || echo 0)"
    _warn "Es existiert bereits: $config_file ($entry_count_existing Einträge)"
    read -rp "  (a)nhängen / (o)verwrite mit Backup / (q) abbrechen [a]: " file_choice
    case "${file_choice:-a}" in
        [aA]) write_mode="append" ;;
        [oO])
            ts="$(date +%Y%m%d_%H%M%S)"
            cp -a "$config_file" "$config_file.bak-$ts"
            _ok "Backup: $config_file.bak-$ts"
            write_mode="new"
            ;;
        *) _info "Abbruch."; exit 0 ;;
    esac
fi
_ok "Ziel: $config_file (Modus: $write_mode)"

# ── Step 2: server IP (used for every entry's listen directive) ──────────────
_hr
_info "Step 2: Server-IP (für die listen-Direktiven aller Einträge)"
while :; do
    read -rp "  Server-IP (IPv4 oder IPv6): " server_ip
    if _valid_ip "$server_ip"; then break; fi
    _err "Ungültige IP: $server_ip"
done
_ok "Server-IP: $server_ip"

# ── Step 3: entry loop ────────────────────────────────────────────────────────
declare -a session_names=()
yaml_buffer=""
entry_no=0

_name_exists() {
    local n="$1"
    for existing in "${session_names[@]}"; do
        [ "$existing" = "$n" ] && return 0
    done
    if [ "$write_mode" = "append" ] && [ -f "$config_file" ]; then
        grep -q "^${n}:" "$config_file" && return 0
    fi
    return 1
}

while :; do
    entry_no=$((entry_no + 1))
    _hr
    _info "Step 3: Eintrag $entry_no anlegen"
    echo
    echo "  Verfügbare Config-Templates:"
    i=0
    for t in "${TEMPLATES[@]}"; do
        i=$((i + 1))
        printf '    %2d) %s\n' "$i" "${t%%|*}"
    done
    while :; do
        read -rp "  Template-Auswahl [1]: " tpl_choice
        [ -z "$tpl_choice" ] && tpl_choice=1
        if [[ "$tpl_choice" =~ ^[0-9]+$ ]] && [ "$tpl_choice" -ge 1 ] && [ "$tpl_choice" -le "${#TEMPLATES[@]}" ]; then
            break
        fi
        _err "Ungültige Auswahl: $tpl_choice"
    done
    IFS='|' read -r tpl_key tpl_cert tpl_port tpl_port_default tpl_extra <<< "${TEMPLATES[$((tpl_choice - 1))]}"
    _ok "Template: $tpl_key"

    while :; do
        read -rp "  Domain (z.B. www.example.com): " domain
        if _valid_domain "$domain"; then break; fi
        _err "Ungültige Domain: $domain"
    done

    while :; do
        read -rp "  Eintragsname [$domain]: " entry_name
        [ -z "$entry_name" ] && entry_name="$domain"
        if ! _valid_name "$entry_name"; then
            _err "Ungültiger Name: $entry_name"
            continue
        fi
        if _name_exists "$entry_name"; then
            _err "Eintragsname existiert bereits: $entry_name"
            continue
        fi
        break
    done

    port=""
    if [ "$tpl_port" = "yes" ]; then
        while :; do
            read -rp "  Backend-Port${tpl_port_default:+ [$tpl_port_default]}: " port
            [ -z "$port" ] && port="$tpl_port_default"
            if _valid_port "$port"; then break; fi
            _err "Ungültiger Port: $port"
        done
    fi

    pollport=""
    grpcport=""
    redirect_domain=""
    root_path=""
    case "$tpl_extra" in
        pollport)
            while :; do
                read -rp "  Longpolling-Port [12000]: " pollport
                [ -z "$pollport" ] && pollport="12000"
                if _valid_port "$pollport"; then break; fi
                _err "Ungültiger Port: $pollport"
            done
            ;;
        grpcport)
            while :; do
                read -rp "  gRPC-Port [6334]: " grpcport
                [ -z "$grpcport" ] && grpcport="6334"
                if _valid_port "$grpcport"; then break; fi
                _err "Ungültiger Port: $grpcport"
            done
            ;;
        redirect)
            while :; do
                read -rp "  Redirect-Ziel-Domain: " redirect_domain
                if _valid_domain "$redirect_domain"; then break; fi
                _err "Ungültige Domain: $redirect_domain"
            done
            ;;
        rootpath)
            while :; do
                read -rp "  Document-Root [/opt/www]: " root_path
                [ -z "$root_path" ] && root_path="/opt/www"
                if _valid_path "$root_path"; then break; fi
                _err "Ungültiger Pfad: $root_path"
            done
            ;;
    esac

    cert_name=""
    if [ "$tpl_cert" = "yes" ]; then
        while :; do
            read -rp "  Zertifikatsname [$domain]: " cert_name
            [ -z "$cert_name" ] && cert_name="$domain"
            if _valid_path "$cert_name" || _valid_domain "$cert_name"; then break; fi
            _err "Ungültiger Zertifikatsname: $cert_name"
        done
    fi

    backend_ip=""
    auth_file=""
    allowed_ips=""
    enable_http3=""
    read -rp "  Optionale Felder setzen (backend_ip, auth_file, allowed_ips, HTTP/3)? (y/N) " want_opts
    if [[ "$want_opts" =~ ^[yYjJ]$ ]]; then
        read -rp "    backend_ip [leer = 127.0.0.1]: " backend_ip
        if [ -n "$backend_ip" ] && ! _valid_ip "$backend_ip"; then
            _err "Ungültige backend_ip: $backend_ip — Feld wird übersprungen."
            backend_ip=""
        fi
        read -rp "    auth_file (htpasswd, leer = keine): " auth_file
        if [ -n "$auth_file" ] && ! _valid_path "$auth_file"; then
            _err "Ungültige auth_file: $auth_file — Feld wird übersprungen."
            auth_file=""
        fi
        read -rp "    allowed_ips (CSV, leer = alle): " allowed_ips
        if [ -n "$allowed_ips" ] && ! [[ "$allowed_ips" =~ ^[0-9a-fA-F.:/,\ ]+$ ]]; then
            _err "Ungültige allowed_ips: $allowed_ips — Feld wird übersprungen."
            allowed_ips=""
        fi
        if [[ "$HTTP3_TEMPLATES" == *" $tpl_key "* ]]; then
            read -rp "    HTTP/3 aktivieren (braucht nginx >= 1.25 + UDP/443)? (y/N) " want_h3
            [[ "$want_h3" =~ ^[yYjJ]$ ]] && enable_http3="true"
        fi
    fi

    # Assemble YAML block (keys mirror nginx_set_conf.py parser)
    entry_yaml="${entry_name}:
  config_template: ${tpl_key}
  ip: ${server_ip}
  domain: ${domain}
"
    [ -n "$port" ]            && entry_yaml+="  port: ${port}
"
    [ -n "$pollport" ]        && entry_yaml+="  pollport: ${pollport}
"
    [ -n "$grpcport" ]        && entry_yaml+="  grpcport: ${grpcport}
"
    [ -n "$cert_name" ]       && entry_yaml+="  cert_name: ${cert_name}
"
    [ -n "$redirect_domain" ] && entry_yaml+="  redirect_domain: ${redirect_domain}
"
    [ -n "$root_path" ]       && entry_yaml+="  root_path: ${root_path}
"
    [ -n "$backend_ip" ]      && entry_yaml+="  backend_ip: \"${backend_ip}\"
"
    [ -n "$auth_file" ]       && entry_yaml+="  auth_file: ${auth_file}
"
    [ -n "$allowed_ips" ]     && entry_yaml+="  allowed_ips: \"${allowed_ips}\"
"
    [ -n "$enable_http3" ]    && entry_yaml+="  enable_http3: true
"

    echo
    _info "Zusammenfassung Eintrag $entry_no:"
    printf '%s' "$entry_yaml" | sed 's/^/    /'
    read -rp "  Eintrag übernehmen? (Y/n) " keep_entry
    if [[ "$keep_entry" =~ ^[nN]$ ]]; then
        _warn "Eintrag verworfen."
        entry_no=$((entry_no - 1))
    else
        session_names+=("$entry_name")
        yaml_buffer+="${entry_yaml}
"
        _ok "Eintrag übernommen: $entry_name"
    fi

    read -rp "  Weiteren Eintrag anlegen? (y/N) " more
    [[ "$more" =~ ^[yYjJ]$ ]] || break
done

if [ "${#session_names[@]}" -eq 0 ]; then
    _warn "Keine Einträge übernommen — nichts zu schreiben."
    exit 0
fi

# ── Step 4: write config file ─────────────────────────────────────────────────
_hr
_info "Step 4: Config schreiben"
if [ "$write_mode" = "append" ]; then
    printf '\n%s' "$yaml_buffer" >> "$config_file"
else
    printf '# Generated by ngx-conf-wizard.sh — %s\n# Consumed by: nginx-set-conf --config_path=%s/\n\n%s' \
        "$(date '+%d.%m.%Y %H:%M')" "$target_dir" "$yaml_buffer" > "$config_file"
fi
_ok "Geschrieben: $config_file (${#session_names[@]} neue Einträge: ${session_names[*]})"

# ── Step 5: optional deploy ───────────────────────────────────────────────────
_hr
_info "Step 5: Deploy"
if command -v nginx-set-conf >/dev/null 2>&1; then
    read -rp "  Jetzt deployen (nginx-set-conf --config_path=$target_dir/)? (y/N) " do_deploy
    if [[ "$do_deploy" =~ ^[yYjJ]$ ]]; then
        if nginx-set-conf --config_path="$target_dir/"; then
            _ok "Deploy abgeschlossen."
        else
            _err "Deploy fehlgeschlagen — Config-Datei bleibt erhalten, Ausgabe oben prüfen."
            exit 1
        fi
    else
        _info "Deploy übersprungen. Später ausführen mit: ngxset  (oder: nginx-set-conf --config_path=$target_dir/)"
    fi
else
    _warn "nginx-set-conf nicht im PATH — Datei wurde geschrieben, Deploy später mit: ngxset"
fi

_hr
_ok "ngx-conf-wizard abgeschlossen"
