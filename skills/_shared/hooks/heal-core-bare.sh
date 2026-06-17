#!/usr/bin/env sh
# heal-core-bare.sh — heal the core.bare=true bleed from harness worktree lifecycle.
#
# Problem: the Claude Code isolation=worktree harness flips core.bare=true in the
# seat's shared .git/config when it creates/tears down agent worktrees.  This
# leaves the seat repo reporting "(bare)" and refusing `git status`.
#
# Fix: if core.bare=true is set but a .git/ subdir is present (the reliable
# discriminator — a genuine bare clone has no .git/ subdir), flip core.bare back
# to false.  On a healthy repo the test fails and the script is a no-op.
#
# Installed into .git/hooks/post-checkout and .git/hooks/post-merge by
# skills/_shared/bootstrap_immunization.py via sentinel-guarded append.
#
# IMPORTANT: This block is appended into an existing hook file.  To avoid
# interfering with other blocks appended after the sentinel:
#   - All logic is wrapped in a function (no top-level early exit).
#   - No set -euo pipefail in this block (options leak into subsequent content).
#   - POSIX sh safe (works under /bin/sh / dash as well as bash).

_tp_heal_core_bare() {
    # Resolve the repo top-level robustly: even with core.bare=true the first
    # `worktree <path>` line from `git worktree list --porcelain` gives us the
    # physical root, so `--show-toplevel` (which errors on bare repos) is avoided.
    # Use sed 's/^worktree //' to preserve paths containing spaces.
    _TP_HEAL_TOPLEVEL=$(git worktree list --porcelain 2>/dev/null \
        | sed -n 's/^worktree //p' | head -1)

    if [ -z "$_TP_HEAL_TOPLEVEL" ]; then
        return 0  # can't determine top-level, be a no-op
    fi

    # Check if core.bare=true is set
    _TP_HEAL_IS_BARE=$(git config --local core.bare 2>/dev/null || echo "false")

    if [ "$_TP_HEAL_IS_BARE" != "true" ]; then
        return 0  # healthy — nothing to do
    fi

    # Discriminator: is there a .git/ subdirectory?  If yes this is a bleed state,
    # not a genuine bare clone.
    if [ -d "${_TP_HEAL_TOPLEVEL}/.git" ]; then
        git config core.bare false
        echo "three-pillars: heal-core-bare: flipped core.bare=true -> false (bleed state healed)" >&2
    fi
}

_tp_heal_core_bare
