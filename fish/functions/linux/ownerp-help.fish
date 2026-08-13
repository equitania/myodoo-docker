# ownERP command overview
# Version 1.1.0 | 13.08.2026
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

    echo ""
    printf " %sownERP · command overview%s%s%44s%s\n" \
        (set_color --bold) $n $d "help" $n
    echo "$d$rule$n"
    __ownerp_help_row "Overview"    dostat "state of this server" doval    "check configs"
    __ownerp_help_row "Odoo update" doup   "update containers"  tui       "pick systems"
    __ownerp_help_row ""            wiz    "add an instance"    edup      "edit config"
    __ownerp_help_row "Backup"      dobk   "back up now"        edbk      "edit config"
    __ownerp_help_row ""            llbk   "list archives"      ""        ""
    __ownerp_help_row "Maintenance" docron "cron schedule"      ups       "update scripts"
    __ownerp_help_row ""            syspatch "system update"    ""        ""
    __ownerp_help_row "nginx"       ngxset "apply config"       'ngx!'    "test config"
    __ownerp_help_row ""            ngxr   "reload"             showcerts "certificates"
    __ownerp_help_row "Docker"      dps    "containers"         dpsall    "with details"
    __ownerp_help_row ""            dkvol  "volumes"            cleandlog "trim logs"
    echo "$d$rule$n"
    echo "$d Odoo per version: odoodev start 19 --dev   ·   every alias: alias$n"
    echo ""
end
