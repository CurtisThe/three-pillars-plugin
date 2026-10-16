"""test_archive_allowlist_escape_ledger.py — the archive prune keeps the escape ledger.

`escape-ledger.ndjson` is allowlisted like `dispatch-telemetry.ndjson`, so the
step-6e2 prune keeps a tracked, unreferenced ledger; the SKILL.md names it.

Run with: python3 -m pytest skills/_shared/test_archive_allowlist_escape_ledger.py
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from archive_allowlist import ALLOWLIST, plan_prune
from escape_ledger import NDJSON_NAME

HERE = Path(__file__).resolve().parent
DD = "three-pillars-docs/completed-tp-designs/x"


def _git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(root), "-c", "user.name=f", "-c",
                    "user.email=f@t", *args], capture_output=True,
                   text=True, check=True, env=env)


def test_ledger_name_is_allowlisted():
    assert "escape-ledger.ndjson" in ALLOWLIST
    assert NDJSON_NAME == "escape-ledger.ndjson"


def test_plan_keeps_ledger_and_drops_junk(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "master")
    d = tmp_path / DD
    d.mkdir(parents=True)
    (d / "design.md").write_text("d\n", encoding="utf-8")
    (d / NDJSON_NAME).write_text("{}\n", encoding="utf-8")
    (d / "junk.txt").write_text("j\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    plan = plan_prune(DD, tmp_path)
    assert f"{DD}/{NDJSON_NAME}" not in plan.drop
    assert f"{DD}/junk.txt" in plan.drop


def test_skill_md_names_ledger():
    text = (HERE.parent / "tp-design-complete" / "SKILL.md").read_text(encoding="utf-8")
    assert "`escape-ledger.ndjson`" in text
