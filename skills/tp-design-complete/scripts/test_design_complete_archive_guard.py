"""Archive-guard invariants for skills/tp-design-complete/SKILL.md.

The design-complete-stamp-guard staged-blob guard: step 6f runs
verify_archive_staged.py between staging and the archival commit, commits
unpiped with a HEAD-advanced check, stages the reconcile --json list by loop, and
stages one pathspec per `git add`. The command checks run on the parsed shell
spans (`skill_spans.code_spans`: line, span, is-shell), never on prose wording.

Run with: pytest skills/tp-design-complete/scripts/test_design_complete_archive_guard.py -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SKILL_MD = Path(__file__).resolve().parents[1] / "SKILL.md"
REPO_ROOT = Path(__file__).resolve().parents[3]
_SHARED = str(Path(__file__).resolve().parents[2] / "_shared")
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)
_CUT = {"||", "&&", ";", "|", "2>/dev/null", ">&2"}


def _read() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _auto_mode_block(text: str) -> str:
    """Return the text from the '## Auto Mode' heading to the next '## ' (or EOF)."""
    match = re.search(r"^## Auto Mode\b.*?(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, "## Auto Mode section not found"
    return match.group(0)


def _shell_spans(shell_only: bool = True) -> list[tuple[int, list[str]]]:
    """(line, tokens) of every (shell, unless shell_only=False) code span in the SKILL.md."""
    skill_spans = pytest.importorskip("skill_spans")
    return [(line, skill_spans.tokens_of(span, shell))
            for line, span, shell in skill_spans.code_spans(_read()) if shell or not shell_only]


def _first(spans, pred, after: int = 0) -> int:
    hits = [line for line, toks in spans if line > after and pred(toks)]
    assert hits, "no shell span matches"
    return hits[0]


def _is_add(t): return t[:2] == ["git", "add"]
def _is_commit(t): return t[:2] == ["git", "commit"]
def _is_guard(t): return t[:1] == ["python3"] and any(x.endswith("verify_archive_staged.py") for x in t)
def _is_pr_open(t):
    return t[:3] == ["gh", "pr", "create"] or (t[:1] == ["python3"] and "pr-create" in t[1:3])


def test_skill_references_resolve(tmp_path) -> None:
    """Invariant 46's check over this SKILL.md: every path, script, flag and skill it
    names (verify_archive_staged.py, reconcile_docs.py --archive-cites --json,
    forge.py) exists and parses with its own argparse."""
    skill_refs = pytest.importorskip("skill_refs")
    report = skill_refs.check(REPO_ROOT, [SKILL_MD], cache_dir=tmp_path)
    assert report.issues == []


def test_guard_runs_after_staging_before_commit_before_pr() -> None:
    """The staged-blob guard is inert unless it runs after a `git add` and before the
    archival `git commit`, which itself precedes opening the PR."""
    spans = _shell_spans()
    add = _first(spans, _is_add)
    guard = _first(spans, _is_guard)
    commit = _first(spans, _is_commit)
    pr = _first(spans, _is_pr_open)
    assert add < guard < commit < pr, (add, guard, commit, pr)


def test_guard_invoked_with_repo_and_slug() -> None:
    """The guard command carries --repo (resolved from the toplevel) and --slug {design-name}."""
    spans = dict(_shell_spans())
    toks = spans[_first(list(spans.items()), _is_guard)]
    assert toks[toks.index("--repo") + 1] == "$(git rev-parse --show-toplevel)"
    assert toks[toks.index("--slug") + 1] == "{design-name}"


def test_archival_commit_unpiped_and_head_advance_checked() -> None:
    """The archival commit is unpiped (a pipe hides its exit status), HEAD is captured
    before it, and a span after it compares HEAD against the captured value."""
    spans = _shell_spans()
    commit = _first(spans, _is_commit)
    toks = dict(spans)[commit]
    assert "|" not in toks and "||" not in toks, toks
    pre = _first(spans, lambda t: t and t[0].startswith("PRE=$(git") and "rev-parse" in t)
    assert pre < commit
    after = _first(spans, lambda t: any("rev-parse HEAD" in x for x in t) and "$PRE" in t, after=commit)
    assert after > commit


def test_reconcile_json_staged_by_loop() -> None:
    """The reconcile --json capture precedes a `for ... in` loop whose body `git add`s
    the loop variable (each rewritten path), not a fixed path set."""
    spans = _shell_spans(shell_only=False)
    cap = _first(spans, lambda t: bool(t) and t[0].startswith("RECONCILE_JSON="))
    loop = _first(spans, lambda t: t[:1] == ["for"] and "$RECONCILE_JSON" in t, after=cap)
    var = dict(spans)[loop][1]
    body = _first(spans, lambda t: _is_add(t) and t[2:] == ["$" + var], after=loop)
    assert cap < loop < body <= loop + 3


def test_each_git_add_stages_one_pathspec() -> None:
    """After step 6c's `git mv`, a non-matching pathspec aborts the WHOLE `git add`, so
    every shell `git add` carries at most one pathspec, and the archived design.md has its own."""
    adds = []
    for line, toks in _shell_spans():
        if not _is_add(toks):
            continue
        cut = next((i for i, t in enumerate(toks) if t in _CUT), len(toks))
        specs = [t for t in toks[2:cut] if not t.startswith("-")]
        assert len(specs) <= 1, (line, specs)
        adds += specs
    assert "three-pillars-docs/completed-tp-designs/{design-name}/design.md" in adds


def test_guard_exit1_double_add_exit2_immediate_abort() -> None:
    """On exit 1 the step re-runs the specific git add (double-add) then aborts if
    still failing; on exit 2 (precondition) it aborts IMMEDIATELY without the retry.
    """
    text = _read()
    # Scope to the guard sub-step: from the guard invocation to the archival commit.
    guard_pos = text.find("verify_archive_staged.py")
    commit_pos = text.find('git commit -m "Complete design:')
    span = text[guard_pos:commit_pos]
    # Kept on purpose: the agent's response to each guard exit code is SKILL.md prose
    # with no parsed structure or eval owner (test_verify_archive_staged*.py own the
    # helper's exit codes, not this disposition), so each assert carries a waiver.
    # exit 1 -> double-add retry
    assert re.search(r"exit.{0,6}1", span), "the guard sub-step must name exit 1"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    assert re.search(r"double-add|re-`?git add`?|re-add", span, re.IGNORECASE), (
        "on exit 1 the step must re-`git add` the offending path (double-add)"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    )
    assert re.search(r"still.{0,20}(exit|fail)|abort", span, re.IGNORECASE), (
        "on a still-failing double-add the step must abort loudly"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    )
    # exit 2 -> immediate abort, no retry
    assert re.search(r"exit.{0,6}2", span), "the guard sub-step must name exit 2"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    assert re.search(r"immediate", span, re.IGNORECASE), (
        "on exit 2 the step must abort IMMEDIATELY"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    )
    assert re.search(r"no(t)?\b.{0,30}retry|without.{0,20}double-add|do not.{0,20}re-?add", span, re.IGNORECASE), (
        "on exit 2 the step must NOT run the double-add retry"  # tp-allow-fragile: guard exit-code disposition, no structured owner
    )


def test_auto_mode_inherits_staged_blob_guard() -> None:
    """## Auto Mode must state the archival commit inherits the staged-blob guard
    (verify_archive_staged.py as its pre-commit self-check) and logs the abort to
    decisions.md under --auto."""
    block = _auto_mode_block(_read())
    assert "verify_archive_staged.py" in block, (
        "## Auto Mode must name verify_archive_staged.py as the inherited guard"
    )
    assert "decisions.md" in block, (
        "## Auto Mode must state the guard abort is logged to decisions.md"
    )
    assert re.search(r"abort|BLOCK|escalat", block, re.IGNORECASE), (
        "## Auto Mode must state the guard aborts / escalates on failure"
    )
