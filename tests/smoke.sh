#!/usr/bin/env bash
set -euo pipefail

bundle="${1:?Usage: smoke.sh BUNDLE_PATH}"
for executable in age bat delta eza fd fzf git git-lfs gum jq lazygit rg shellcheck sops zoxide; do
  test -x "$bundle/bin/$executable"
done

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
