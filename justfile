default:
    @just --list

check:
    bash scripts/check.sh

build:
    nix build --no-write-lock-file --no-link .#default

release-check:
    uv run --script scripts/release.py check --json

release-plan:
    uv run --script scripts/release.py plan --json

release-dry-run:
    uv run --script scripts/cut_release.py --dry-run

cut-release:
    uv run --script scripts/cut_release.py --apply
