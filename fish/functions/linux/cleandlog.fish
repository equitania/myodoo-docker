# Trim Docker container logs.
# Version 1.0.0 | 14.08.2026
#
# Replaces an alias that could not do what its name said:
#   sudo sh -c "cat /dev/null > /var/lib/docker/containers/*/*-json.log"
# A redirect takes exactly one target while a glob yields many, so at best a
# single file was emptied and the rest were handed to `cat` as arguments. Where
# the pattern matched nothing — a relocated data-root, or the `local` log
# driver, whose files are not named *-json.log — sh passed the pattern through
# literally and the shell answered "Directory nonexistent" while trimming
# nothing at all. That is the failure mode this exists to end: a maintenance
# command that reports an error is recoverable, one that silently does nothing
# is not.
#
# Truncates, never deletes. Rotated logs (*-json.log.1) are emptied too rather
# than removed — the file belongs to the daemon, and unlinking it under a
# running container leaves a writer holding a handle to nothing.
#
# The find arguments are single-quoted throughout: fish expands an unquoted
# glob before find ever sees it, and `{}` unquoted is a brace expansion.

function cleandlog --description 'Truncate Docker container logs'
    argparse 'n/dry-run' -- $argv
    or return 1

    if not command -q docker
        echo "cleandlog: docker not found" >&2
        return 127
    end

    # The data-root is a daemon setting, not a constant. Hard-coding
    # /var/lib/docker is exactly why the old alias failed on this host.
    set -l root (docker info --format '{{.DockerRootDir}}' 2>/dev/null)
    if test -z "$root"
        set root /var/lib/docker
        echo "cleandlog: docker info unavailable, assuming $root" >&2
    end

    set -l dir $root/containers
    if not sudo test -d $dir
        echo "cleandlog: $dir does not exist" >&2
        return 1
    end

    # json-file driver: <id>-json.log · local driver: local-logs/container.log
    set -l match '(' -name '*-json.log*' -o -name 'container.log*' ')'

    set -l stats (sudo find $dir -type f $match -printf '%s\n' \
        | awk '{n++; s+=$1} END {printf "%d %d\n", n+0, s+0}')
    set -l parts (string split ' ' -- $stats)
    set -l count $parts[1]
    set -l bytes $parts[2]

    if test "$count" -eq 0
        echo "cleandlog: no container logs under $dir"
        return 0
    end

    set -l human "$bytes bytes"
    if command -q numfmt
        set human (numfmt --to=iec --suffix=B $bytes)
    end

    if set -q _flag_dry_run
        echo "cleandlog: would free $human in $count log file(s) under $dir"
        return 0
    end

    if not sudo find $dir -type f $match -exec truncate -s 0 '{}' +
        echo "cleandlog: truncate failed" >&2
        return 1
    end

    echo "cleandlog: freed $human in $count log file(s)"
end
