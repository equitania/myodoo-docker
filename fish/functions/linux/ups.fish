# Update ownERP Scripts Function
# Version 1.1.0 | 11.08.2026

function ups --description "Update ownERP scripts from repository (-v for full output)"
    echo "🔄 Updating ownERP scripts..."
    echo ""

    # Run getScripts.py - arguments are forwarded, so `ups -v` reaches the
    # script's verbose mode instead of being swallowed here
    sudo $HOME/getScripts.py $argv

    # Copy the updated getScripts.py
    sudo cp $HOME/myodoo-docker/getScripts.py $HOME/

    # Reload Fish configuration
    echo ""
    echo "🐟 Reloading Fish configuration..."
    source ~/.config/fish/config.fish

    echo ""
    echo "✅ ownERP scripts updated!"
end
