# System Update Function
# Version 1.4.0 | 29.09.2026
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
    # The rebuild hashes the whole filesystem and took 30+ min on Docker hosts,
    # so it runs detached as a transient systemd unit at idle CPU/IO priority;
    # syspatch no longer waits for it.
    # NOTE: `aide --update` exits non-zero when it detects changes (always true
    # after an upgrade), so the promotion is gated on aide.db.new existing — NOT
    # on the exit code. A stale aide.db.new from an aborted run is removed first
    # so it can never be promoted.
    if command -sq aide
        echo ""
        echo "🔐 AIDE baseline (post-update)..."
        if systemctl is-active --quiet aide-rebaseline
            echo "   A rebuild is already running — skipped."
            echo "   Progress: journalctl -u aide-rebaseline -f"
        else
            # AIDE 0.18+ (Debian trixie) ships no compiled-in default config, so a
            # bare `aide --update` fails with "missing configuration". On Debian the
            # active config is assembled from /etc/aide/aide.conf.d into
            # aide.conf.autogen by update-aide.conf — regenerate it, then pass it
            # explicitly via --config (falling back to /etc/aide/aide.conf).
            test -x /usr/sbin/update-aide.conf; and sudo /usr/sbin/update-aide.conf
            set -l aide_conf /var/lib/aide/aide.conf.autogen
            sudo test -f $aide_conf; or set aide_conf /etc/aide/aide.conf
            set -l db /var/lib/aide/aide.db
            if sudo systemd-run --unit=aide-rebaseline --collect --quiet \
                    --nice=19 -p IOSchedulingClass=idle -p CPUSchedulingPolicy=idle \
                    /bin/sh -c "rm -f $db.new; aide --config $aide_conf --update; if test -s $db.new; then mv $db.new $db && echo 'AIDE baseline updated.'; else echo 'AIDE: no new database produced - baseline left unchanged.'; fi"
                echo "   Rebuild started in the background (low priority)."
                echo "   Progress: journalctl -u aide-rebaseline -f"
            else
                echo "   AIDE: could not start the background rebuild — baseline left unchanged."
            end
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
