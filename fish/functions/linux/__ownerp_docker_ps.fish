# Container listing — the shared body behind dps and dpsall.
# Version 1.0.0 | 14.08.2026
#
# Two functions need this and fish autoloads one file per function name, so it
# lives in its own file rather than beside either of them.
#
# The fallback is not decoration: dps is typed on servers where `ups` has not
# run yet, and a listing that errors out because a renderer is missing is worse
# than an unframed one. It reproduces the pre-1.2.0 output, minus the defect
# that started all this — `awk` holds the header back and sorts only the rows.

function __ownerp_docker_ps --description 'docker ps as a table, with a fallback'
    set -l renderer $HOME/docker_table.py

    if test -f $renderer; and command -q python3
        python3 $renderer $argv
        return $status
    end

    set -l format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"
    if contains -- --details $argv
        set format "table {{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Command}}\t{{.CreatedAt}}\t{{.Status}}\t{{.Ports}}"
    end

    docker ps -a --format $format | awk 'NR==1 {print; next} {print | "sort"}'
end
