# three-pillars commit guard — sentinel body (v1), inserted after the shebang
# of pre-commit and commit-msg. POSIX sh; no set -e; the caller does
# `_tp_commit_guard <hook> "$@" || exit $?`, so a refusal's rc blocks the commit
# and a pass falls through to the hook's own lines (a husky-style `exit` or an
# `exec`-terminated hook never returns, which is why the block runs first).
#
# The body resolves the framework from the tp-root pointer
# `<git-common-dir>/three-pillars/tp-root` (written by
# commit_guard.record_tp_root; absolute, so the hook's cwd and an inherited
# GIT_DIR do not matter) and runs the guard's dispatcher in-process.
# Unreachable plugin (an upgrade moved the cache path) or no python3: one loud
# line and rc 0 — never block the user's commits because the plugin is gone.
_tp_commit_guard() {
  _tg_hook="$1"
  shift
  _tg_common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
  if [ -z "$_tg_common" ] || [ ! -f "$_tg_common/three-pillars/tp-root" ]; then
    echo "three-pillars commit guard: tp-root pointer missing — commit NOT checked (run any /tp-* skill to refresh)"
    return 0
  fi
  _tg_root=$(cat "$_tg_common/three-pillars/tp-root" 2>/dev/null)
  if [ -z "$_tg_root" ] || [ ! -f "$_tg_root/skills/_shared/commit_guard.py" ]; then
    echo "three-pillars commit guard: plugin not found at $_tg_root — commit NOT checked (run any /tp-* skill to refresh)"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || {
    echo "three-pillars commit guard: python3 not found — commit NOT checked (run any /tp-* skill to refresh)"
    return 0
  }
  python3 "$_tg_root/skills/_shared/commit_guard.py" run "$_tg_hook" "$@"
  return $?
}
