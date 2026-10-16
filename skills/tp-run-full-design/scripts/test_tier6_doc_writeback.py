"""Tier 6 writes the completion-PR number back into the living docs before the review request.

design: design-complete-final-doc-state (plan task 3.3). Oracle: example, per
`skills/_shared/test-fragility.md`. No assert here reads a heading, a section or a phrase out of the
SKILL.md prose: every command comes through `skill_spans` (the parser `skill_refs` reads references
with) and the region comes from line numbers (the `_tier6_region` slice of `test_pr_author_call_site.py`).
The shipped writeback, scoped add, commit and push are run verbatim in a fixture repo by the sibling
`test_tier6_doc_writeback_shipped.py`, which reads them through `_chain` here.

Run with: python3 -m pytest skills/tp-run-full-design/scripts/test_tier6_doc_writeback.py -q
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
SHARED = REPO_ROOT / "skills" / "_shared"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import skill_text  # noqa: E402

SLUG = "fixture-design"
DOCS = "three-pillars-docs"
LIVE = f"{DOCS}/product_roadmap.md"
DONE_DIR = f"{DOCS}/completed-tp-designs/{SLUG}"
NUMBERLESS, NUMBERED = "Done (completion PR)", "Done — PR #42"
ROW = f"| {SLUG} | Fixture. | design | {NUMBERLESS} — [design]({DONE_DIR}/design.md) | Docs |"
PUSH = ["git", "push", "origin", "tp/{slug}"]


class Cmd(NamedTuple):
    line: int
    span: str
    words: list[str]


def _words(tokens: list[str]) -> list[str]:
    """A span's tokens, with a `VAR="$(cmd ...)"` capture split back into the command's words."""
    words: list[str] = []
    for token in tokens:
        if re.match(r"\w+=\$\(", token):
            inner = re.sub(r"^\w+=\$\(", "", token).removesuffix(")")
            try:
                words.extend(shlex.split(inner))
                continue
            except ValueError:
                pass
        words.append(token)
    return words


def _commands() -> list[Cmd]:
    """Every command or code span the SKILL.md shows, in document order, read through `skill_spans`."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for line, span, shell in skill_spans.code_spans(skill_text.read_skill_text("tp-run-full-design")):
        try:
            found.append(Cmd(line, span, _words(skill_spans.tokens_of(span, shell))))
        except ValueError:  # a span that is not a shell command at all
            continue
    return found


def _heading(pattern: str, after: int = 0) -> int:
    """The 1-based line of the first heading matching *pattern* after line *after*."""
    for number, text in enumerate(skill_text.read_skill_text("tp-run-full-design").splitlines(), start=1):
        if number > after and re.match(pattern, text):
            return number
    raise AssertionError(f"no heading {pattern!r} after line {after}")


def _tier6() -> tuple[int, int]:
    start = _heading(r"## Tier 6\b")
    return start, _heading(r"## Tier 7\b", start)


def _in(cmds: list[Cmd], start: int, end: int) -> list[Cmd]:
    return [c for c in cmds if start <= c.line < end]


def _tier6_commands() -> list[Cmd]:
    return _in(_commands(), *_tier6())


def _writeback_calls(cmds: list[Cmd]) -> list[Cmd]:
    return [c for c in cmds if "--pre-merge" in c.words and any(w.endswith("/reconcile_docs.py") for w in c.words)]


def _chain_step(words: list[str]) -> bool:
    """A writeback-chain command: the `--pre-merge` writeback, or a `git add` / `commit` / `push`."""
    return ("--pre-merge" in words and any(w.endswith("/reconcile_docs.py") for w in words)) or (
        words[:2] in (["git", "add"], ["git", "commit"], ["git", "push"]))


def _first(cmds: list[Cmd], match, after: int = -1) -> int:
    """Index of the first command after position *after* satisfying *match*."""
    for pos, cmd in enumerate(cmds):
        if pos > after and match(cmd.words):
            return pos
    raise AssertionError("no command matches")


def _create(words: list[str]) -> bool:
    return "python3" in words and "pr-create" in words and "--context" in words and "autonomous" in words


def _review(words: list[str]) -> bool:
    return words[:2] == ["gh", "api"] and any(t.startswith("reviewers[]=") for t in words)


def _chain() -> dict[str, tuple[int, Cmd]]:
    """The Tier 6 writeback chain: create, writeback, scoped add, commit, then the FIRST push after the
    commit (the outcomes list names the same push again), then the review request."""
    cmds = _tier6_commands()
    create = _first(cmds, _create)
    writeback = _first(cmds, lambda w: "--pre-merge" in w and any(t.endswith("/reconcile_docs.py") for t in w), create)
    add = _first(cmds, lambda w: w[:2] == ["git", "add"], writeback)
    commit = _first(cmds, lambda w: w[:2] == ["git", "commit"] and "docs({slug})" in " ".join(w), add)
    push = _first(cmds, lambda w: w == PUSH, commit)
    review = _first(cmds, _review, create)
    return {name: (pos, cmds[pos]) for name, pos in (
        ("create", create), ("writeback", writeback), ("add", add), ("commit", commit),
        ("push", push), ("review", review))}


# --- the Tier 6 command list ---------------------------------------------------------------------


def test_writeback_follows_the_create_and_precedes_the_review_request():
    """create -> writeback -> scoped add -> commit -> push -> review request, each adjacent pair on its
    own; and no part of the chain (a retry push, say) sits after the review request in the
    create-succeeded path, i.e. before `### Step 3`."""
    chain = _chain()
    names = ("create", "writeback", "add", "commit", "push", "review")
    for first, then in zip(names, names[1:]):
        (at_first, cmd_first), (at_then, cmd_then) = chain[first], chain[then]
        assert at_first < at_then, (f"out of order: the {first} (line {cmd_first.line}) must precede "
                                    f"the {then} (line {cmd_then.line})")
    step3 = _heading(r"### Step 3\b", _tier6()[0])
    cmds = _tier6_commands()
    late = [(c.line, c.span) for c in cmds[chain["review"][0] + 1:] if c.line < step3 and _chain_step(c.words)]
    assert not late, f"writeback step after the review request (before Step 3): {late}"


def test_writeback_names_the_design_and_the_pr_and_parses(tmp_path):
    argparse_probe = pytest.importorskip("argparse_probe")
    args = _chain()["writeback"][1].words
    args = args[args.index("python3") + 2:]
    assert args[args.index("--slug") + 1] == "{slug}"
    assert {"--pr", "--apply", "--json"} <= set(args), args
    probe = argparse_probe.probe(SHARED / "reconcile_docs.py", [a.replace("{n}", "1") for a in args],
                                 cache_dir=tmp_path)
    assert probe["status"] == "parsed", probe["message"]


def test_the_add_is_scoped_to_the_edited_paths():
    words = _chain()["add"][1].words
    assert not {"-A", "--all", "."} & set(words), words
    assert any("edits[]" in t for t in words), words


def test_the_commit_message_names_the_pr():
    message = _chain()["commit"][1].words[-1]
    assert message == "docs({slug}): completion PR #{n} in living docs"


def test_the_writeback_failure_token_is_logged_between_the_writeback_and_the_review():
    cmds = _tier6_commands()
    chain = _chain()
    logged = [pos for pos, c in enumerate(cmds)
              if "[tp-run-full-design/tier-6]" in c.span and "doc-writeback-failed" in c.span]
    assert logged, "Tier 6 must log doc-writeback-failed"
    assert chain["writeback"][0] < logged[0] < chain["review"][0], (
        f"doc-writeback-failed (command {logged[0]}) is not between the writeback "
        f"({chain['writeback'][0]}) and the review request ({chain['review'][0]})")


def test_the_tier_names_the_shared_protocol_doc():
    named = [c for c in _tier6_commands() if "skills/_shared/final-doc-state.md" in c.span]
    assert named, "Tier 6 must point at skills/_shared/final-doc-state.md"
    assert (SHARED / "final-doc-state.md").is_file()


def test_the_outcomes_name_the_writeback_push_before_tier_7():
    start = _heading(r"### Tier 6 outcomes", _tier6()[0])
    pushes = [c for c in _in(_commands(), start, _tier6()[1]) if c.words == PUSH]
    assert pushes, "the Tier 6 outcomes must name the writeback push (git push origin tp/{slug})"
    assert _chain()["writeback"][1].line < start


def test_a_create_failure_runs_no_writeback():
    """The writeback lies in the create-succeeded path, before Step 3; the failure path holds no part of it."""
    step3 = _heading(r"### Step 3\b", _tier6()[0])
    step4 = _heading(r"### Step 4\b", step3)
    assert _chain()["push"][1].line < step3
    failure = _in(_commands(), step3, step4)
    assert failure, "Step 3 must show its fail-open commands"
    assert not _writeback_calls(failure)
    assert not [c for c in failure if c.words[:2] in (["git", "add"], ["git", "commit"], ["git", "push"])]


def test_the_legacy_fold_conflict_fallback_runs_no_writeback():
    legacy = _heading(r"#### Tier 6 — legacy fallback", _tier6()[0])
    step2 = _heading(r"### Step 2\b", legacy)
    fallback = _in(_commands(), legacy, step2)
    assert [c for c in fallback if "--base" in c.words and "tp/{slug}" in c.words], "the --base tp/{slug} PR"
    assert _writeback_calls(_tier6_commands()), "the completion path must run the writeback"
    assert not _writeback_calls(fallback)
