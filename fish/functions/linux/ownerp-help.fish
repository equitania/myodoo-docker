# ownERP command overview
# Version 1.7.0 | 29.09.2026
#
# Printed once per LOGIN (see conf.d/50-prompt.fish); `help` shows it again.
#
# Curated rather than generated: an auto-listing of every alias would be forty
# lines nobody reads, and the point of this panel is the dozen commands an
# operator actually needs at 3am. tests/test_fish_help.py checks that every
# command named here still exists, so the curation cannot rot into a lie.

# Column widths are fixed and the colour codes are separate printf arguments,
# so padding measures the text rather than the escape sequences. Hand-spaced
# echo lines drifted the moment a name like `showcerts` appeared.
function __ownerp_help_row --argument-names label cmd1 desc1 cmd2 desc2
    printf " %s%-13s%s %s%-9s%s %-19s %s%-10s%s %s\n" \
        (set_color cyan) $label (set_color normal) \
        (set_color --bold) $cmd1 (set_color normal) $desc1 \
        (set_color --bold) $cmd2 (set_color normal) $desc2
end

function ownerp-help --description "Show the ownERP command overview"
    set -l d (set_color brblack)
    set -l n (set_color normal)
    set -l rule " ──────────────────────────────────────────────────────────────────────"

    # getScripts' restricted mode (no root, no sudo): none of the server
    # commands below is installed for this user, so the panel names only what
    # works in their own account.
    if test -e $HOME/.getscripts_restricted
        __ownerp_help_restricted
        return
    end

    echo ""
    printf " %sownERP · command overview%s%s%44s%s\n" \
        (set_color --bold) $n $d "help" $n
    echo "$d$rule$n"
    __ownerp_help_row "Overview"    konsole "server console"     dostat    "same, as text"
    __ownerp_help_row ""            doval  "check configs"       ""        ""
    __ownerp_help_row "Odoo update" doup   "update containers"  wizup     "add an instance"
    __ownerp_help_row ""            edup   "edit config"        ""        ""
    __ownerp_help_row "Backup"      dobk   "back up now"        wizbk     "add a database"
    __ownerp_help_row ""            llbk   "list archives"      ""        ""
    __ownerp_help_row "Maintenance" docron "cron schedule"      ups       "update scripts"
    __ownerp_help_row ""            syspatch "system update"    ""        ""
    __ownerp_help_row "nginx"       ngxset "apply config"       'ngx!'    "test config"
    __ownerp_help_row ""            ngxr   "reload"             showcerts "certificates"
    __ownerp_help_row "Docker"      dps    "containers"         dpsall    "with details"
    __ownerp_help_row ""            dpi    "images"             dkvol     "volumes"
    __ownerp_help_row ""            cleandlog "trim logs"       ct        "live monitor"
    echo "$d$rule$n"
    # No odoodev line: that CLI belongs to workstation development, and this
    # panel is what an operator needs on a server at 3am.
    echo "$d every alias: alias$n"
    echo ""
end

function __ownerp_help_restricted --description "Command overview for getScripts' restricted mode"
    set -l d (set_color brblack)
    set -l n (set_color normal)
    set -l rule " ──────────────────────────────────────────────────────────────────────"

    echo ""
    printf " %sownERP · restricted mode%s%s%45s%s\n" \
        (set_color --bold) $n $d "help" $n
    echo "$d$rule$n"
    __ownerp_help_row "Shell"       ups    "update config"      help      "this overview"
    __ownerp_help_row "Files"       ll     "list files"         hg        "search history"
    if command -q zoxide
        __ownerp_help_row "Navigation" z   "jump to a dir"      zi        "pick a dir"
    end
    # Second tier: a user in the docker group gets the Odoo tools that need
    # nothing beyond Docker and their own home (getScripts delivers them).
    if test -x $HOME/update_docker_odoo.py
        __ownerp_help_row "Odoo update" doup "update containers"  wizup     "add an instance"
        __ownerp_help_row ""            edup   "edit config"        doval     "check configs"
        __ownerp_help_row "Backup"      dobk   "back up now"        wizbk     "add a database"
        __ownerp_help_row ""            edbk   "edit config"        llbk      "list archives"
        __ownerp_help_row "Docker"      dostat "server state"       dps       "containers"
        __ownerp_help_row ""            dpsall "with details"       dpi       "images"
    end
    __ownerp_help_row "Git"         gst    "status"             glog      "history graph"
    __ownerp_help_row ""            gl     "pull"               gd        "diff"
    if command -q fastfetch
        __ownerp_help_row "System"  ff     "system info"        ""        ""
    end
    echo "$d$rule$n"
    echo "$d system updates: your administrator (apt-get update, apt-get upgrade)$n"
    echo "$d every alias: alias$n"
    echo ""
end
