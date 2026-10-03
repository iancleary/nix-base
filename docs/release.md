# Release process

Releases publish a Git tag and a GitHub release for `iancleary/nix-base`.
They do not change manifests, `flake.lock`, or a `VERSION` file.

## Version policy

Use `YYYY.MM.DD.XX` without a `v` prefix. The first release of each day ends in
`.00`. Further releases increment the two-digit suffix through `.99`. Stop if
that day's suffix is exhausted.

The date comes from `America/Phoenix`, regardless of the machine's time zone.
The helper reads both local tags and remote `origin` tags. Remote queries use
`git ls-remote`; version queries do not fetch or mutate Git state.

```sh
uv run scripts/cut_release.py --print-current-version
uv run scripts/cut_release.py --print-next-version
uv run scripts/cut_release.py --validate-version VERSION
```

Replace uppercase placeholders with reviewed values. Validation rejects a
version that does not match the repository's calendar policy. A new version
must use the next serial for its selected date, including `.00` for a new day.
Existing valid tags pass version validation so that exact resume can work.
Normal publication still rejects an existing tag. Explicit versions can select
a different date for a reviewed backfill, but cannot skip that date's serial.

## Prerequisites and release gate

Use Python 3.11 or later, uv, Git, Nix with flakes enabled, and authenticated
`gh` access to the repository. Keep uv installed through mise or a native
package manager. Do not add it to the stable bundle.

The release runner requires all of these conditions:

- The working tree is clean and the branch is `main`.
- All `origin` fetch and push URLs identify `iancleary/nix-base`.
- GitHub CLI publication resolves to the same public repository.
- Local `HEAD` is exactly the current remote `main` commit.
- `bash scripts/check.sh` passes.
- The latest `check.yml` push run for that `main` commit succeeds.
- The run includes successful `check (aarch64-darwin)`,
  `check (x86_64-linux)`, and `check (aarch64-linux)` native jobs.

`scripts/check_release_ci.py` verifies remote and CI state. CI selects Python
3.11 for local checks. If the workstation's system Python is older, use:

```sh
uv run --python 3.11 -- bash scripts/check.sh
```

Dry runs and resume enforce the same release gate. A failed or missing check
blocks publication. Repair the failure and repeat the checks.

## Plan and dry run

Use the checked-in `release.toml` contract through the repo-local runner:

```sh
uv run scripts/release.py check --json
uv run scripts/release.py plan --json
```

`check` reports readiness for the configured checks. `plan` queries the version
and reports `version`, `target_commit`, and `config_sha256`. Planning does not
run checks or validate GitHub CLI authentication. Version queries contact
`origin` and can use its configured Git authentication. Its `ready` value is `null` and
`checks_verified` is `false`; use its exit status to assess planning success.

Copy the plan's values into a guarded dry run:

```sh
uv run scripts/release.py run --dry-run --version VERSION --expected-head COMMIT --expected-config SHA256 --json
```

The guards reject a changed commit or release contract. The dry run checks the
selected version and publication preconditions without creating a tag,
pushing, or creating a GitHub release. Review its output before publication.

The convenience helper defaults to a dry run:

```sh
uv run scripts/cut_release.py --dry-run
```

It also accepts `--version`, `--notes-file`, `--expected-head`, and
`--expected-config`. Use explicit guarded values for an approved release.

## Publish

Publication requires authorization for the selected release. Reuse the exact
version, commit, and contract checksum from the reviewed dry run:

```sh
uv run scripts/release.py run --apply --version VERSION --expected-head COMMIT --expected-config SHA256 --json
```

The convenience form is `uv run scripts/cut_release.py --apply`, with the
reviewed guarded values supplied as needed. The explicit `--apply` flag is
required to publish.

Checks run before publication. The runner creates the tag at the verified
commit, pushes only that tag, then creates the GitHub release. It does not push
the branch or create a version commit.

GitHub-generated notes are the default. For curated notes, commit a Markdown
file inside this repository and pass `--notes-file PATH` to both the dry run
and apply command. Keep its path and content unchanged between those commands.

## Recover partial publication

If tag push succeeded but GitHub release creation failed, inspect the remote
tag and its commit before resuming. Resume requires the tagged commit to
remain the current local and remote `main` commit and pass the normal gate.

```sh
uv run scripts/release.py run --dry-run --resume --version VERSION --expected-head TAG_COMMIT --json
uv run scripts/release.py run --apply --resume --version VERSION --expected-head TAG_COMMIT --json
```

Resume reruns checks and completes GitHub publication. It does not move tags,
push, or create commits. An already published matching release is a no-op.
Conflicting tags, drafts, and authentication or API errors stop the operation.

If `main` has advanced, the remote tag is missing, or publication failed before
tag push, stop for manual review. Do not bypass the current-main gate or retag
another commit.

## Maintain the workflow

Use `create-release-process` for workflow changes. Use `cut-release` and
`release-runner` for ordinary execution. Keep `release.toml`,
`scripts/cut_release.py`, `scripts/check_release_ci.py`, and checks aligned with
this document.

`scripts/release.py` is vendored unchanged from
[`iancleary/release-skills`](https://github.com/iancleary/release-skills/tree/1357ca075b4c214cccf798a910f7348e238acd51)
at commit `1357ca075b4c214cccf798a910f7348e238acd51`. The `[runner_source]` table
records that commit and the file's SHA-256. Each contract load verifies the
local file against the checksum. The checksum detects local drift; it does
not verify the upstream source online.

Keep consumer policy in TOML and small helpers. To update the runner, review an
explicit upstream commit, copy the unchanged file, record its provenance, and
run the local checks and isolated release contract tests before promotion.
