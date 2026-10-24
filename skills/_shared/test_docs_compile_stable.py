"""test_docs_compile_stable.py — Task 1.7: compile determinism and duplicate-ID refusal.

design: living-doc-fragments, Task 1.7 (§Interfaces steps 2 and 4). Real temp git repos; assertions are
exact text, git trees and exit codes (Oracle: example, metamorphic), never message wording
(test-fragility.md §2).
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile  # noqa: E402
import reconcile_docs  # noqa: E402
from test_docs_compile import ARCH, CH, KI, ROADMAP, TWO, frag, git, make_repo  # noqa: E402

STAMP = re.compile(r"^\*Last updated: (\d{4}-\d{2}-\d{2})", re.M)
DUP_KI = ("# Known Issues\n\n## Critical / High\n\n## Medium\n\n### M52: first\nbody\n\n"
          "### M52: second\nbody\n\n## Low\n")


def _fake_day(monkeypatch, day: str):
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(day)

    monkeypatch.setattr(reconcile_docs.datetime, "date", FakeDate)


def test_last_updated_is_the_newest_fragment_date(tmp_path, monkeypatch):
    _fake_day(monkeypatch, "2031-06-07")
    root = make_repo(tmp_path, TWO)
    base = git(root, "rev-parse", "HEAD")
    docs_compile.compile_all(root, base_ref=base, prs={"alpha": 7}, commit=True)
    for rel in (ROADMAP, ARCH):
        stamps = STAMP.findall((root / rel).read_text(encoding="utf-8"))
        assert stamps == ["2020-01-03"], rel


def test_output_is_identical_under_a_faked_later_clock(tmp_path, monkeypatch):
    first = make_repo(tmp_path, TWO, name="one")
    second = tmp_path / "two"
    shutil.copytree(first, second)
    base = git(first, "rev-parse", "HEAD")
    _fake_day(monkeypatch, "2031-06-07")
    docs_compile.compile_all(first, base_ref=base, prs={"alpha": 7}, commit=True)
    _fake_day(monkeypatch, "2044-12-30")
    docs_compile.compile_all(second, base_ref=base, prs={"alpha": 7}, commit=True)
    assert git(first, "rev-parse", "HEAD^{tree}") == git(second, "rev-parse", "HEAD^{tree}")


def test_duplicate_issue_id_refuses_and_restores(tmp_path, capsys):
    body = "\n## Roadmap\n\n### Current Focus\n+ - alpha focus\n"
    root = make_repo(tmp_path, {"alpha": frag("alpha", "2020-01-02", body)}, docs={KI: DUP_KI.replace("### M52: second\nbody\n\n", "")})
    base = git(root, "rev-parse", "HEAD")
    (root / KI).write_text(DUP_KI, encoding="utf-8")  # the duplicate appears after base_ref
    git(root, "commit", "-q", "-am", "introduce duplicate")
    head = git(root, "rev-parse", "HEAD")
    rc = docs_compile.main(["--base-ref", base, "--commit", "--repo-root", str(root), "--pr", "alpha=7"])
    out = capsys.readouterr().out
    assert rc == 1 and "M52" in out
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "rev-parse", "HEAD") == head
    assert (root / CH / "alpha.md").exists()
