# System Update Function
# Version 1.3.0 | 14.07.2026
# Comprehensive system update and cleanup

function syspatch --description "Comprehensive system update and cleanup"
    echo "🧹 Cleaning journal logs..."
    sudo journalctl --vacuum-time=7d
    sudo journalctl --vacuum-size=2G

    echo ""
    echo "📦 Updating package lists..."
    sudo apt -y update

    echo ""
    echo "⬆️  Upgrading packages..."
    sudo apt -y dist-upgrade

    echo ""
    echo "🗑️  Removing unused packages..."
    sudo apt -y autoremove
    sudo apt -y autoclean

    # Rebuild the AIDE baseline: the upgrade legitimately changed system files,
    # so refresh the integrity database to avoid drowning real alerts in noise.
    # NOTE: `aide --update` exits non-zero when it detects changes (always true
    # after an upgrade), so we gate the copy on aide.db.new existing — NOT on the
    # exit code (which is why a plain `aide --update && cp` would be wrong here).
    if command -sq aide
        echo ""
        echo "🔐 Rebuilding AIDE baseline (post-update)..."
        # AIDE 0.18+ (Debian trixie) ships no compiled-in default config, so a
        # bare `aide --update` fails with "missing configuration". On Debian the
        # active config is assembled from /etc/aide/aide.conf.d into
        # aide.conf.autogen by update-aide.conf — regenerate it, then pass it
        # explicitly via --config (falling back to /etc/aide/aide.conf).
        test -x /usr/sbin/update-aide.conf; and sudo /usr/sbin/update-aide.conf
        set -l aide_conf /var/lib/aide/aide.conf.autogen
        sudo test -f $aide_conf; or set aide_conf /etc/aide/aide.conf
        sudo aide --config $aide_conf --update
        if sudo test -f /var/lib/aide/aide.db.new
            sudo cp /var/lib/aide/aide.db.new /var/lib/aide/aide.db
            echo "   AIDE baseline updated."
        else
            echo "   AIDE: no new database produced — baseline left unchanged."
        end
    end

    echo ""
    echo "🐳 Pruning Docker (dangling images only)..."
    # SAFETY: only remove dangling image layers. Do NOT run `docker volume prune`
    # or `docker system prune --volumes` here — that would irreversibly delete
    # data volumes of stopped/paused containers (e.g. an Odoo filestore) with no
    # confirmation. See the Docker safety rule in CLAUDE.md. Use the guarded
    # `dkrmv` / `dkprv` aliases for deliberate, confirmed volume cleanup.
    docker image prune -f

    echo ""
    echo "✅ System update complete!"
end
