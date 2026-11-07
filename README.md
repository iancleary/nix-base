# nix-base

A reproducible bundle of stable command-line tools and slow-moving shell
configuration for macOS and Linux, delivered as a single Nix package.

One `nix profile add` installs the same curated tools, prompt, tmux settings,
Git defaults, and helper executables on every machine. Home Manager and NixOS
can install the same bundle through one-line modules. Everything is pinned by
this repository's `flake.lock`, so each machine runs the exact versions that
were reviewed here.

## Quick start

Requires Nix with flakes enabled.

```sh
# Review what is already in your profile.
nix profile list

# Install a reviewed commit. Replace <commit> with a full Git commit ID or a
# release tag such as 2026.11.07.00.
nix profile add 'github:iancleary/nix-base?rev=<commit>'
```

The bundle lands in your Nix profile. Put the profile `bin/` on `PATH` and link
the configuration files from `share/nix-base/` into `$HOME` as described in
[Use the configuration files](#use-the-configuration-files). The bundle never
writes to `$HOME` on its own.

### Home Manager

```nix
inputs.nix-base.url = "github:iancleary/nix-base/<commit>";

# In your Home Manager configuration:
imports = [ inputs.nix-base.homeManagerModules.default ];
```

The module sets only `home.packages`.

### NixOS

```nix
inputs.nix-base.url = "github:iancleary/nix-base/<commit>";

# In your NixOS configuration:
imports = [ inputs.nix-base.nixosModules.default ];
```

The module sets only `environment.systemPackages`.

Both modules install the bundle built from this repository's own lock. Do not
set `inputs.nix-base.inputs.nixpkgs.follows`; that would swap in the consumer's
Nixpkgs and defeat the pinning.

## What you get

### Command-line tools

The selection lives in `package-names.nix`:

```text
age bat delta eza fd fzf git git-lfs gum jq lazygit ripgrep shellcheck sops zoxide zsh-powerlevel10k
```

Each tool ships with its manual pages and shell completions. The bundle
deliberately excludes language runtimes, developer package managers, fonts, and
fast-moving tools. Use mise or your OS package manager for those.

### Helper executables

Scripts tracked in `bin/` are installed next to the tools:

| Executable | Purpose |
| --- | --- |
| `git-targets` | Multi-account Git helper. `list`, `clone <key> <repo>`, `login`, `status`, and `migrate` route repositories to the right identity using a TSV table you supply. |
| `moshi-status`, `moshi-upgrade`, `moshi-upgrade-preview`, `moshi-maintenance` | Status and upgrade commands for the Moshi Homebrew formula, backed by `libexec/moshi-maintenance.py`. |
| `code`, `code.exe` | Launch VS Code from macOS or from WSL. |
| `vivado`, `vivado.exe` | Launch Vivado from WSL. |
| `powershell`, `powershell.exe` | Launch PowerShell from WSL. |

Configuration for these executables is through environment variables:

| Variable | Effect |
| --- | --- |
| `GIT_TARGETS_TABLE` | Path to the account table. Defaults to `$XDG_CONFIG_HOME/git-targets/targets.tsv`. Columns: `key`, `directory`, `host`, `username`, `email`, `login`, `gitconfig`, `credential`, `tool`. Gitconfig paths resolve relative to the table. |
| `MOSHI_BREWFILE` | Read the Moshi tap and formula from a marked Brewfile instead of the upstream `rjyo/moshi` defaults. |
| `MACOS_VSCODE_LAUNCHER`, `WSL_VSCODE_LAUNCHER`, `VIVADO_LAUNCHER` | Override the program each launcher executes. |

The account table, credentials, and any identity data live outside this
repository. Nothing in the bundle contains them.

### Configuration files

`share/nix-base/` holds startup files that change rarely:

| File | Contents |
| --- | --- |
| `zshenv` | Environment for login and non-interactive Zsh. |
| `zshrc` | Interactive Zsh setup: completions, Powerlevel10k, zoxide, fzf, and the worktree helpers. |
| `p10k.zsh` | Powerlevel10k prompt configuration. |
| `tmux.conf` | Shared tmux settings. |
| `worktrees.sh` | `ga` and `gd`, helpers that create and remove Git worktrees. Sourceable from Bash or Zsh. `gd` confirms through `gum`. |
| `gitconfig` | Public Git defaults: `merge.conflictStyle`, delta as pager and diff filter, and delta options. No identity. |

## Use the configuration files

Link or include the bundled files from your own dotfiles. The installed path
looks like
`~/.local/state/nix/profiles/profile/share/nix-base/<file>`.

| Bundled file | Typical wiring |
| --- | --- |
| `zshenv`, `zshrc` | Symlink `~/.zshenv` and `~/.zshrc` to them, or source them from your own files. |
| `p10k.zsh` | Nothing to do. `zshrc` sources it unless `~/.p10k.zsh` exists, which takes precedence. |
| `tmux.conf` | Add `source-file <path>` to `~/.config/tmux/tmux.conf`. |
| `gitconfig` | Add `[include] path = <path>` to `~/.gitconfig`, then keep your name, email, and credential settings in `~/.gitconfig`. |

Machine-specific and personal settings go in files the bundle looks for but
does not ship:

| Hook | Sourced by |
| --- | --- |
| `~/.config/dotfiles/local.zshenv` | `zshenv`, for environment on every shell |
| `~/.config/dotfiles/login.sh` | `zshenv`, for login setup such as activating mise |
| `~/.config/dotfiles/local.zsh` | `zshrc`, for interactive extras and host-only aliases |
| `~/.p10k.zsh` | `zshrc`, to replace the bundled prompt configuration |
| `~/.config/tmux/local.conf` | `tmux.conf`, for host-only tmux settings |

Missing hooks are skipped silently.

## Supported platforms

| Nix system | Machines |
| --- | --- |
| `aarch64-darwin` | Apple silicon Macs |
| `x86_64-linux` | x86-64 Linux |
| `aarch64-linux` | ARM64 Linux, including DGX Spark |

## Updating and rolling back

Pin a specific commit or release tag and move it deliberately. A pinned
install never changes on its own. To update, remove the old entry and add the
new revision:

```sh
nix profile remove nix-base
nix profile add 'github:iancleary/nix-base?rev=<new-commit>'
```

Return to the previous generation if something breaks:

```sh
nix profile rollback
```

Home Manager and NixOS users roll back through their normal generation tools.

The flake tracks the FlakeHub `NixOS/nixpkgs/0.2605` stream. `flake.lock`
records the exact Nixpkgs revision. Tool upgrades are `flake.lock` changes and
selection changes are `package-names.nix` changes, both reviewed through pull
requests and verified on all three platforms before release.

## Development

Requires Nix with flakes enabled and Python 3.9 or later. `just` is optional.

```sh
bash scripts/check.sh   # or: just check
nix build .             # or: just build
```

`scripts/check.sh` audits tracked files and staged blobs for fonts and stray
dependencies, then runs `nix flake check --all-systems --no-build`. Stage new
files before running it. CI runs the same audit, package builds, flake checks,
and adapter contract tests natively on all three platforms.

[The CI workflow](.github/workflows/check.yml) configures Nix download retries
through the installer's `extra-conf`: up to 10 attempts per download, a 15
second connect timeout, and a 60 second stalled-download timeout. These cover
Nix fetches only. If retries are exhausted, read the failing URL in the job log
and rerun; do not edit `flake.lock` or skip checks to route around an outage.

## Releases

Releases are tags of the form `YYYY.MM.DD.XX`, starting at `.00` each day in
`America/Phoenix`. A release tags a verified `main` commit and publishes GitHub
release notes; it does not change the package selection or the lockfile.

Release tooling needs Python 3.11 or later and uv. The recipes are
`just release-check`, `just release-plan`, `just release-dry-run`, and
`just cut-release`. See [docs/release.md](docs/release.md) for the full
process, guards, and recovery steps.

## License

MIT. See [LICENSE](LICENSE).
