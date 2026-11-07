# Interactive Git worktree helpers. Sourceable in Bash and Zsh. The bundle's
# zshrc sources this file; ga and gd change the calling shell's directory, so
# they cannot be bin/ executables. gd confirms through gum from this bundle.
function ga() {
  local branch="${1:-}"
  [[ -n "$branch" ]] || {
    printf 'Usage: ga BRANCH\n' >&2
    return 2
  }

  local main_worktree
  main_worktree="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  [[ -n "$main_worktree" ]] || {
    printf 'ga: unable to locate the main Git worktree\n' >&2
    return 1
  }
  [[ "$(pwd -P)" == "$main_worktree" ]] || {
    printf 'ga: run from the main worktree: %s\n' "$main_worktree" >&2
    return 1
  }

  local slug worktree_path
  slug="$(printf '%s' "$branch" | tr '/' '_')"
  worktree_path="../${slug}--$(basename "$main_worktree")"
  git worktree add -b "$branch" -- "$worktree_path" || return
  cd "$worktree_path" || return
}

function gd() {
  local main_worktree current_worktree branch slug expected_name
  main_worktree="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
  current_worktree="$(git rev-parse --show-toplevel)" || return
  [[ -n "$main_worktree" && "$current_worktree" != "$main_worktree" ]] || {
    printf 'gd: run from a linked Git worktree\n' >&2
    return 1
  }
  [[ "$(pwd -P)" == "$current_worktree" ]] || {
    printf 'gd: run from the linked worktree root: %s\n' "$current_worktree" >&2
    return 1
  }
  branch="$(git symbolic-ref --quiet --short HEAD)" || {
    printf 'gd: the worktree has no local branch\n' >&2
    return 1
  }
  slug="$(printf '%s' "$branch" | tr '/' '_')"
  expected_name="${slug}--$(basename "$main_worktree")"
  [[ "$(basename "$current_worktree")" == "$expected_name" ]] || {
    printf 'gd: this worktree was not created by ga: %s\n' "$current_worktree" >&2
    return 1
  }

  command -v gum >/dev/null || {
    printf 'gd: gum is required for confirmation\n' >&2
    return 1
  }
  gum confirm "Remove worktree '$current_worktree' and delete branch '$branch'?" || return 0
  cd "$main_worktree" || return
  git worktree remove -- "$current_worktree" || return
  git branch -D -- "$branch"
}
