#!/usr/bin/env bash
# resolve_root.sh — locate the three-pillars framework root directory.
#
# Prints one absolute path on stdout (exit 0) or one failure line on stderr (exit 1).
#
# Usage:
#   bash skills/_shared/resolve_root.sh [--skill-dir <dir>]
#
# Probes (first hit wins):
#   1. $CLAUDE_PLUGIN_ROOT   — set by Claude Code for plugin skills
#   2. --skill-dir grandparent  — <dir>/../..  (probe 2)
#   3. Plugin-cache glob     — $HOME/.claude/plugins/cache/*/three-pillars*
#   4. Dev-checkout fallback — git rev-parse --show-toplevel of cwd
#
# A candidate qualifies iff skills/_shared/first-run.md exists inside it.
# The winner is passed through readlink -f to resolve symlinks.

set -eu

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SKILL_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
        --skill-dir)
            if [ $# -lt 2 ]; then
                echo "resolve_root.sh: --skill-dir requires a value" >&2
                exit 2
            fi
            SKILL_DIR="$2"
            shift 2
            ;;
        *)
            echo "resolve_root.sh: unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Sentinel predicate: a candidate qualifies iff this file exists inside it
# ---------------------------------------------------------------------------
SENTINEL_REL="skills/_shared/first-run.md"

_has_sentinel() {
    # $1 = candidate root path
    [ -f "$1/$SENTINEL_REL" ]
}

# ---------------------------------------------------------------------------
# Winner output: resolve symlinks and print
# ---------------------------------------------------------------------------
_output_winner() {
    # $1 = candidate path
    local resolved
    resolved="$(readlink -f "$1" 2>/dev/null)" || resolved="$1"
    printf '%s\n' "$resolved"
    exit 0
}

# ---------------------------------------------------------------------------
# Probe 1: $CLAUDE_PLUGIN_ROOT
# ---------------------------------------------------------------------------
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
    if _has_sentinel "${CLAUDE_PLUGIN_ROOT}"; then
        _output_winner "${CLAUDE_PLUGIN_ROOT}"
    fi
fi

# ---------------------------------------------------------------------------
# Probe 2: --skill-dir grandparent (<dir>/../..)
# ---------------------------------------------------------------------------
if [ -n "$SKILL_DIR" ]; then
    # grandparent: skill_dir/../../ resolves to two levels up
    grandparent="$(cd "$SKILL_DIR/../.." 2>/dev/null && pwd -P)" || grandparent=""
    if [ -n "$grandparent" ] && _has_sentinel "$grandparent"; then
        _output_winner "$grandparent"
    fi
fi

# ---------------------------------------------------------------------------
# Probe 3: plugin-cache glob $HOME/.claude/plugins/cache/*/three-pillars*
# ---------------------------------------------------------------------------
# Both the marketplace segment (*) and the plugin name (three-pillars*) are
# wildcarded to cover three-pillars and three-pillars-pro.
_probe3_winner=""
_probe3_mtime=-1  # floor -1 so mtime=0 is accepted as a valid candidate

_check_cache_entry() {
    # $1 = candidate path
    [ -d "$1" ] || return 0
    if _has_sentinel "$1"; then
        # Get mtime (seconds since epoch) of the sentinel file for tiebreak
        _mtime=""
        if command -v stat >/dev/null 2>&1; then
            # Try GNU stat first, then BSD stat
            _mtime="$(stat -c '%Y' "$1/$SENTINEL_REL" 2>/dev/null)" \
                || _mtime="$(stat -f '%m' "$1/$SENTINEL_REL" 2>/dev/null)" \
                || _mtime="0"
        else
            _mtime="0"
        fi
        _mtime="${_mtime:-0}"
        if [ "$_mtime" -gt "$_probe3_mtime" ] 2>/dev/null; then
            _probe3_mtime="$_mtime"
            _probe3_winner="$1"
        fi
    fi
}

if [ -n "${HOME:-}" ] && [ -d "${HOME}/.claude/plugins/cache" ]; then
    # Iterate over matching paths: $HOME/.claude/plugins/cache/*/three-pillars*
    for _marketplace_dir in "${HOME}/.claude/plugins/cache/"*/; do
        [ -d "$_marketplace_dir" ] || continue
        for _plugin_dir in "${_marketplace_dir}"three-pillars*/; do
            [ -d "$_plugin_dir" ] || continue
            # Strip trailing slash for consistent sentinel check
            _plugin_path="${_plugin_dir%/}"
            _check_cache_entry "$_plugin_path"
        done
    done
fi

if [ -n "$_probe3_winner" ]; then
    _output_winner "$_probe3_winner"
fi

# ---------------------------------------------------------------------------
# Probe 4: git rev-parse --show-toplevel of cwd, sentinel-checked
# ---------------------------------------------------------------------------
_git_toplevel=""
_git_toplevel="$(git rev-parse --show-toplevel 2>/dev/null)" || _git_toplevel=""
if [ -n "$_git_toplevel" ] && _has_sentinel "$_git_toplevel"; then
    _output_winner "$_git_toplevel"
fi

# ---------------------------------------------------------------------------
# All probes missed
# ---------------------------------------------------------------------------
printf 'three-pillars: cannot locate the framework root — probed $CLAUDE_PLUGIN_ROOT, the skill directory, ~/.claude/plugins/cache/*/three-pillars*, and the current repo. Set CLAUDE_PLUGIN_ROOT to the plugin install root and re-run.\n' >&2
exit 1
