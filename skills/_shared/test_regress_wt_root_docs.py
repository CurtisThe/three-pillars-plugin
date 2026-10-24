"""Tier 5 Step 1 (regression check) opens its worktree through wt_root.py."""
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / "tp-run-full-design" / "tier-5-closeout.md"


def _step1() -> str:
    text = "\n" + DOC.read_text(encoding="utf-8")
    assert "\n### Step 1" in text and "\n### Step 2" in text
    return text.split("\n### Step 1", 1)[1].split("\n### Step 2", 1)[0]


def test_step1_opens_via_wt_root():
    s = _step1()
    assert "wt_root.py open --role regress" in s
    assert "--base-ref origin/candidate/{slug}/single" in s
    assert "WORKTREE:" in s
    assert "wt_root.py reap --role regress" in s


def test_step1_has_no_legacy_isolation_or_switch():
    s = _step1()
    assert "isolation=" not in s and "isolation:" not in s
    assert "git switch -C regress/" not in s
