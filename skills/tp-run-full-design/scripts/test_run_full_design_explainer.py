"""The `/tp-run-full-design` explainer wiring: Tier 5.6 Step 2b, Tier 6 and Tier 7 (dev repo only).

design: explainer-agent (plan Task 10.2; detailed-design §Wiring: the autonomous equivalents of the
`/tp-design-complete` 6b3 draft and 6g post, plus the Tier 7 refresh and `rulings-fold`). The SKILL.md
only points at `skills/_shared/explainer.md`; it never copies the protocol and never spawns
`tp-explainer` itself (the file is a `DOC_SITE` of `test_role_engine_guard_spans.py`).

Per `skills/_shared/test-fragility.md` the checks read structure, not wording: a region is the line
range of a heading (the file repeats `## Tier 6` as an inline cross-ref, so `str.index` on prose would
land on the wrong one), and every `explain_cli.py` call is read through `skill_spans` (the parser
`skill_refs` reads with), so its subcommand, flags and `||` guard are parsed tokens. The two prose pins
are the PR-head checkout rule and the archived paths the `two-stable` flush commit stages.

Run with: python3 -m pytest skills/tp-run-full-design/scripts/test_run_full_design_explainer.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
if str(REPO_ROOT / "skills" / "_shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))

import skill_text  # noqa: E402


def _lines() -> list[str]:
    return skill_text.read_skill_text("tp-run-full-design").split("\n")


def _range(heading: str) -> tuple[int, int]:
    """`(first, last)` 0-based lines of the section whose heading line starts with *heading*:
    up to the next heading of the same or a shallower level."""
    lines = _lines()
    level = len(heading) - len(heading.lstrip("#"))
    starts = [i for i, line in enumerate(lines) if line.startswith(heading)]
    assert len(starts) == 1, (heading, starts)
    stop = re.compile(r"^#{1,%d} " % level)
    end = next((i for i in range(starts[0] + 1, len(lines)) if stop.match(lines[i])), len(lines))
    return starts[0], end - 1


def _slice(first: int, last: int) -> str:
    return "\n".join(_lines()[first:last + 1])


def _cli_calls(first: int, last: int) -> list[tuple[int, str, list[str], list[str]]]:
    """`(line, subcommand, args, raw tokens)` of every `explain_cli.py <sub> ...` command in the
    range, in document order (a line is 0-based, in the whole file)."""
    skill_spans = pytest.importorskip("skill_spans")
    calls = []
    for rel, span, shell in skill_spans.code_spans(_slice(first, last)):
        try:
            tokens = skill_spans.tokens_of(span, shell)
        except ValueError:  # a span that is not a shell command at all
            continue
        for i, word in enumerate(tokens[:-1]):
            if word.endswith("/explain_cli.py") or word == "explain_cli.py":
                calls.append((first + rel - 1, tokens[i + 1], tokens[i + 2:], tokens))
    return calls


def _call(first: int, last: int, sub: str) -> tuple[int, list[str], list[str]]:
    hits = [(line, args, tokens) for line, name, args, tokens in _cli_calls(first, last)
            if name == sub]
    assert len(hits) == 1, f"want one explain_cli.py {sub} in lines {first}-{last}, got {hits}"
    return hits[0]


# ---- Tier 5.6 Step 2b ------------------------------------------------------------------------


def test_tier_5_6_has_a_step_2b_between_step_2_and_the_archive_step():
    first, last = _range("## Tier 5.6")
    steps = [re.match(r"### Step (\w+)", line).group(1) for line in _lines()[first:last + 1]
             if line.startswith("### Step ")]
    assert steps == ["1", "2", "2b", "3"], steps


def test_step_2b_drafts_the_brief_before_the_archive_dispatch_and_is_off_unless_enabled():
    first, last = _range("## Tier 5.6")
    s2b_first, s2b_last = _range("### Step 2b — Draft the PR brief")
    assert first < s2b_first <= s2b_last <= last
    assert "skills/_shared/explainer.md" in _slice(s2b_first, s2b_last)
    assert [name for _, name, _, _ in _cli_calls(s2b_first, s2b_last)] == ["enabled"]
    dispatch = next(i for i in range(first, last + 1)
                    if "/tp-design-complete {slug} --auto" in _lines()[i])
    assert s2b_last < dispatch


# ---- Tier 6 ----------------------------------------------------------------------------------


def test_tier_6_posts_the_brief_then_syncs_rulings_after_the_pr_number_writeback():
    first, last = _range("## Tier 6")
    wb_first, wb_last = _range("### Step 2b — PR-number writeback")
    assert first < wb_first <= wb_last <= last
    post_line, post_args, _ = _call(first, last, "post")
    sync_line, sync_args, _ = _call(first, last, "rulings-sync")
    assert wb_first < post_line < sync_line
    for args in (post_args, sync_args):
        assert "||" in args and "--pr" in args and "--slug" in args  # fail-open, one PR
    assert post_args[post_args.index("--context") + 1] == "autonomous"


def test_tier_6_pr_body_leads_with_the_headline_and_rulings_sync_runs_autonomous():
    first, last = _range("## Tier 6")
    head_line, head_args, _ = _call(first, last, "headline")
    assert "--slug" in head_args and "||" in head_args and head_args[-1] == "true"
    lines = _lines()
    create = next(i for i in range(first, last + 1) if 'pr-create' in lines[i] and '"$FORGE"' in lines[i])
    assert head_line < create
    body = next(lines[i] for i in range(create, last + 1) if "--body" in lines[i])
    assert re.search(r"\$\{?HEADLINE\}?", body.split("structured PR description")[0])
    assert "structured PR description" in body
    _, sync_args, _ = _call(first, last, "rulings-sync")
    assert sync_args[sync_args.index("--context") + 1] == "autonomous"


# ---- Tier 7 terminal -------------------------------------------------------------------------


def _tier7_spans() -> list[tuple[int, str]]:
    skill_spans = pytest.importorskip("skill_spans")
    first, last = _range("## Tier 7")
    return [(first + rel - 1, span) for rel, span in skill_spans.spans(_slice(first, last))]


def test_tier_7_terminal_checks_refresh_then_folds_rulings_before_the_log_flush():
    first, last = _range("## Tier 7")
    spans = [span for _, span in _tier7_spans()]

    def at(needle: str) -> int:  # the document-order index of the one span holding *needle*
        hits = [i for i, span in enumerate(spans) if needle in span]
        assert len(hits) == 1, (needle, hits)
        return hits[0]

    assert at("explain_cli.py refresh-needed") < at("explain_cli.py post") \
        < at("explain_cli.py rulings-fold") < at("round_scratch.py flush")
    _, refresh_args, refresh_tokens = _call(first, last, "refresh-needed")
    _, post_args, _ = _call(first, last, "post")
    _, fold_args, _ = _call(first, last, "rulings-fold")
    # `refresh-needed` exits 0 stale / 1 current, so `|| true` would defeat it: an `if` guard (or the
    # printed line); every other delivery call is guarded with `||`.
    assert refresh_tokens[0] == "if" or "||" in refresh_args
    assert "--envelope" in post_args and "||" in post_args
    assert "||" in fold_args and "--slug" in fold_args


def test_tier_7_pointer_names_the_archived_paths_the_two_stable_flush_commit_stages():
    first, last = _range("## Tier 7")
    fold_line, _, _ = _call(first, last, "rulings-fold")
    on_line = [span for line, span in _tier7_spans() if line == fold_line]
    assert any(s.endswith("completed-tp-designs/{slug}/rulings.ndjson") for s in on_line), on_line
    assert any(s.endswith("completed-tp-designs/{slug}/decisions.md") for s in on_line), on_line
    assert "two-stable" in _lines()[fold_line]


def test_tier_7_pointer_says_the_refresh_post_runs_on_a_checkout_of_the_pr_head():
    first, last = _range("## Tier 7")
    post_line, _, _ = _call(first, last, "post")
    assert re.search(r"checkout of the PR head", " ".join(_lines()[post_line].split()))


# ---- no spawn --------------------------------------------------------------------------------


def test_the_skill_never_spawns_tp_explainer():
    skill_spans = pytest.importorskip("skill_spans")
    agent_spans = [t for _, t in skill_spans.spans("\n".join(_lines())) if t.startswith("Agent(")]
    assert agent_spans, "the guard is vacuous if the parser sees no Agent( span"
    assert not [t for t in agent_spans if "tp-explainer" in t], agent_spans
