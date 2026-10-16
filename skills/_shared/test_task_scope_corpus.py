"""test_task_scope_corpus.py — `task_scope` over every archived plan.

design: local-implement-and-review

Runs the block splitter and both field parsers (Targets and File) over
`three-pillars-docs/completed-tp-designs/*/plan.md` (plain files; no git) and prints the
canonical / non-canonical and `unparsed_files` counts (`-s`). Plans written before the
**Targets** field are non-canonical by construction: nothing in their Test prose runs.
"""
from __future__ import annotations

from pathlib import Path

import task_scope
import pytest

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_dev_docs = pytest.mark.skipif(
    not (_DEV_ROOT / "three-pillars-docs").exists(),
    reason="reads the dev repo's three-pillars-docs/ (dev-repo only)")

_REPO = Path(__file__).resolve().parents[2]
_GLOB = str(_REPO / "three-pillars-docs" / "completed-tp-designs" / "*" / "plan.md")


@_needs_dev_docs
def test_corpus_parsers_never_raise_and_counts_add_up():
    report = task_scope.corpus_report(_GLOB)
    assert report["plans"] >= 100
    assert report["tasks"] == len(report["rows"]) > 1000
    assert report["canonical"] + report["non_canonical"] == report["tasks"]
    assert sum(report["kinds"].values()) == report["tasks"]
    assert report["unparsed_files"] == sum(1 for r in report["rows"] if r["unparsed"])
    print(f"\ncorpus: {report['plans']} plans, {report['tasks']} tasks, "
          f"{report['canonical']} canonical, {report['non_canonical']} non-canonical")
    print(f"kinds: {dict(sorted(report['kinds'].items()))}")
    print(f"unparsed_files: {report['unparsed_files']} tasks")


def test_every_non_canonical_row_is_not_runnable():
    """A task without a valid Targets field never yields a runnable spec."""
    for row in task_scope.corpus_report(_GLOB)["rows"]:
        if not row["canonical"]:
            assert (row["kind"], row["specs"]) == ("not-runnable", []), (
                row["design"], row["task_id"])
        elif row["kind"] != "not-runnable":
            assert row["specs"] and set(row["files"]) == {
                s.partition("::")[0] for s in row["specs"]}
