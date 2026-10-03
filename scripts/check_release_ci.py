#!/usr/bin/env python3
"""Require current main and successful native CI before release publication."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "iancleary/nix-base"
SYSTEMS = ("aarch64-darwin", "x86_64-linux", "aarch64-linux")
ORIGIN_RE = re.compile(
    r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
    r"iancleary/nix-base(?:\.git)?"
)


def output(repo: Path, *command: str) -> str:
    result = subprocess.run(command, cwd=repo, check=True, text=True,
                            capture_output=True, timeout=30)
    return result.stdout.strip()


def api(repo: Path, endpoint: str) -> dict:
    return json.loads(output(repo, "gh", "api", endpoint))


def remote_main(repo: Path) -> str:
    refs = output(repo, "git", "ls-remote", "--heads", "origin", "refs/heads/main")
    lines = refs.splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != ["refs/heads/main"]:
        raise ValueError("origin must have one main branch")
    return lines[0].split()[0]


def validate_run(run: dict, head: str) -> None:
    expected = {
        "head_sha": head, "head_branch": "main", "event": "push",
        "path": ".github/workflows/check.yml", "status": "completed",
        "conclusion": "success",
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError("latest check.yml push/main run must succeed at the release commit")
    if run.get("head_repository", {}).get("full_name") != REPOSITORY:
        raise ValueError("CI run must belong to iancleary/nix-base")
    if not isinstance(run.get("id"), int) or not isinstance(run.get("run_attempt"), int):
        raise ValueError("CI run is missing its id or attempt")


def validate_jobs(jobs: list[dict]) -> None:
    required = {f"check ({system})" for system in SYSTEMS}
    if len(jobs) != len(required) or {job.get("name") for job in jobs} != required:
        raise ValueError("CI must contain exactly the three required native platform checks")
    if any(job.get("status") != "completed" or job.get("conclusion") != "success"
           for job in jobs):
        raise ValueError("all native platform checks must complete successfully")


def check_ci(repo: Path = ROOT) -> None:
    if output(repo, "git", "status", "--short"):
        raise ValueError("release checks require a clean working tree")
    if output(repo, "git", "branch", "--show-current") != "main":
        raise ValueError("release checks require main")
    for args in (("remote", "get-url", "--all", "origin"),
                 ("remote", "get-url", "--push", "--all", "origin")):
        urls = output(repo, "git", *args).splitlines()
        if not urls or any(not ORIGIN_RE.fullmatch(url) for url in urls):
            raise ValueError("origin fetch and push URLs must point to iancleary/nix-base")
    if output(repo, "gh", "repo", "view", "--json", "url", "--jq", ".url") != (
        f"https://github.com/{REPOSITORY}"
    ):
        raise ValueError("GitHub CLI publication must resolve to iancleary/nix-base")
    head = output(repo, "git", "rev-parse", "HEAD")
    if head != remote_main(repo):
        raise ValueError("HEAD must equal the current origin/main commit")
    endpoint = (f"repos/{REPOSITORY}/actions/workflows/check.yml/runs"
                f"?head_sha={head}&branch=main&event=push&per_page=100")
    runs = api(repo, endpoint).get("workflow_runs", [])
    if not runs:
        raise ValueError("no check.yml push/main run exists for the release commit")
    run = max(runs, key=lambda item: item["id"])
    validate_run(run, head)
    jobs = api(repo, f"repos/{REPOSITORY}/actions/runs/{run['id']}/attempts/"
               f"{run['run_attempt']}/jobs?per_page=100")
    if jobs.get("total_count") != len(SYSTEMS):
        raise ValueError("CI job count differs from the required native platforms")
    validate_jobs(jobs.get("jobs", []))
    latest = api(repo, f"repos/{REPOSITORY}/actions/runs/{run['id']}")
    validate_run(latest, head)
    if latest["run_attempt"] != run["run_attempt"]:
        raise ValueError("CI attempt changed during release checks; run the checks again")
    if remote_main(repo) != head:
        raise ValueError("origin/main changed during release checks; create a new plan")
    print(f"native CI passed for {head}: {run['html_url']}")


if __name__ == "__main__":
    try:
        check_ci()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        print(f"release CI check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
