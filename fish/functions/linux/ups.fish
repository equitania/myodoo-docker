# Update ownERP Scripts Function
# Version 1.2.0 | 15.09.2026

function ups --description "Update ownERP scripts from repository (-v for full output)"
    echo "🔄 Updating ownERP scripts..."
    echo ""

    # Run getScripts.py - arguments are forwarded, so `ups -v` reaches the
    # script's verbose mode instead of being swallowed here.
    #
    # --preserve-env: on Debian, `Defaults env_reset` strips http_proxy/
    # https_proxy/no_proxy from the sudo child even though this fish session
    # has them (99-proxy.fish) and /etc/environment carries them too -
    # /etc/pam.d/sudo has no pam_env line, so that file is not re-read under
    # sudo either. Without this flag, a proxy-only server's `git pull` inside
    # getScripts goes direct and is silently dropped by the firewall.
    # getScripts.py >= 9.23.1 also recovers the proxy itself if it is still
    # missing here (ensure_proxy_environment()); this is the cheaper, direct
    # fix. Supported since sudo 1.8.21 (Debian 12/13, Ubuntu 22.04/24.04).
    sudo --preserve-env=http_proxy,https_proxy,no_proxy,HTTP_PROXY,HTTPS_PROXY,NO_PROXY $HOME/getScripts.py $argv

    # Copy the updated getScripts.py
    sudo cp $HOME/myodoo-docker/getScripts.py $HOME/

    # Reload Fish configuration
    echo ""
    echo "🐟 Reloading Fish configuration..."
    source ~/.config/fish/config.fish

    echo ""
    echo "✅ ownERP scripts updated!"
end
