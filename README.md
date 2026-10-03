# nix-base

A small, reproducible CLI foundation for macOS and Linux.

This repository owns a shared package selection and its `flake.lock`. It exports
one package bundle. Workstations can install the bundle directly. Home Manager
and NixOS can install the same bundle through minimal adapters.

## Package selection

`package-names.nix` is the source of truth:

```text
age bat delta eza fd fzf git git-lfs gum jq lazygit ripgrep shellcheck sops zoxide
```

These are stable command-line tools. Update the selection deliberately. Keep
developer package managers, language runtimes, and fast-moving tools in mise.

## Supported platforms

| Nix system | Machines |
| --- | --- |
| `aarch64-darwin` | Apple silicon Macs |
| `x86_64-linux` | Linux development machines |
| `aarch64-linux` | ARM64 Linux machines, including DGX Spark |

The bundle includes executables, manual pages, and shell completions. It does
not configure shell startup or activate completions. Dotfiles own that work.

## Ownership

| Repository or tool | Responsibility |
| --- | --- |
| `nix-base` | Stable CLI packages and their dependency lock |
| `dotfiles` | Editable shell, Git, terminal, and editor configuration |
| mise | Developer package managers, runtimes, and frequently updated tools |
| Native package manager | OS packages, desktop applications, and services |
| `nix-fleet` | NixOS appliances, host services, and fleet operations |

This repository contains no fonts, font inputs, personal configuration,
credentials, machine identities, or GPU drivers. Berkeley Mono is private and
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

Dotfiles must expose the Nix user profile on `PATH`. This repository does not
change shell startup files or install Nix.

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

Required tools are Nix with flakes enabled and Python 3. `just` is optional and
can be installed through mise.

```sh
bash scripts/check.sh
nix build .
```

Equivalent wrappers are `just check` and `just build`.

The check script audits tracked working files and staged blobs for font assets
and extra dependencies. Stage new files before running it. It then
runs `nix flake check --no-write-lock-file --all-systems --no-build` to evaluate
all supported systems. A separate build selects the local system's checks.
CI builds and checks the three supported platforms on native runners.

Checks cover the bundle, executable smoke tests, ownership rules, and the
minimal adapter contracts. Keep these checks aligned with the public outputs.

## License

MIT. See [LICENSE](LICENSE).
