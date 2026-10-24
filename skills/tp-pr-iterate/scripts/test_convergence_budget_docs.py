"""Doc pins for the iterate-convergence-budget finding bar.

design: iterate-convergence-budget (Task 1.6)

Both reviewers (local `/code-review` angles and Copilot) must read the same
blocking bar, verbatim, under *What counts as a real defect here*.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills" / "_shared"))

_DEV_ROOT = Path(__file__).resolve().parents[3]
_needs_github_dir = pytest.mark.skipif(
    not (_DEV_ROOT / ".github").exists(),
    reason="reads the dev repo's .github/ instructions (dev-repo only)")
_needs_architecture = pytest.mark.skipif(
    not (_DEV_ROOT / "three-pillars-docs/architecture.md").exists(),
    reason="reads the dev repo's architecture.md (dev-repo only)")

REPO = Path(__file__).resolve().parents[3]
REVIEW_INSTRUCTIONS = REPO / ".github" / "review-instructions.md"
COPILOT_INSTRUCTIONS = REPO / ".github" / "copilot-instructions.md"

REVIEW_BAR = (
    "Only a demonstrated shipped-behaviour defect with a reproducer blocks; mutation "
    "survivors, test-tightening, exotic env, lint-guard bypasses, style and perf are "
    "non-blocking notes."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _section(text: str, heading: str) -> str:
    """Body of the `## heading` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"missing section: ## {heading}"
    return m.group(1)


def _blocking_bar(text: str) -> str:
    defects = _section(text, "What counts as a real defect here")
    m = re.search(r"^### Blocking bar\s*$(.*?)(?=^#{2,3} |\Z)", defects, re.M | re.S)
    assert m, "missing '### Blocking bar' under 'What counts as a real defect here'"
    return m.group(1)


@_needs_github_dir
def test_review_bar_verbatim_in_instructions():
    for path in (REVIEW_INSTRUCTIONS, COPILOT_INSTRUCTIONS):
        text = path.read_text(encoding="utf-8")
        assert REVIEW_BAR in _flat(_blocking_bar(text)), path.name


@_needs_github_dir
def test_lint_bypass_needs_real_call_site():
    for path in (REVIEW_INSTRUCTIONS, COPILOT_INSTRUCTIONS):
        bar = _flat(_blocking_bar(path.read_text(encoding="utf-8")))
        assert "real call site" in bar, path.name


@_needs_github_dir
def test_unpinned_contract_bullet_requires_demonstrated_failure():
    for path in (REVIEW_INSTRUCTIONS, COPILOT_INSTRUCTIONS):
        defects = _flat(_section(path.read_text(encoding="utf-8"),
                                 "What counts as a real defect here"))
        assert "a contract the tests don't actually pin." not in defects, path.name
        assert ("a shipped-behaviour contract the tests don't pin, with a demonstrated "
                "failure" in defects), path.name


# ---------- Task 8.1: round-topology.md ----------

TOPOLOGY = REPO / "skills" / "tp-pr-iterate" / "round-topology.md"


def _topology() -> str:
    return _flat(TOPOLOGY.read_text(encoding="utf-8"))


def _has_all(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_round_topology_angles_as_data_all_opus_and_bar():
    text = _topology()
    assert not _has_all(text, "review.angles", "DEFAULT_ANGLES", "angles.json",
                        'model: "opus"', "confirmer", REVIEW_BAR)
    assert "Sonnet" in text and "never" in text  # load_angles refuses non-Opus Claude models


def test_round_topology_round_tail_and_path_authority():
    text = _topology()
    assert not _has_all(text, "round tail", "path authority", "round_scratch.py prepare",
                        "reproduce.py --round-dir", "converge.py --round-dir", "run_round.py",
                        "tail-check", "without worktree isolation")


def test_round_topology_inline_fix_contract():
    text = _topology()
    assert not _has_all(text, "Steps 3 and 4 are skipped", "derive_fix_paths", "paths=",
                        "three-pillars-docs/**", ".three-pillars/config.json",
                        "fix-paths-mismatch", "head_reviewed", "git add -A")


def test_round_topology_scratch_is_per_round_and_per_angle():
    text = _topology()
    assert not _has_all(text, "rounds/<pr>/r<N>/", "<angle>/reply.md", "r<N>.1",
                        "per-round", "per-angle")


def test_round_topology_log_flush_commits_only_at_two_stable():
    text = _topology()
    assert not _has_all(text, "round_scratch.py flush", "decisions.md",
                        "committed and pushed only at `two-stable`", "round_log_carry",
                        "modified and uncommitted")


def test_round_topology_reproducer_outcomes():
    text = _topology()
    assert not _has_all(text, "reproduced", "not-reproduced", "inconclusive",
                        "legacy-no-reproducer", "never fails open")


def test_round_topology_recoveries():
    text = _topology()
    assert not _has_all(text, "pdw.guards.round_cap", "leave it uncommitted", "re-run",
                        "budget-exhausted", "budget-error", "tail-failed", "git restore",
                        "round_scratch.py remove", "missing `started_at`", "`now`")


# ---------- Task 8.2: tp-pr-iterate/SKILL.md ----------

SKILL = REPO / "skills" / "tp-pr-iterate" / "SKILL.md"
SKILL_MAX_LINES = 497  # net <= 0 against the pre-design file


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_skill_md_references_resolve():
    """Every path / script / skill reference in SKILL.md resolves (structured spans only)."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(REPO, [SKILL])
    assert report.issues == []


def test_skill_md_termination_matrix_has_budget_rows():
    matrix = _between(_skill(), "### Termination matrix", "## --dry-run mode")
    assert not _has_all(matrix, "`budget-exhausted`", "round-cap", "growth-lines",
                        "test-code-ratio", "budget-error", "`cap-exhausted`", "wall-clock",
                        "k-consecutive")
    assert "max_iterations" not in matrix


def test_skill_md_second_clean_round_not_required():
    assert "a second clean round is not required" in _flat(_skill())


def test_skill_md_loop_steps_name_the_round_dir_flow():
    loop = _between(_skill(), "## Loop body", "### Cold-resume contract")
    assert not _has_all(loop, "round_scratch.py prepare", "reproduce.py --round-dir",
                        "converge.py --round-dir", "`pr_url`", "`round`", "`ordinal`",
                        "`class_log_path`", "`review_base`", "paths=", "derive_fix_paths",
                        "round_budget.tick", "round_scratch.py tail-check")
    order = [loop.index(s) for s in ("round_scratch.py prepare", "reproduce.py --round-dir",
                                     "converge.py --round-dir", "round_scratch.py tail-check")]
    assert order == sorted(order)


def test_skill_md_no_worktree_isolated_pr_fix_dispatch():
    body = _flat(_skill())
    assert not re.search(r"/tp-pr-fix[^.]{0,200}isolation=\"worktree\"", body)


def test_skill_md_net_line_budget():
    assert len(_skill().splitlines()) <= SKILL_MAX_LINES


# ---------- Task 1.3: the growth floor pointer (design diff-growth-min-floor) ----------

def test_skill_md_names_the_growth_floor():
    """SKILL.md lists `growth_floor_lines` among the guards and says what it gates."""
    guards = _flat(_between(_skill(), "- `.three-pillars/config.json` — `pdw.guards.*`",
                            "override the defaults"))
    assert not _has_all(guards, "growth_floor_lines", "ratio_floor_lines"), guards
    body = _flat(_skill())
    assert not _has_all(body, "growth and ratio are judged only above it",
                        "default 300 changed lines")


# ---------- Task 8.4: proof-of-review.md, architecture.md, tp-design-complete ----------

PROOF_DOC = REPO / "skills" / "tp-pr-iterate" / "proof-of-review.md"
ARCHITECTURE = REPO / "three-pillars-docs" / "architecture.md"
DESIGN_COMPLETE = REPO / "skills" / "tp-design-complete" / "SKILL.md"


def _components() -> str:
    """architecture.md §Key Components — the live description, not the dated history."""
    return _between(ARCHITECTURE.read_text(encoding="utf-8"), "## Key Components",
                    "## Finding the spawning design")


@_needs_architecture
def test_no_run_loop_in_docs():
    for name, text in (("proof-of-review.md", PROOF_DOC.read_text(encoding="utf-8")),
                       ("tp-design-complete/SKILL.md",
                        DESIGN_COMPLETE.read_text(encoding="utf-8")),
                       ("architecture.md §Key Components", _components())):
        assert "run_loop" not in text and "_apply_guards" not in text, name
    assert "run_round" in _components() and "round_budget" in _components()


def test_design_complete_lists_notes():
    lines = [ln for ln in DESIGN_COMPLETE.read_text(encoding="utf-8").splitlines()
             if "[tp-pr-iterate/note]" in ln]
    assert lines and any("decisions.md" in ln for ln in lines)
