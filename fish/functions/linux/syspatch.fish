# System Update Function
# Version 1.0.0 | 28.01.2026
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

    echo ""
    echo "🐳 Pruning Docker..."
    docker system prune -f
    docker volume prune -f

    echo ""
    echo "✅ System update complete!"
end
