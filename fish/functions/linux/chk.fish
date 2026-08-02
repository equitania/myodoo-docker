# Server Readiness Check Function
# Version 1.0.0 | 02.08.2026

function chk --description "Check whether this server is in the expected state"
    # Full report including the checks that passed. getScripts.py runs the same
    # script with --brief at the end of every `ups`; this is the on-demand view.
    # Needs root: reads /etc/cron.d, /etc/logrotate.d and root's crontab.
    sudo $HOME/server-readiness.py $argv
end
