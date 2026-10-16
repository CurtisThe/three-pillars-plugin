"""Structured checks over skills/tp-merge-from-main/SKILL.md (the base-sync half).

The SKILL.md prose is not asserted here (no wording, heading or line pins). The behaviour
it describes is pinned in the sibling tests (`test_gate_cli*.py`, `test_merge_driver*.py`,
`test_cert_comment*.py`, ...); the doc's references (scripts, helpers, flags, skills it
names) are checked by `skill_refs` (invariant 46); the frontmatter by the shipped
`skill_frontmatter` validator.

Run with: pytest skills/tp-merge-from-main/scripts/test_merge_skill_md.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
REPO_ROOT = SKILL_MD.parent.parent.parent
_SHARED = str(REPO_ROOT / "skills" / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)


def test_merge_skill_frontmatter_passes_schema():
    skill_frontmatter = pytest.importorskip("skill_frontmatter")
    assert SKILL_MD.exists(), "skills/tp-merge-from-main/SKILL.md must exist"
    assert skill_frontmatter.check(SKILL_MD) == []
    fm, issues = skill_frontmatter.parse(SKILL_MD.read_text(encoding="utf-8"))
    assert issues == []
    assert fm["name"][1] == "tp-merge-from-main"


def test_merge_skill_references_resolve(tmp_path):
    """Every path, helper script, `/tp-*` skill and `python3` invocation SKILL.md names
    exists and parses with its script's own argparse."""
    skill_refs = pytest.importorskip("skill_refs")
    assert SKILL_MD.exists()
    assert skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path).issues == []


def test_every_auto_resolve_class_is_named():
    """Every class the resolver may auto-apply is listed (backticked) in SKILL.md."""
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import classify

    text = SKILL_MD.read_text(encoding="utf-8")
    missing = sorted(c for c in classify.AUTO_RESOLVE if f"`{c}`" not in text)
    assert missing == []


def test_verify_cli_line_names_base():
    """The line documenting verify.py's standalone usage documents `--base`."""
    lines = [
        ln for ln in SKILL_MD.read_text(encoding="utf-8").splitlines()
        if "verify.py" in ln and "<ours> <theirs> <resolved>" in ln
    ]
    assert lines, "no verify.py standalone-usage line found"
    assert all("--base" in ln for ln in lines)


def test_sync_gate_before_push_land_gate_after():
    """The base-sync's blocking pre-push check is sync_gate.py; the land gate (gate_cli.py)
    runs only after the step-7 push, as a readout. Order of first occurrences pins it, so
    the land gate cannot drift back in front of the push it would block."""
    text = SKILL_MD.read_text(encoding="utf-8")
    sync = text.find("scripts/sync_gate.py --repo")
    push = text.find("\n7. **Push")
    land = text.find("scripts/gate_cli.py --repo")
    assert sync != -1 and push != -1 and land != -1, (sync, push, land)
    assert sync < push < land, (sync, push, land)
