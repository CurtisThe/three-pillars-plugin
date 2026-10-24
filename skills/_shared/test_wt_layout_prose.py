"""Prose checks: shipped skill text opens worktrees through wt_root.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wt_layout_scan  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

REWORDED = [
    "skills/tp-run-full-design/audits.md",
    "skills/_shared/local-dispatch.md",
    "skills/tp-pr-iterate/round-topology.md",
    "skills/tp-run-full-design/scripts/build_synth_prompt.py",
    "skills/_shared/worker_root.py",
]


def _rules_bullet(rel: str, token: str) -> str:
    """Return the first §Rules bullet of `rel` that mentions `token`."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    rules = text.split("\n## Rules", 1)[1].split("\n## ", 1)[0]
    for line in rules.splitlines():
        if line.startswith("- ") and token in line:
            return line
    return ""


def test_phase_implement_parallel_agents():
    bullet = _rules_bullet("skills/tp-phase-implement/SKILL.md", "Parallel agents")
    assert bullet != ""
    assert "wt_root.py open --role worker" in bullet
    assert "WORKTREE:" in bullet
    assert "wt_root.py reap" in bullet
    assert "isolation" not in bullet


def test_no_literal_in_reworded_files():
    for rel in REWORDED:
        hits = wt_layout_scan.scan([ROOT / Path(rel).parent], base=ROOT)
        assert [h for h in hits if h[0] == rel] == [], rel
