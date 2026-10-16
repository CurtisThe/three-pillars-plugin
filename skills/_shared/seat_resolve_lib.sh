#!/usr/bin/env bash
# seat_resolve_lib.sh — helper functions for seat_resolve.sh.
#
# Sourced by seat_resolve.sh; not run directly. Defines functions only — no
# top-level command runs. Relies on the caller's REPO / BASE globals exactly as
# the inline helpers did when they lived in seat_resolve.sh.

# ---------------------------------------------------------------------------
# Helper: run git in REPO, return stdout. Returns non-zero on error.
# ---------------------------------------------------------------------------
_git() {
    git -C "${REPO}" "$@" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Helper: parse git worktree list --porcelain into parallel arrays.
# Mirrors worktree_isolation_guard.py::all_worktrees()
# Sets: WT_PATHS[], WT_BRANCHES[], WT_BARE[]
# ---------------------------------------------------------------------------
_parse_worktrees() {
    local porcelain="$1"
    WT_PATHS=()
    WT_BRANCHES=()
    WT_BARE=()

    local cur_path="" cur_branch="" cur_bare="false"

    _flush_wt() {
        if [[ -n "${cur_path}" ]]; then
            WT_PATHS+=("${cur_path}")
            WT_BRANCHES+=("${cur_branch}")
            WT_BARE+=("${cur_bare}")
        fi
        cur_path=""
        cur_branch=""
        cur_bare="false"
    }

    while IFS= read -r line; do
        case "${line}" in
            "worktree "*)
                _flush_wt
                cur_path="${line#worktree }"
                ;;
            "branch refs/heads/"*)
                cur_branch="${line#branch refs/heads/}"
                ;;
            "branch "*)
                cur_branch="${line#branch }"
                ;;
            "bare")
                cur_bare="true"
                ;;
            "")
                _flush_wt
                ;;
        esac
    done <<< "${porcelain}"
    _flush_wt
}

# ---------------------------------------------------------------------------
# Helper: resolve base branch (reuses tp-post-merge step-3 cascade)
# Priority: --base flag → refs/remotes/origin/HEAD
#           → (bare only) symbolic-ref HEAD (hub's own default branch)
#           → main → master
#
# The bare-only symbolic-ref step is gated strictly on is-bare-repository
# because on a non-bare checkout symbolic-ref HEAD returns the CURRENTLY
# CHECKED-OUT branch (often a feature/tp branch), NOT the base.  Using it
# as base for non-bare repos would regress healthy seats on feature branches.
# ---------------------------------------------------------------------------
_resolve_base() {
    if [[ -n "${BASE}" ]]; then
        echo "${BASE}"
        return
    fi
    local remote_head
    remote_head="$(_git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    if [[ -n "${remote_head}" ]]; then
        # Strip "origin/" prefix
        echo "${remote_head#origin/}"
        return
    fi
    # For bare repos, the repo's own HEAD is the hub's default branch —
    # authoritative when there is no origin/HEAD (e.g. git clone --bare
    # disconnected from origin, or non-standard default branch like `trunk`).
    local is_bare_here
    is_bare_here="$(_git rev-parse --is-bare-repository 2>/dev/null || true)"
    if [[ "${is_bare_here}" == "true" ]]; then
        local hub_default
        hub_default="$(_git symbolic-ref --short HEAD 2>/dev/null || true)"
        hub_default="${hub_default#refs/heads/}"
        if [[ -n "${hub_default}" ]]; then
            echo "${hub_default}"
            return
        fi
    fi
    # Try main then master.
    # Known boundary: a NON-bare repo with a non-standard default branch (e.g.
    # "trunk", "develop") AND no origin/HEAD cannot reliably auto-resolve its
    # base here — it falls through to "master".  Use --base as the escape hatch.
    if _git rev-parse --verify main >/dev/null 2>&1; then
        echo "main"
        return
    fi
    echo "master"
}

# ---------------------------------------------------------------------------
# Helper: is path under a *-wt/ sibling dir?
# Returns 0 (true) if under *-wt/, 1 otherwise.
# ---------------------------------------------------------------------------
_is_under_wt_dir() {
    local path="$1"
    local parent
    parent="$(dirname "${path}")"
    # parent directory name ends with -wt
    case "$(basename "${parent}")" in
        *-wt) return 0 ;;
        *) return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Helper: canonicalize a path (resolve to absolute physical path).
# Infallible: if cd fails (non-cd-able dir, stale worktree entry, etc.)
# or pwd -P errors, falls back to the original string unchanged.
# Uses `pwd -P` so physical (non-symlink) paths are returned — consistent
# with the physical paths emitted by `git worktree list --porcelain`.
# ---------------------------------------------------------------------------
_canon() {
    local p="$1"
    (cd "${p}" 2>/dev/null && pwd -P) || printf '%s' "${p}"
}
