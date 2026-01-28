# Docker Remove Volumes Function
# Version 1.0.0 | 28.01.2026

function dkrmv --description "Remove all Docker volumes (with confirmation)"
    set -l volumes (docker volume ls -q)

    if test -z "$volumes"
        echo "No volumes to remove."
        return 0
    end

    echo "⚠️  WARNING: This will permanently delete all data in Docker volumes!"
    echo ""
    echo "The following volumes will be removed:"
    docker volume ls --format "table {{.Name}}\t{{.Driver}}"
    echo ""

    read -l -P "Are you ABSOLUTELY sure you want to remove all volumes? [y/N] " confirm

    if test "$confirm" = "y" -o "$confirm" = "Y"
        read -l -P "Type 'DELETE' to confirm: " final_confirm

        if test "$final_confirm" = "DELETE"
            docker volume rm $volumes
            echo "✅ All volumes removed."
        else
            echo "❌ Aborted."
        end
    else
        echo "❌ Aborted."
    end
end
