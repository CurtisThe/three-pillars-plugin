#!/usr/bin/env sh
# heal-core-bare.sh — heal a core.bare=true bleed in the seat's shared config.
#
# Problem: the seat's shared .git/config was flipped to core.bare=true, leaving
# the seat reporting "(bare)" and refusing `git status`.  Cause (corrected
# 2026-09-22, hook-inherited-git-env; known_issues M17): self-inflicted by the
# framework's own pre-commit chain — framework-check invariant 7 ran a temp-dir
# `git init` under the hook's inherited GIT_DIR, so a commit from a linked
# worktree re-initialised that worktree's gitdir and wrote core.bare=true into
# the shared config.  That init was vestigial and is deleted; invariant #42
# keeps the class from returning.  This hook stays as a BACKSTOP.  It runs on
# post-checkout / post-merge only, which is why a worktree commit used to
# leave the seat bare until the next checkout.
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
