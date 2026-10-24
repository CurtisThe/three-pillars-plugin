"""safety_gate.py - the one list of safety-gate paths and its predicates.

The design's five gate families: (1) the merge gate, (2) delete fences,
(3) the allow list, (4) review-proof carry, (5) worktree / isolation and
commit guards. A light design that touches none of them skips the certifier
and the `security` angle. Every `_shared` module gate_roster.py imports and
every hook in hooks/claude-code-hooks.json is covered
(test_safety_gate_coverage.py checks it). GATE_PATHS is family globs (names
carrying guard, gate, proof, approval, carry, identity, delete, fence, kill or
allowlist) plus named singles whose names carry no family word. It is
curated, not a transitive closure; set `safety-gate: true` in the frontmatter
for anything else. Stdlib only.
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import weight_class  # noqa: E402

GATE_PATHS = (
    # --- family globs: a new module whose name carries a family word is a gate
    # (1) merge gate and its predicates
    "skills/_shared/*gate*.py",
    "skills/tp-merge-from-main/scripts/merge_gate*.py",
    "skills/tp-merge-from-main/scripts/gate_cli.py",
    "skills/tp-merge/scripts/land.py",
    "skills/_shared/*approval*.py",
    "skills/_shared/*identity*.py",
    # (2) delete and create fences, kill guards
    "skills/_shared/*delete*.py",
    "skills/_shared/*fence*.py",
    "skills/_shared/*kill*.py",
    # (3) allow list
    "skills/_shared/*allowlist*.py",
    "skills/_shared/allowlist/*",
    # (4) review-proof and approval carry
    "skills/_shared/*proof*.py",
    "skills/_shared/*carry*.py",
    "skills/tp-pr-iterate/scripts/review_proof*.py",
    # (5) worktree / isolation and commit guards, and every registered hook
    "skills/_shared/*guard*.py",
    "skills/_shared/hooks/*",
    # --- named singles: no family word in the name
    "skills/_shared/review_readiness.py",
    "skills/_shared/default_branch.py",
    "skills/_shared/project_root.py",
    "skills/_shared/fragility_predicate.py",
    "skills/_shared/fragility_ast.py",
    "skills/_shared/ci_local_stamp.py",
    "skills/_shared/operator_accept.py",
    "skills/_shared/base_sync_cert.py",
    "skills/_shared/cert_once.py",
    "skills/_shared/worker_root.py",
    "skills/_shared/thread_resolver.py",
    "skills/_shared/per_developer_author.py",
    "skills/_shared/wt_layout_hook.py",
    "skills/_shared/escalate_first_hook.py",
    "skills/_shared/stop_question_hook.py",
    "skills/_shared/wait_ttl_hook.py",
    "skills/_shared/run_scratch.py",
    "skills/_shared/scratch_leftovers.py",
    "skills/_shared/run_no_cards_hook.py",
)


def touches_gate(paths) -> bool:
    """True if any non-test path matches GATE_PATHS; None (unreadable diff) is True."""
    if paths is None:
        return True
    for p in paths:
        if os.path.basename(p).startswith("test_"):
            continue
        if any(fnmatch.fnmatch(p, g) for g in GATE_PATHS):
            return True
    return False


def declares_safety_gate(design_dir) -> bool:
    """True when design.md frontmatter has `safety-gate: true`; False on any error."""
    try:
        text = (Path(design_dir) / "design.md").read_text(encoding="utf-8")
        fm = weight_class.parse_frontmatter(text)
        return str(fm.get("safety-gate", "")).strip().lower() == "true"
    except Exception:
        return False


def changed_paths(repo, base, head):
    """Paths changed between base...head, or None on a git failure."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.quotePath=false", "diff",
             "--no-renames", "--name-only", f"{base}...{head}"],
            capture_output=True, text=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return [ln for ln in r.stdout.split("\n") if ln]
