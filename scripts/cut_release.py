#!/usr/bin/env -S uv run --script
# Adapted from iancleary/release-skills templates/release/scripts/calver_day_serial.py.
# /// script
# requires-python = ">=3.11"
# ///
"""Plan or publish a YYYY.MM.DD.XX tag-only release."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
RELEASE_TIMEZONE = "America/Phoenix"
VERSION_RE = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[0-9]{2}")


def validate_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"Release version must match YYYY.MM.DD.XX: {version}")
    year, month, day, _ = map(int, version.split("."))
    date(year, month, day)


def release_tags(tags: list[str]) -> list[str]:
    versions = []
    for tag in tags:
        try:
            validate_version(tag)
        except ValueError:
            continue
        versions.append(tag)
    return versions


def current_version(tags: list[str]) -> str:
    return max(release_tags(tags), default="")


def next_version(tags: list[str], today: date) -> str:
    stamp = today.strftime("%Y.%m.%d")
    serials = [int(tag.rsplit(".", 1)[1]) for tag in release_tags(tags)
               if tag.startswith(f"{stamp}.")]
    serial = max(serials, default=-1) + 1
    if serial > 99:
        raise ValueError(f"Release sequence exhausted for {stamp}; maximum is .99")
    return f"{stamp}.{serial:02d}"


def validate_selected_version(version: str, tags: list[str]) -> None:
    validate_version(version)
    if version in release_tags(tags):
        # The vendored runner rejects existing tags unless exact resume is requested.
        return
    year, month, day, _ = map(int, version.split("."))
    expected = next_version(tags, date(year, month, day))
    if version != expected:
        raise ValueError(f"New release version must be {expected} for the selected date")


def release_day() -> date:
    return datetime.now(ZoneInfo(RELEASE_TIMEZONE)).date()


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, text=True,
                            capture_output=True, timeout=30)
    return result.stdout.strip()


def local_remote_tags(repo: Path = ROOT) -> list[str]:
    tags = set(git_output(repo, "tag", "--list").splitlines())
    remote = git_output(repo, "ls-remote", "--tags", "--refs", "origin")
    for line in remote.splitlines():
        _, ref = line.split()
        if ref.startswith("refs/tags/"):
            tags.add(ref.removeprefix("refs/tags/"))
    return sorted(tags)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview; the default")
    mode.add_argument("--apply", action="store_true", help="Push a tag and publish a release")
    query = parser.add_mutually_exclusive_group()
    query.add_argument("--print-current-version", action="store_true")
    query.add_argument("--print-next-version", action="store_true")
    query.add_argument("--validate-version", metavar="YYYY.MM.DD.XX")
    parser.add_argument("--version", metavar="YYYY.MM.DD.XX")
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-config")
    args = parser.parse_args(argv)
    if (args.print_current_version or args.print_next_version or args.validate_version) and (
        args.dry_run or args.apply or args.version or args.notes_file
        or args.expected_head or args.expected_config
    ):
        parser.error("version queries cannot be combined with release arguments")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.validate_version:
        validate_version(args.validate_version)
        validate_selected_version(args.validate_version, local_remote_tags())
        return 0
    if args.print_current_version:
        print(current_version(local_remote_tags()))
        return 0
    if args.print_next_version:
        print(next_version(local_remote_tags(), release_day()))
        return 0

    if args.version:
        validate_version(args.version)
    tags = local_remote_tags()
    version = args.version or next_version(tags, release_day())
    validate_selected_version(version, tags)
    command = ["uv", "run", "--script", "scripts/release.py", "run",
               "--apply" if args.apply else "--dry-run", "--version", version, "--json"]
    for flag, value in (("--notes-file", args.notes_file),
                        ("--expected-head", args.expected_head),
                        ("--expected-config", args.expected_config)):
        if value is not None:
            command.extend([flag, str(value)])
    print(f"release version: {version}", file=sys.stderr)
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"release failed: {error}", file=sys.stderr)
        raise SystemExit(1)
