#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python3 scripts/check_source.py
python3 -B -m unittest discover -s tests -p 'test_source_audit.py'
bash -n scripts/check.sh tests/smoke.sh
nix flake check --no-write-lock-file --all-systems --no-build
native_system="$(nix eval --impure --raw --expr builtins.currentSystem)"
nix build --no-write-lock-file --no-link --print-build-logs \
  ".#checks.$native_system.package-policy" \
  ".#checks.$native_system.module-contract" \
  ".#checks.$native_system.smoke"
