# Docker Remove Images Function
# Version 1.0.0 | 28.01.2026

function dkrmi --description "Remove all Docker images (with confirmation)"
    set -l images (docker images -q)

    if test -z "$images"
        echo "No images to remove."
        return 0
    end

    echo "The following images will be removed:"
    docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
    echo ""

    read -l -P "Are you sure you want to remove all images? [y/N] " confirm

    if test "$confirm" = "y" -o "$confirm" = "Y"
        docker rmi $images
        echo "✅ All images removed."
    else
        echo "❌ Aborted."
    end
end
