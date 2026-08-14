# Container listing — name, image, status, ports.
# Version 1.0.0 | 14.08.2026

function dps --description 'Docker containers as a table'
    __ownerp_docker_ps $argv
end
