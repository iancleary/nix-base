default:
    @just --list

check:
    bash scripts/check.sh

build:
    nix build --no-write-lock-file --no-link .#default
