# Image listing — repository:tag, ID, size, age.
# Version 1.0.0 | 14.08.2026
#
# `docker images` on Docker 29 answers with DISK USAGE, CONTENT SIZE and EXTRA
# and no age at all, which is the question actually asked of an image list on a
# server. The renderer supplies it; the fallback keeps `dpi` working on a server
# where `ups` has not run yet, sorted with the header held back.

function dpi --description 'Docker images as a table, with their age'
    set -l renderer $HOME/docker_table.py

    if test -f $renderer; and command -q python3
        python3 $renderer --images $argv
        return $status
    end

    docker images --format "table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}" \
        | awk 'NR==1 {print; next} {print | "sort"}'
end
