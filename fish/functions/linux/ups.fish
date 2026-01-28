# Update ownERP Scripts Function
# Version 1.0.0 | 28.01.2026

function ups --description "Update ownERP scripts from repository"
    echo "🔄 Updating ownERP scripts..."
    echo ""

    # Run getScripts.py
    sudo $HOME/getScripts.py

    # Copy the updated getScripts.py
    sudo cp $HOME/myodoo-docker/getScripts.py $HOME/

    # Reload Fish configuration
    echo ""
    echo "🐟 Reloading Fish configuration..."
    source ~/.config/fish/config.fish

    echo ""
    echo "✅ ownERP scripts updated!"
end
