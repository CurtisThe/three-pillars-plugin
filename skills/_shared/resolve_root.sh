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
# wildcarded to cover three-pillars and three-pillars-pro. Selection among
# multiple matches is DETERMINISTIC — the lexicographically-first matching
# path wins, never sentinel mtime (mtime silently tracks install/update
# order, so the same machine can resolve a different root on two different
# days with no visible signal) [catalog G6 fix]. When more than one entry
# matches, a loud warning naming every match and the chosen winner is
# printed to stderr — side-by-side `three-pillars*` distributions on one
# machine are worth surfacing, not silently resolving.
_probe3_matches=()

_check_cache_entry() {
    # $1 = candidate path — record it iff the sentinel lives directly inside
    [ -d "$1" ] || return 0
    if _has_sentinel "$1"; then
        _probe3_matches+=("$1")
    fi
}

_check_cache_tree() {
    # $1 = a three-pillars* plugin dir. The REAL Claude Code marketplace layout
    # nests the framework one level deeper under a version segment:
    #   cache/<marketplace>/<plugin>/<version>/skills/_shared/first-run.md
    # so the sentinel is NOT at the plugin dir itself. Check the plugin dir
    # (versionless/local installs) AND each immediate <version> subdir
    # (marketplace installs) — supporting BOTH shapes so a layout change can't
    # silently kill probe 3. [catalog G6 + plugin-mode-parity H2]
    local _base="${1%/}"
    _check_cache_entry "$_base"
    local _version_dir
    for _version_dir in "$_base"/*/; do
        [ -d "$_version_dir" ] || continue
        _check_cache_entry "${_version_dir%/}"
    done
}

if [ -n "${HOME:-}" ] && [ -d "${HOME}/.claude/plugins/cache" ]; then
    # Iterate over matching paths: $HOME/.claude/plugins/cache/*/three-pillars*
    # (then one level deeper for the versioned marketplace layout).
    for _marketplace_dir in "${HOME}/.claude/plugins/cache/"*/; do
        [ -d "$_marketplace_dir" ] || continue
        for _plugin_dir in "${_marketplace_dir}"three-pillars*/; do
            [ -d "$_plugin_dir" ] || continue
            _check_cache_tree "${_plugin_dir%/}"
        done
    done
fi

if [ "${#_probe3_matches[@]}" -gt 0 ]; then
    _probe3_winner="$(printf '%s\n' "${_probe3_matches[@]}" | sort | head -n 1)"
    if [ "${#_probe3_matches[@]}" -gt 1 ]; then
        _probe3_others="$(printf '%s, ' "${_probe3_matches[@]}" | sed 's/, $//')"
        printf 'three-pillars: WARNING multiple plugin-cache matches for three-pillars* under %s/.claude/plugins/cache — selecting %s deterministically (lexicographically first among: %s)\n' \
            "${HOME}" "$_probe3_winner" "$_probe3_others" >&2
    fi
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
