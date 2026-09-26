#!/usr/bin/env python3
"""End-to-end ground-truth fixtures landed by basesync-prepend-log — the fixtures the classifier's
GATED comment was waiting for. They prove a REAL base-sync conflict (git-minimized to an EMPTY
base) over a newest-first ADR log auto-resolves keep-both through the WHOLE pipeline
(classify -> resolve -> merge_driver writes it) AND that the shared cert byte-production path
(`resolve_conflict_bytes`) reproduces those exact bytes — the precondition on which
`approval-survives-safe-base-sync` carries the human approval + review proof across the base-sync.

Why this is the real proof and the unit `_diff3` fixtures are not: `git merge-file --diff3`
minimizes a concurrent insertion so the shared `## History` header + prior entry factor OUT of the
hunk, leaving an EMPTY base. Only a real three-commit repo driven through `merge_driver.merge_back`
exercises that shape — the exact shape of the operator's re-approval tax on architecture.md.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402

_MERGE_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "tp-merge-from-main", "scripts")
)
sys.path.insert(0, _MERGE_SCRIPTS)
import merge_driver  # noqa: E402

ARCH = "three-pillars-docs/architecture.md"


def _git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=env)


def _three_commit_repo(tmp_path, path, base_txt, ours_txt, theirs_txt):
    """base commit -> design branch writes ours -> master writes theirs; checkout design.
    `merge_back(master)` then faces a real base-sync conflict on `path`."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(base_txt)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "design")
    (repo / path).write_text(ours_txt)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "ours")
    _git(repo, "checkout", "-q", "master")
    (repo / path).write_text(theirs_txt)
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "theirs")
    _git(repo, "checkout", "-q", "design")
    return repo


def _history(entries):
    # Real `## History` shape: a bold-lead dated bullet + an indented continuation body (so the
    # fixture also exercises a WRAPPED entry, not just a single-line bullet).
    body = "\n\n".join(f"- **{d}** — {t}\n\n  {b}" for d, t, b in entries)
    return f"# Architecture\n\n## History\n\n{body}\n"


def test_history_prepend_auto_resolves_and_reproduces_bytes(tmp_path):
    A = ("2026-07-01", "decision A", "rationale A")
    base_txt = _history([A])
    ours_txt = _history([("2026-07-04", "decision OURS", "rat ours"), A])      # ours prepends
    theirs_txt = _history([("2026-07-05", "decision THEIRS", "rat theirs"), A])  # theirs prepends

    repo = _three_commit_repo(tmp_path, ARCH, base_txt, ours_txt, theirs_txt)
    report = merge_driver.merge_back(str(repo), "master")
    assert ARCH in report.auto_resolved, report.to_json()   # the base-sync auto-resolved it

    written = (repo / ARCH).read_text(encoding="utf-8")
    for needle in ["decision OURS", "decision THEIRS", "decision A"]:
        assert needle in written                            # zero-drop: every entry survives
    assert "<<<<<<<" not in written                         # no conflict markers left

    # Cert byte-repro precondition: the shared resolve path reproduces the written bytes exactly.
    status, merged = resolve_conflict_bytes(base=base_txt, ours=ours_txt, theirs=theirs_txt)
    assert status == RESOLVED
    assert merged == written


DECISIONS = "three-pillars-docs/tp-designs/demo/decisions.md"


def _decisions(entries):
    """The real `decisions.md` shape `auto-mode.md` prescribes."""
    body = "\n\n".join(
        f"### [{tag}] {title}\n**Question**: {q}\n**Decided**: {d}\n**Confidence**: High"
        for tag, title, q, d in entries)
    return f"# Decisions — demo\n\n{body}\n"


def test_decisions_log_both_sides_append_auto_resolves(tmp_path):
    """Design Behavior 4, end to end: the guaranteed hand-resolve on every `/tp-run-full-design`
    fold is gone. The orchestrator appends on `tp/{slug}` while a worker appends on
    `candidate/{slug}/single`; both entry sets survive, auto-resolved and staged, no human."""
    seed = ("tp-promote", "promoted from seed", "promote?", "yes")
    base_txt = _decisions([seed])
    ours_txt = _decisions([seed, ("tp-plan", "one phase", "escalate?", "no")])
    theirs_txt = _decisions([seed, ("tp-plan-audit", "council round 1", "which findings?", "1+3")])

    repo = _three_commit_repo(tmp_path, DECISIONS, base_txt, ours_txt, theirs_txt)
    report = merge_driver.merge_back(str(repo), "master")

    assert DECISIONS in report.auto_resolved, report.to_json()
    assert report.needs_human is False, report.to_json()

    written = (repo / DECISIONS).read_text(encoding="utf-8")
    for needle in ("[tp-promote]", "[tp-plan]", "[tp-plan-audit]",
                   "promoted from seed", "one phase", "council round 1"):
        assert needle in written                            # zero-drop: every entry survives
    assert "<<<<<<<" not in written

    # Cert byte-repro precondition: the shared resolve path reproduces the written bytes exactly.
    status, merged = resolve_conflict_bytes(base=base_txt, ours=ours_txt, theirs=theirs_txt)
    assert status == RESOLVED
    assert merged == written


def test_design_md_sibling_still_defers(tmp_path):
    """Only `decisions.md` joins the mechanical lane — a sibling design artifact under the same
    slug directory is NOT auto-resolved, so the pattern is not a `tp-designs/**` glob."""
    path = "three-pillars-docs/tp-designs/demo/design.md"
    base_txt = "# Design\n\n## Scope\n\nshared prose.\n"
    repo = _three_commit_repo(tmp_path, path, base_txt,
                              base_txt.replace("shared prose.", "ours rewrote the scope."),
                              base_txt.replace("shared prose.", "theirs rewrote the scope."))
    report = merge_driver.merge_back(str(repo), "master")
    assert path not in report.auto_resolved, report.to_json()
    assert report.needs_human is True


def test_history_semantic_edit_still_defers(tmp_path):
    # A base-sync that MODIFIES an existing entry (non-empty base) must NOT auto-resolve — the carry
    # must never certify a semantic change. Fail-closed backstop for the empty-base predicate.
    A = ("2026-07-01", "decision A", "rationale A")
    base_txt = _history([A])
    ours_txt = _history([("2026-07-01", "decision A", "rationale A — ours edit")])
    theirs_txt = _history([("2026-07-01", "decision A", "rationale A — theirs edit")])
    repo = _three_commit_repo(tmp_path, ARCH, base_txt, ours_txt, theirs_txt)
    report = merge_driver.merge_back(str(repo), "master")
    assert ARCH not in report.auto_resolved, report.to_json()   # deferred to a human
