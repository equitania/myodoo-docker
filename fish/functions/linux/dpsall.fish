# Container listing with details — adds ID, command and creation time.
# Version 1.0.0 | 14.08.2026

function dpsall --description 'Docker containers as a table, with details'
    __ownerp_docker_ps --details $argv
end
