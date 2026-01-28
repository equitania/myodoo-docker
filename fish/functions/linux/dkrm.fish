# Docker Remove Containers Function
# Version 1.0.0 | 28.01.2026

function dkrm --description "Remove all Docker containers (with confirmation)"
    set -l containers (docker ps -a -q)

    if test -z "$containers"
        echo "No containers to remove."
        return 0
    end

    echo "The following containers will be removed:"
    docker ps -a --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
    echo ""

    read -l -P "Are you sure you want to remove all containers? [y/N] " confirm

    if test "$confirm" = "y" -o "$confirm" = "Y"
        docker rm $containers
        echo "✅ All containers removed."
    else
        echo "❌ Aborted."
    end
end
