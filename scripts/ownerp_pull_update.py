#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ==============================================================================
# Title:            ownerp_pull_update.py
# Description:      Fetches update jobs from the release manager (pull update)
#                   and carries them out with update_docker_odoo.py
# Version:          1.0.0
# Date:             14.10.2026
# Author:           Equitania Software GmbH
# ==============================================================================
#
# The release manager never connects to this server. This script asks it, every
# few minutes from cron, whether an update is due for one of the instances here:
#
#   GET  <url>/rm/api/v1/job                 -> 204 nothing to do, 200 a job
#   POST <url>/rm/api/v1/runs/<id>/start
#   POST <url>/rm/api/v1/runs/<id>/finish    {"exit_code": n, "log": "..."}
#
# Every instance authenticates with its own update token (Authorization: Bearer).
# A job holds data only - database name, Odoo version, image, kernel and module
# zip files with their download addresses - never a command. This script checks
# every value against this server's own configuration before using it, writes a
# release file and hands the work to update_docker_odoo.py --release-file, the
# same runner an operator uses with doup.
#
# Configuration, in the central .env (/root/.config/myodoo-docker/.env, 0600):
#
#   RM_PULL_URL=https://releasemanager.example.com
#   RM_PULL_TOKEN_<CONTAINER>=<token>     one per instance; <CONTAINER> is the
#                                         container_name from docker2update.yaml,
#                                         upper case, every other character "_"
#   RM_PULL_MODULE_HOST=modules.example.com   optional: host the zip files may
#                                         come from (default: host of RM_PULL_URL)
#   RM_PULL_IMAGE_PREFIX=myodoo/          optional: allowed image repository prefix
#
# Without RM_PULL_URL or without any token the script does nothing and prints
# nothing, so the cron line can be present on every server.
#
# Exit codes: 0 nothing to do or all jobs done, 1 a job failed or was refused,
# 2 configuration error.
#
##############################################################################
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError:  # pragma: no cover - depends on the machine
    yaml = None

SCRIPT_VERSION = "1.0.0"
SCRIPT_DATE = "14.10.2026"

HOME = os.path.expanduser("~")
ENV_PATHS = ("/root/.config/myodoo-docker/.env", os.path.join(HOME, ".env"))
UPDATE_CONFIG = os.path.join(HOME, "docker2update.yaml")
UPDATE_RUNNER = os.path.join(HOME, "update_docker_odoo.py")
LOCK_PATH = "/run/lock/ownerp_pull_update.lock"
WORK_DIR = os.path.join(HOME, ".cache", "ownerp_pull_update")

HTTP_TIMEOUT = 60
UPDATE_TIMEOUT = 4 * 3600
LOG_LIMIT = 900 * 1024  # the release manager keeps 1 MB; leave room for the header

IMAGE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_./-]*:[a-zA-Z0-9_.-]+$")
ZIP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*\.zip$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PROXY_KEYS = ("http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")


class Refused(Exception):
    """A job that does not fit this server. Reported, never carried out."""


# ------------------------------------------------------------------ config
def read_env(paths=ENV_PATHS):
    """KEY=VALUE lines of the first .env that exists; comments and blanks skipped."""
    for path in paths:
        if os.path.isfile(path):
            values = {}
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip().strip('"').strip("'")
            return values
    return {}


def token_key(container_name):
    return "RM_PULL_TOKEN_" + re.sub(r"[^A-Z0-9]", "_", container_name.upper())


def load_containers(path=UPDATE_CONFIG):
    if yaml is None:
        raise SystemExit("PyYAML is missing: apt install python3-yaml")
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [c for c in data.get("containers") or [] if isinstance(c, dict) and c.get("container_name")]


def configured_instances(env, containers):
    """[(container, token)] for every container that has an update token."""
    pairs = []
    for container in containers:
        token = env.get(token_key(container["container_name"]))
        if token:
            pairs.append((container, token))
    return pairs


def load_proxy_environment(path="/etc/environment"):
    """cron starts without the proxy that getScripts wrote to /etc/environment."""
    if any(os.environ.get(key) for key in PROXY_KEYS) or not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            key, _sep, value = line.strip().partition("=")
            if key in PROXY_KEYS and value:
                os.environ[key] = value.strip().strip('"')


# ------------------------------------------------------------------ http
def api(base_url, token, method, path, body=None):
    """(status, parsed JSON or None). Never raises for an HTTP status."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
    request.add_header("Authorization", "Bearer " + token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as error:
        return error.code, None


# ------------------------------------------------------------------ job
def check_job(job, container, env, base_url):
    """The release file lines for ``job``, or Refused with the reason.

    The release manager is trusted to say *what* to install, not *where from*
    or *for whom*: the database must be this container's, the image must come
    from the allowed repository, and every download must be a plain zip file
    under one base address on the allowed host.
    """
    if not isinstance(job, dict) or not isinstance(job.get("run_id"), int):
        raise Refused("malformed job")
    if job.get("instance") != container.get("database_name"):
        raise Refused(
            "job is for database %r, container %s serves %r"
            % (job.get("instance"), container["container_name"], container.get("database_name"))
        )
    wanted = str(container.get("odoo_version") or "")
    if job.get("odoo_version") and wanted and str(job["odoo_version"]).split(".")[0] != wanted.split(".")[0]:
        raise Refused("job is for Odoo %s, container runs %s" % (job["odoo_version"], wanted))
    image = job.get("docker_image") or ""
    prefix = env.get("RM_PULL_IMAGE_PREFIX", "myodoo/")
    if not IMAGE_RE.match(image) or not image.startswith(prefix):
        raise Refused("image %r is not allowed (expected %s<name>:<tag>)" % (image, prefix))

    kernel = job.get("kernel") or {}
    entries = ([kernel] if kernel else []) + list(job.get("modules") or [])
    if not kernel:
        raise Refused("job has no kernel")
    allowed_host = env.get("RM_PULL_MODULE_HOST") or urllib.parse.urlsplit(base_url).hostname
    base = None
    for entry in entries:
        name, url = entry.get("zip") or "", entry.get("url") or ""
        if not ZIP_RE.match(name):
            raise Refused("not a plain zip file name: %r" % name)
        if not url.endswith("/" + name):
            raise Refused("address %r does not end in its file %s" % (url, name))
        entry_base = url[: -len(name)]
        base = base or entry_base
        if entry_base != base:
            raise Refused("downloads come from more than one base address")
        if entry.get("name") is not None and not NAME_RE.match(entry["name"]):
            raise Refused("not a module name: %r" % entry["name"])
    parts = urllib.parse.urlsplit(base)
    if parts.scheme != "https" or parts.hostname != allowed_host:
        raise Refused("downloads must come from https://%s, not %s" % (allowed_host, base))
    return [base.rstrip("/"), image, kernel["zip"]] + [m["zip"] for m in job.get("modules") or []]


def run_update(container, release_lines, run_id, runner=UPDATE_RUNNER):
    """(exit code, output) of update_docker_odoo.py for this release."""
    os.makedirs(WORK_DIR, mode=0o700, exist_ok=True)
    handle, path = tempfile.mkstemp(prefix="run-%d-" % run_id, suffix=".release", dir=WORK_DIR)
    with os.fdopen(handle, "w", encoding="utf-8") as release:
        release.write("\n".join(release_lines) + "\n")
    command = [
        sys.executable,
        runner,
        "-s",
        container["container_name"],
        "--release-file",
        path,
        "--comment",
        "pull update run %d" % run_id,
    ]
    try:
        done = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=UPDATE_TIMEOUT
        )
        return done.returncode, done.stdout
    except subprocess.TimeoutExpired as expired:
        return 124, (expired.stdout or "") + "\nupdate_docker_odoo.py did not finish within %d s" % UPDATE_TIMEOUT
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def tail(text, limit=LOG_LIMIT):
    if len(text) <= limit:
        return text
    return "[first %d characters dropped]\n" % (len(text) - limit) + text[-limit:]


def process_instance(container, token, env, base_url, runner=UPDATE_RUNNER, out=print):
    """Fetch and carry out at most one job for one container. Returns 0 or 1."""
    name = container["container_name"]
    status, job = api(base_url, token, "GET", "/rm/api/v1/job")
    if status == 204:
        return 0
    if status != 200:
        out("%s: job request answered %s" % (name, status))
        return 1
    run_id = job.get("run_id") if isinstance(job, dict) else None
    try:
        release_lines = check_job(job, container, env, base_url)
    except Refused as refusal:
        out("%s: run %s refused: %s" % (name, run_id, refusal))
        if isinstance(run_id, int):
            api(base_url, token, "POST", "/rm/api/v1/runs/%d/start" % run_id)
            api(
                base_url,
                token,
                "POST",
                "/rm/api/v1/runs/%d/finish" % run_id,
                {"exit_code": 2, "log": "Refused by %s: %s" % (os.uname().nodename, refusal)},
            )
        return 1
    status, _ = api(base_url, token, "POST", "/rm/api/v1/runs/%d/start" % run_id)
    if status != 204:
        out("%s: run %d could not be started (%s)" % (name, run_id, status))
        return 1
    out("%s: run %d started (%d modules, image %s)" % (name, run_id, len(release_lines) - 3, release_lines[1]))
    started = time.time()
    exit_code, output = run_update(container, release_lines, run_id, runner=runner)
    header = "ownerp_pull_update.py %s, run %d, %s, %.0f s, exit %d\n" % (
        SCRIPT_VERSION,
        run_id,
        name,
        time.time() - started,
        exit_code,
    )
    status, _ = api(
        base_url, token, "POST", "/rm/api/v1/runs/%d/finish" % run_id, {"exit_code": exit_code, "log": header + tail(output)}
    )
    out("%s: run %d finished with exit %d (reported: %s)" % (name, run_id, exit_code, status))
    return 0 if exit_code == 0 and status == 204 else 1


# ------------------------------------------------------------------ main
def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="Fetch and carry out update jobs from the release manager.")
    parser.add_argument("--check", action="store_true", help="Show which instances are configured; contacts nobody")
    parser.add_argument("--version", action="version", version="%(prog)s " + SCRIPT_VERSION)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_arguments(argv)
    env = read_env()
    base_url = env.get("RM_PULL_URL", "")
    if not base_url:
        if args.check:
            print("RM_PULL_URL is not set in the central .env - pull update is off.")
        return 0
    if not base_url.startswith("https://"):
        print("RM_PULL_URL must be an https:// address")
        return 2
    try:
        instances = configured_instances(env, load_containers())
    except (OSError, yaml.YAMLError if yaml else OSError) as error:
        print("Cannot read %s: %s" % (UPDATE_CONFIG, error))
        return 2
    if args.check:
        print("Release manager: %s" % base_url)
        if not instances:
            print("No instance has an update token (RM_PULL_TOKEN_<CONTAINER>).")
        for container, token in instances:
            print("  %s (database %s) token …%s" % (container["container_name"], container.get("database_name"), token[-4:]))
        return 0
    if not instances:
        return 0

    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # the previous run is still updating; cron comes back
        load_proxy_environment()
        result = 0
        for container, token in instances:
            try:
                result |= process_instance(container, token, env, base_url)
            except (urllib.error.URLError, OSError, ValueError) as error:
                print("%s: %s" % (container["container_name"], error))
                result = 1
        return result


if __name__ == "__main__":
    sys.exit(main())
