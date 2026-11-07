# nix-base

A small, reproducible CLI foundation and slow-moving home configuration for
macOS and Linux.

This repository owns a shared package selection and its `flake.lock`. It exports
one package bundle: the selected command-line tools, a set of tracked host
executables, and slow-moving home configuration files. Workstations can install
the bundle directly. Home Manager and NixOS can install the same bundle through
minimal adapters. The dotfiles checkout owns the fast-moving and personal
parts: the git account table, per-account gitconfigs, `$HOME/.config` hooks,
and host-only settings, plus the deployment that links the bundle's files into
`$HOME`.

## Package selection

`package-names.nix` is the source of truth:

```text
age bat delta eza fd fzf git git-lfs gum jq lazygit ripgrep shellcheck sops zoxide zsh-powerlevel10k
```

These are stable command-line tools plus the Powerlevel10k prompt theme, which
the bundle's `zshrc` sources from `share/zsh-powerlevel10k`. Update the
selection deliberately. Keep
developer package managers, language runtimes, and fast-moving tools in mise.

## Supported platforms

| Nix system | Machines |
| --- | --- |
| `aarch64-darwin` | Apple silicon Macs |
| `x86_64-linux` | Linux development machines |
| `aarch64-linux` | ARM64 Linux machines, including DGX Spark |

The bundle includes executables, manual pages, shell completions, tracked host
executables, and the home configuration described below. Dotfiles own the
activation of completions and the deployment of the configuration files.

## Bundle contents

The default package is one `buildEnv` containing:

- `bin/`: the tools from `package-names.nix`, plus the tracked executables
  from this repository:
  - `git-targets`: the git account tool. It reads an account table
    (`key`, `directory`, `host`, `username`, `email`, `login`, `gitconfig`,
    `credential`, `tool`) from `$GIT_TARGETS_TABLE` or
    `$XDG_CONFIG_HOME/git-targets/targets.tsv`, and resolves the gitconfig
    files named by the table relative to the table's own directory. It provides
    `list`, `clone`, `login`, `status`, and `migrate`. Invoked as `clone`, it
    keeps the historical `clone <key> <repo>` form. The table and the
    gitconfigs live in the dotfiles checkout, which deploys the table to
    `~/.config/git-targets/targets.tsv`.
  - `moshi-status`, `moshi-upgrade`, `moshi-upgrade-preview`, and
    `moshi-maintenance`: the Moshi maintenance interface backed by
    `libexec/moshi-maintenance.py`. The procedure defaults to the upstream
    `rjyo/moshi` tap and `moshi-hook` formula; set `MOSHI_BREWFILE` to read
    them from a marked Brewfile instead.
  - `code` (macOS and Windows-VS-Code-under-WSL), `vivado` and
    `powershell.exe` (WSL): host launchers with environment-variable overrides
    (`MACOS_VSCODE_LAUNCHER`, `WSL_VSCODE_LAUNCHER`, `VIVADO_LAUNCHER`).
    `code.exe`, `powershell`, and `vivado.exe` alias the same scripts.
- `libexec/`: support programs used by the `bin/` executables.
- `share/nix-base/`: the home configuration files:
  - `zshenv`: login and non-interactive Zsh environment. It sources
    `$HOME/.config/dotfiles/local.zshenv` and `login.sh`, which dotfiles owns.
  - `zshrc`: interactive Zsh configuration. It sources
    `$HOME/.config/dotfiles/local.zsh`, which dotfiles owns. It does not source
    the dotfiles-owned `$HOME/.config/shell` helpers; the dotfiles checkout's
    own startup wrapper adds them.
  - `p10k.zsh`: the Powerlevel10k prompt configuration. The bundle `zshrc`
    sources it unless a host `~/.p10k.zsh` exists.
  - `tmux.conf`: the shared tmux settings. Dotfiles link `~/.config/tmux/tmux.conf`
    to a forwarder that sources this file. It sources the dotfiles-owned
    `~/.config/tmux/local.conf` for host-only settings.
  - `worktrees.sh`: the `ga` and `gd` Git worktree helpers, sourceable in Bash
    and Zsh. The bundle's `zshrc` sources it from the same directory. `gd`
    confirms through `gum` from this bundle.
  - `gitconfig`: public Git settings (`merge.conflictStyle`, the delta pager
    and diff filter, delta options). The dotfiles `~/.gitconfig` includes it;
    identity, directory includes, and credential routing stay there.

These files carry no identity, table, or secret content. The dotfiles checkout
links them into `$HOME` from the installed profile path, for example
`~/.local/state/nix/profiles/profile/share/nix-base/zshrc`.

## Ownership

| Repository or tool | Responsibility |
| --- | --- |
| `nix-base` | Stable CLI packages and their dependency lock; the Powerlevel10k theme; slow-moving home configuration, public Git settings, tmux settings, worktree helpers, and host launchers; the generic git account tool |
| `dotfiles` | Editable shell, Git, terminal, and editor configuration; the git account table and per-account gitconfigs; deployment into `$HOME` |
| mise | Developer package managers, runtimes, and frequently updated tools |
| Native package manager | OS packages, desktop applications, and services |
| `nix-fleet` | NixOS appliances, host services, and fleet operations |

This repository contains no fonts, font inputs, git account tables, per-account
gitconfigs, credentials, host identities, or secrets. Berkeley Mono is private and
must remain outside this repository and its Git history.

## Install the bundle

Use an existing Nix installation with flakes enabled. Inventory the current
owners of these tools first. Resolve duplicate packages before installing the
bundle. Do not replace an existing profile without reviewing its contents.

Inspect the current profile:

```sh
nix profile list
```

Choose a reviewed commit. Replace `<commit>` below with its full Git commit ID:

```sh
nix profile add 'github:iancleary/nix-base?rev=<commit>'
```

The dotfiles checkout exposes the Nix user profile on `PATH` and links the
bundle's home configuration into `$HOME`. This repository does not install
itself into `$HOME`.

## Home Manager and NixOS

Add the base as a pinned flake input:

```nix
inputs.nix-base.url = "github:iancleary/nix-base/<commit>";
```

For Home Manager, import:

```nix
imports = [ inputs.nix-base.homeManagerModules.default ];
```

For NixOS, import:

```nix
imports = [ inputs.nix-base.nixosModules.default ];
```

The Home Manager adapter sets only `home.packages`. The NixOS adapter sets only
`environment.systemPackages`. Both use the bundle built from this repository's
locked package set. They do not use the consumer's package versions.

Do not set `inputs.nix-base.inputs.nixpkgs.follows`. That would replace the
base's dependency selection with the consumer's selection.

## Update and rollback

Package updates require a reviewed `flake.lock` change. Package selection
changes require a reviewed `package-names.nix` change. Build and check an update
on all supported platforms before promoting it.

The flake uses FlakeHub's public `NixOS/nixpkgs/0.2605` stream. The lockfile
records the exact Nixpkgs revision selected from that stream.

Consumers update their pinned base commit explicitly. A dotfiles pull does not
update this bundle. A mise installation does not update this bundle.

Keep the previous profile generation until the new tools pass local checks.
Direct profile users can return to it with:

```sh
nix profile rollback
```

Home Manager and NixOS users use their normal generation rollback workflow.
This repository does not migrate machines or replace existing configurations.

## Development

Required tools are Nix with flakes enabled and Python 3.9 or later. `just`
is optional and can be installed through mise.

```sh
bash scripts/check.sh
nix build .
```

Equivalent wrappers are `just check` and `just build`.

The check script audits tracked working files and staged blobs for font assets
and extra dependencies. Stage new files before running it. It then
runs `nix flake check --no-write-lock-file --all-systems --no-build` to evaluate
all supported systems. A separate build selects the local system's checks.
CI checks only the base source audit, packages, flake, and adapter contracts
on the three native platforms. Release-tool tests run locally through
`release.toml`.

Checks cover the bundle, executable smoke tests, ownership rules, and the
minimal adapter contracts. Keep these checks aligned with the public outputs.

### CI network retries

[The native CI workflow](.github/workflows/check.yml) configures Nix's built-in
download retries through the installer action's `extra-conf`. Transient fetch
and binary-cache download failures get up to 10 attempts per download, with
Nix's backoff between attempts. Connections time out after 15 seconds; downloads
with no progress time out after 60 seconds so Nix can retry instead of hanging.
See [Nix's configuration reference](https://nix.dev/manual/nix/stable/command-ref/conf-file.html#conf-download-attempts).

Retries apply to Nix downloads, not the entire check script. Source audit,
evaluation, build, and smoke-test errors still fail CI. These settings take
effect after Nix installation; they do not control checkout, action downloads,
or the installer itself. Persistent network failures still fail after the
retry budget or the job's 30-minute timeout. If retries are exhausted, inspect
the failed URL and HTTP or connection error in the job log before rerunning;
do not change `flake.lock` or bypass checks to work around an outage.

## Releases

Releases use `YYYY.MM.DD.XX`, starting with `.00` each day in
`America/Phoenix`. They tag a verified commit and publish GitHub notes. They do
not change the package selection, lockfile, or a version file.

Release tooling needs Python 3.11 or later and uv from mise or a native
package manager. Use the repo-local runner. See [the release process](docs/release.md) for checks,
guarded dry runs, publication, and recovery.

## License

MIT. See [LICENSE](LICENSE).
