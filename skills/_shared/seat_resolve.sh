#!/usr/bin/env bash
# seat_resolve.sh — single-sourced seat-resolution helper
#
# Derives "where is the seat?" / "am I the seat?" / "what broken state is this?"
# from observable git state. Pure detection, no mutation.
#
# Usage:
#   seat_resolve.sh --detect    [--repo <path>] [--base <branch>]
#   seat_resolve.sh --where     [--repo <path>] [--base <branch>]
#   seat_resolve.sh --am-i-seat [--repo <path>]
#   seat_resolve.sh --json      [--repo <path>] [--base <branch>]
#
# Exit codes:
#   --detect / --where / --json : always exit 0 on successful classification
#                                  (incl. indeterminate); non-zero for usage errors
#   --am-i-seat                 : exit 0 = confirmed seat; exit 1 = not-seat or indeterminate
#
# See skills/_shared/topology.md for the canonical seat definition.

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
MODE=""
REPO="."
BASE=""

_usage() {
    echo "Usage: seat_resolve.sh --detect|--where|--am-i-seat|--json [--repo <path>] [--base <branch>]" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --detect|--where|--am-i-seat|--json)
            if [[ -n "${MODE}" ]]; then
                echo "Error: only one mode flag allowed" >&2
                _usage
            fi
            MODE="${1#--}"
            shift
            ;;
        --repo)
            [[ $# -ge 2 ]] || _usage
            REPO="$2"
            shift 2
            ;;
        --base)
            [[ $# -ge 2 ]] || _usage
            BASE="$2"
            shift 2
            ;;
        *)
            echo "Error: unknown argument: $1" >&2
            _usage
            ;;
    esac
done

if [[ -z "${MODE}" ]]; then
    _usage
fi

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

# ---------------------------------------------------------------------------
# --am-i-seat: cheap boolean probe (no worktree enumeration)
# Exit 0 = confirmed seat (non-bare AND toplevel not under *-wt/)
# Exit 1 = not-seat or indeterminate
# ---------------------------------------------------------------------------
_am_i_seat() {
    # Probe 1: bare-bit (cheap constant-time rev-parse)
    local is_bare
    is_bare="$(_git rev-parse --is-bare-repository 2>/dev/null)" || {
        # git errored — not a repo or corrupt; fail-open to exit 1
        exit 1
    }
    if [[ "${is_bare}" == "true" ]]; then
        exit 1
    fi

    # Probe 2: path-shape — the REPO's worktree toplevel must NOT be under *-wt/.
    # We use worktree list --porcelain to get the toplevel (same source as --detect).
    # This is still constant-time relative to the number of worktrees because we
    # only read the first stanza (the owning worktree of REPO).
    local porcelain
    porcelain="$(_git worktree list --porcelain 2>/dev/null)" || exit 1

    # Find which worktree REPO maps to: walk the parsed list and find the
    # worktree whose path is a prefix of (or equal to) the canonicalized REPO.
    local repo_abs
    repo_abs="$(_canon "${REPO}")"

    local found_toplevel=""
    local cur_path=""
    local best_len=-1

    _am_flush() {
        if [[ -n "${cur_path}" ]]; then
            local canon_path
            canon_path="$(_canon "${cur_path}")"
            local path_len="${#canon_path}"
            # Check if repo_abs is equal to or inside this worktree's path
            if [[ "${repo_abs}" == "${canon_path}" || "${repo_abs}" == "${canon_path}/"* ]]; then
                if [[ ${path_len} -gt ${best_len} ]]; then
                    best_len=${path_len}
                    found_toplevel="${canon_path}"
                fi
            fi
        fi
        cur_path=""
    }

    while IFS= read -r line; do
        case "${line}" in
            "worktree "*)
                _am_flush
                cur_path="${line#worktree }"
                ;;
            "") _am_flush ;;
        esac
    done <<< "${porcelain}"
    _am_flush

    if [[ -z "${found_toplevel}" ]]; then
        exit 1
    fi

    if _is_under_wt_dir "${found_toplevel}"; then
        exit 1
    fi

    # Both probes pass: confirmed seat
    exit 0
}

# ---------------------------------------------------------------------------
# Core verdict engine: classify the repo state into the closed 8-value set.
# Outputs: VERDICT, SEAT_PATH, REPAIR_HINT
# ---------------------------------------------------------------------------
VERDICT=""
SEAT_PATH="NONE"
REPAIR_HINT=""

_classify() {
    # Step 1: Get bare-bit
    local is_bare
    is_bare="$(_git rev-parse --is-bare-repository 2>/dev/null)" || {
        VERDICT="indeterminate"
        return 0
    }

    # Step 2: Get worktree porcelain (the load-bearing input)
    local porcelain
    porcelain="$(_git worktree list --porcelain 2>/dev/null)" || {
        VERDICT="indeterminate"
        return 0
    }

    # Step 3: Parse worktrees
    _parse_worktrees "${porcelain}"

    # Step 4: The primary worktree toplevel (first entry) is the repo root.
    local primary_toplevel=""
    if [[ ${#WT_PATHS[@]} -gt 0 ]]; then
        primary_toplevel="${WT_PATHS[0]}"
    fi

    if [[ -z "${primary_toplevel}" ]]; then
        VERDICT="indeterminate"
        return 0
    fi

    # Step 5: Find which worktree the --repo path maps to.
    # This lets us classify "from inside a design worktree" correctly.
    local repo_abs
    repo_abs="$(_canon "${REPO}")"

    local our_wt_index=0
    local our_wt_path="${primary_toplevel}"
    local best_len=-1
    local i
    for i in "${!WT_PATHS[@]}"; do
        local wt_path="${WT_PATHS[$i]}"
        local wt_canon
        wt_canon="$(_canon "${wt_path}")"
        local path_len="${#wt_canon}"
        if [[ "${repo_abs}" == "${wt_canon}" || "${repo_abs}" == "${wt_canon}/"* ]]; then
            if [[ ${path_len} -gt ${best_len} ]]; then
                best_len=${path_len}
                our_wt_index=${i}
                our_wt_path="${wt_canon}"
            fi
        fi
    done

    # Step 6: Discriminator — is-bare + .git subdir check (NORMATIVE)
    # Uses the PRIMARY toplevel (index 0) as the definitive git directory location.
    if [[ "${is_bare}" == "true" ]]; then
        if [[ -d "${primary_toplevel}/.git" ]]; then
            # core-bare-flip: working tree exists but core.bare=true
            VERDICT="core-bare-flip"
            return 0
        else
            # Genuine bare hub (git clone --bare or similar)
            # Determine if a standing base worktree exists
            local resolved_base
            resolved_base="$(_resolve_base)"

            local has_base_wt="false"
            local base_wt_path=""
            for i in "${!WT_PATHS[@]}"; do
                local wt_branch="${WT_BRANCHES[$i]}"
                local wt_path="${WT_PATHS[$i]}"
                if [[ "${wt_branch}" == "${resolved_base}" || \
                      "${wt_branch}" == "refs/heads/${resolved_base}" ]]; then
                    has_base_wt="true"
                    base_wt_path="${wt_path}"
                    break
                fi
            done

            if [[ "${has_base_wt}" == "true" ]]; then
                VERDICT="bare-hub-variant"
                SEAT_PATH="${base_wt_path}"
            else
                VERDICT="missing-seat"
                REPAIR_HINT="add-worktree"
            fi
            return 0
        fi
    fi

    # is-bare == false from here on

    # Step 7: Path-shape check — is the worktree containing REPO under a *-wt/ dir?
    if _is_under_wt_dir "${our_wt_path}"; then
        # This checkout is inside a design worktree, not the seat
        VERDICT="design-worktree"
        return 0
    fi

    # Step 8: Check for unknown-worktree — a registered worktree that is neither
    # the primary (index 0) nor under *-wt/.
    # If our_wt_index != 0 and not under *-wt/, it is an unknown worktree.
    if [[ "${our_wt_index}" -ne 0 ]] && ! _is_under_wt_dir "${our_wt_path}"; then
        VERDICT="unknown-worktree"
        return 0
    fi

    # Step 9: We are at the primary worktree (seat candidate).
    # Resolve base branch and check for redundant base worktree.
    local resolved_base
    resolved_base="$(_resolve_base)"

    local has_redundant="false"
    for i in "${!WT_PATHS[@]}"; do
        local wt_path="${WT_PATHS[$i]}"
        # Skip the primary worktree
        [[ "${i}" -eq 0 ]] && continue

        if _is_under_wt_dir "${wt_path}"; then
            # Check if this is a redundant base worktree: *-wt/{base}
            local wt_name
            wt_name="$(basename "${wt_path}")"
            if [[ "${wt_name}" == "${resolved_base}" ]]; then
                has_redundant="true"
                break
            fi
        fi
    done

    if [[ "${has_redundant}" == "true" ]]; then
        VERDICT="redundant-base-worktree"
        SEAT_PATH="${primary_toplevel}"
        return 0
    fi

    # Step 10: Healthy seat
    VERDICT="seat-healthy"
    SEAT_PATH="${primary_toplevel}"
    return 0
}

# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------
if [[ "${MODE}" == "am-i-seat" ]]; then
    _am_i_seat
    # _am_i_seat exits directly; this line is unreachable
    exit 1
fi

# For reporters (--detect / --where / --json): always exit 0 after classification
_classify

case "${MODE}" in
    detect)
        if [[ "${VERDICT}" == "missing-seat" && -n "${REPAIR_HINT}" ]]; then
            echo "state=${VERDICT}"
            echo "repair_hint=${REPAIR_HINT}"
            echo ""
            echo "Broken state detected: no seat found. Suggested repair: git worktree add <repo>-host <base>"
            echo "Or run the worktree management skill's 'seat --apply' command."
        elif [[ "${VERDICT}" == "core-bare-flip" ]]; then
            echo "state=${VERDICT}"
            echo ""
            echo "Broken state detected: core.bare=true on a real checkout."
            echo "Repair: git config core.bare false"
            echo "Then (if tree is stale): git reset --hard origin/<base>"
            echo "Or run the worktree management skill's 'seat --apply' command."
        elif [[ "${VERDICT}" == "redundant-base-worktree" ]]; then
            echo "state=${VERDICT}"
            echo ""
            echo "Broken state detected: a *-wt/{base} worktree shadows the base checkout."
            echo "Repair: git worktree remove <repo>-wt/<base>"
            echo "Or run the worktree management skill's 'seat --apply' command."
        elif [[ "${VERDICT}" == "bare-hub-variant" ]]; then
            echo "state=${VERDICT}"
            echo ""
            echo "Note: bare-hub variant detected (supported but non-canonical)."
            echo "Consolidation paths (operator picks one):"
            echo "  1. git config core.bare false (flip hub to non-bare seat)"
            echo "  2. Keep standing base worktree as the canonical seat"
            echo "Run the worktree management skill's 'seat' command for details."
        elif [[ "${VERDICT}" == "indeterminate" ]]; then
            echo "state=${VERDICT}"
            echo ""
            echo "Indeterminate: git command errored (not a repo, or corrupt)."
        else
            echo "state=${VERDICT}"
            if [[ -n "${SEAT_PATH}" && "${SEAT_PATH}" != "NONE" ]]; then
                echo "seat_path=${SEAT_PATH}"
            fi
        fi
        exit 0
        ;;

    where)
        if [[ "${VERDICT}" == "seat-healthy" || \
              "${VERDICT}" == "bare-hub-variant" || \
              "${VERDICT}" == "redundant-base-worktree" ]]; then
            echo "${SEAT_PATH}"
        else
            echo "NONE"
        fi
        exit 0
        ;;

    json)
        local_seat_path="null"
        if [[ -n "${SEAT_PATH}" && "${SEAT_PATH}" != "NONE" ]]; then
            local_seat_path="\"${SEAT_PATH//\\/\\\\}\""
        fi

        local_repair_hint="null"
        if [[ -n "${REPAIR_HINT}" ]]; then
            local_repair_hint="\"${REPAIR_HINT}\""
        fi

        printf '{"state":"%s","seat_path":%s,"repair_hint":%s}\n' \
            "${VERDICT}" \
            "${local_seat_path}" \
            "${local_repair_hint}"
        exit 0
        ;;
esac
