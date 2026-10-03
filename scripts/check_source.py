#!/usr/bin/env python3
"""Audit the exact tracked source before building or publishing."""

import json
import re
import subprocess
import sys
from pathlib import Path

FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2", ".eot", ".dfont", ".bdf", ".pcf"}
FONT_SIGNATURES = (b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"wOFF", b"wOF2")
FLAKEHUB_NIXPKGS_URL = "https://flakehub.com/f/NixOS/nixpkgs/0.2605"
FLAKEHUB_PINNED_NIXPKGS_RE = re.compile(
    r"https://api\.flakehub\.com/f/pinned/NixOS/nixpkgs/0\.2605\.[0-9]+%2Brev-"
    r"([0-9a-f]{40})/[0-9a-f-]{36}/source\.tar\.gz"
)


def audit(root: Path) -> list[str]:
    errors = []
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root).decode().split("\0")
    snapshots = {}
    for entry in filter(None, entries):
        metadata, relative = entry.split("\t", 1)
        mode, blob, stage = metadata.split()
        if stage != "0":
            errors.append(f"unresolved index conflict: {relative}")
            continue
        path = root / relative
        if mode == "120000" or path.is_symlink():
            errors.append(f"source symlinks are not allowed: {relative}")
            continue
        if not path.is_file():
            errors.append(f"tracked source is missing: {relative}")
            continue
        snapshots[relative] = {
            path.read_bytes(),
            subprocess.check_output(["git", "cat-file", "blob", blob], cwd=root),
        }
        for data in snapshots[relative]:
            if path.suffix.lower() in FONT_SUFFIXES or data.startswith(FONT_SIGNATURES):
                errors.append(f"font asset is not allowed: {relative}")
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"tracked source must be UTF-8 text: {relative}")

    lock_path = root / "flake.lock"
    if not lock_path.is_file() or "flake.lock" not in snapshots:
        errors.append("tracked flake.lock is required")
        return errors
    for data in snapshots["flake.lock"]:
        nodes = json.loads(data)["nodes"]
        if set(nodes) != {"root", "nixpkgs"}:
            errors.append("only root and official nixpkgs may appear in the lock graph")
        if nodes.get("root", {}).get("inputs") != {"nixpkgs": "nixpkgs"}:
            errors.append("nixpkgs must be the only root dependency")
        nixpkgs = nodes.get("nixpkgs", {})
        original = nixpkgs.get("original", {})
        if (original.get("type"), original.get("url")) != ("tarball", FLAKEHUB_NIXPKGS_URL):
            errors.append("original dependency must be public NixOS/nixpkgs 26.05 from FlakeHub")
        locked = nixpkgs.get("locked", {})
        match = FLAKEHUB_PINNED_NIXPKGS_RE.fullmatch(locked.get("url", ""))
        if (locked.get("type") != "tarball" or match is None
                or match.group(1) != locked.get("rev")):
            errors.append("locked dependency must be the matching public NixOS/nixpkgs 26.05 FlakeHub source")
    return sorted(set(errors))


if __name__ == "__main__":
    failures = audit(Path(__file__).resolve().parents[1])
    for failure in failures:
        print(f"source audit: {failure}", file=sys.stderr)
    if failures:
        sys.exit(1)
    print("source audit: tracked files contain no font assets; only public nixpkgs is locked")
