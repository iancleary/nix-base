#!/usr/bin/env bash
set -euo pipefail

# Name the failing command instead of failing silently.
trap 'status=$?; if (( status != 0 )); then printf "smoke: failed (exit %s): %s\n" "$status" "$BASH_COMMAND" >&2; fi' ERR

bundle="${1:?Usage: smoke.sh BUNDLE_PATH}"
for executable in age bat delta eza fd fzf git git-lfs gum jq lazygit rg shellcheck sops zoxide; do
  test -x "$bundle/bin/$executable"
done

# Tracked executables and their aliases ship in the same bundle.
for executable in clone code code.exe git-targets moshi-maintenance moshi-status \
  moshi-upgrade moshi-upgrade-preview powershell powershell.exe vivado vivado.exe; do
  test -x "$bundle/bin/$executable"
done
test -L "$bundle/bin/clone" && test "$bundle/bin/clone" -ef "$bundle/bin/git-targets"
test -L "$bundle/bin/code.exe" && test "$bundle/bin/code.exe" -ef "$bundle/bin/code"
test -L "$bundle/bin/powershell" && test "$bundle/bin/powershell" -ef "$bundle/bin/powershell.exe"
test -L "$bundle/bin/vivado.exe" && test "$bundle/bin/vivado.exe" -ef "$bundle/bin/vivado"

# Home configuration and the bundled maintenance procedure ride along.
for shared in share/nix-base/zshenv share/nix-base/zshrc share/nix-base/p10k.zsh \
  libexec/moshi-maintenance.py; do
  test -f "$bundle/$shared"
done
bash -n "$bundle/bin/git-targets" "$bundle/bin/clone" "$bundle/bin/code" \
  "$bundle/bin/vivado" "$bundle/bin/powershell.exe" "$bundle/bin/moshi-status" \
  "$bundle/bin/moshi-upgrade" "$bundle/bin/moshi-upgrade-preview" \
  "$bundle/bin/moshi-maintenance"

# The git account tool prints its usage without a configured table.
if "$bundle/bin/git-targets" >/dev/null 2>&1; then
  echo "git-targets without a table must not succeed" >&2
  exit 1
fi
usage_text="$($bundle/bin/git-targets 2>&1 || true)"
printf '%s\n' "$usage_text" | grep -q 'Usage: git-targets'

"$bundle/bin/age" --version
"$bundle/bin/bat" --version
"$bundle/bin/delta" --version
"$bundle/bin/eza" --version
"$bundle/bin/fd" --version
"$bundle/bin/fzf" --version
"$bundle/bin/git" --version
"$bundle/bin/git-lfs" version
"$bundle/bin/gum" --version
"$bundle/bin/jq" --version
"$bundle/bin/lazygit" --version
"$bundle/bin/rg" --version
"$bundle/bin/shellcheck" --version
"$bundle/bin/sops" --version --disable-version-check
"$bundle/bin/zoxide" --version

# Exercise the selected text tools, not just executable presence.
test "$(printf '%s\n' '{"base":"stable"}' | "$bundle/bin/jq" -r .base)" = stable
printf '%s\n' 'nix-base smoke test' | "$bundle/bin/rg" -q '^nix-base smoke test$'
