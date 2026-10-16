"""The `/tp-design-complete` explainer wiring: steps 6b3, 6f and 6g (dev repo only).

design: explainer-agent (plan Task 10.1; detailed-design §Wiring: "tp-design-complete/SKILL.md
gets a new step 6b3 draft (after 6b2 `number_issues`, before the 6c `git mv`), the 6f stage, and
a 6g post"). The SKILL.md only points at `skills/_shared/explainer.md`; it never copies the
protocol and never spawns `tp-explainer` itself (plan §Conventions, last bullet).

Per `skills/_shared/test-fragility.md` the checks read structure, not wording: the step labels
(`b2`, `b3`, `c`) are the document's own structure; the commands are read through `skill_spans`
(the parser `skill_refs` reads them with), so each `explain_cli.py` call, each `git add` line and
the `--body` of the PR command are parsed tokens, and `explainer.md`'s call points are its
numbered list items. The one prose pin is that 6b3 says it never spawns under `--auto`.

Run with: pytest skills/tp-design-complete/scripts/test_design_complete_explainer.py -q
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
SKILL_MD = SCRIPTS.parent / "SKILL.md"
REPO_ROOT = SCRIPTS.parents[2]
EXPLAINER_MD = REPO_ROOT / "skills" / "_shared" / "explainer.md"
if str(REPO_ROOT / "skills" / "_shared") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "skills" / "_shared"))

STEP_LABEL = re.compile(r"^ {3}([a-z]\d?)\.\s")  # "   b3. **Draft ..." (a step under step 6)
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _step_ranges() -> dict[str, tuple[int, int]]:
    """`{label: (first_line, last_line)}` (1-based, inclusive) of every step-6 sub-step."""
    lines = _text().split("\n")
    starts = [(m.group(1), i + 1) for i, line in enumerate(lines)
              if (m := STEP_LABEL.match(line))]
    return {label: (start, (starts[k + 1][1] - 1) if k + 1 < len(starts) else len(lines))
            for k, (label, start) in enumerate(starts)}


def _step_text(label: str) -> str:
    first, last = _step_ranges()[label]
    return "\n".join(_text().split("\n")[first - 1:last])


def _words(tokens: list[str]) -> list[str]:
    """A span's tokens, with a `VAR="$(cmd ...)"` capture split back into the command's words."""
    words: list[str] = []
    for token in tokens:
        if " " in token and re.match(r"^\w+=\$\(", token):
            inner = re.sub(r"^\w+=\$\(", "", token).removesuffix(")")
            try:
                words.extend(shlex.split(inner))
                continue
            except ValueError:
                pass
        words.append(token)
    return words


def _spans() -> list[tuple[int, list[str], list[str]]]:
    """`(line, raw tokens, words)` of every command the SKILL.md shows, in document order."""
    skill_spans = pytest.importorskip("skill_spans")
    found = []
    for line, span, shell in skill_spans.code_spans(_text()):
        try:
            tokens = skill_spans.tokens_of(span, shell)
        except ValueError:  # a span that is not a shell command at all
            continue
        found.append((line, tokens, _words(tokens)))
    return found


def _cli_calls(label: str | None = None) -> list[tuple[int, str, list[str], list[str]]]:
    """`(line, subcommand, args, raw tokens)` of every `explain_cli.py <sub> ...` command, in
    document order, optionally limited to one step's lines."""
    first, last = _step_ranges()[label] if label else (0, 10**9)
    calls = []
    for line, tokens, words in _spans():
        if not first <= line <= last:
            continue
        for i, word in enumerate(words[:-1]):
            if word.endswith("/explain_cli.py") or word == "explain_cli.py":
                calls.append((line, words[i + 1], words[i + 2:], tokens))
    return calls


def _call(label: str, sub: str) -> tuple[int, list[str], list[str]]:
    hits = [(line, args, tokens) for line, name, args, tokens in _cli_calls(label) if name == sub]
    assert len(hits) == 1, f"step {label}: want one explain_cli.py {sub}, got {hits}"
    return hits[0]


def _pr_create() -> tuple[int, list[str]]:
    hits = [(line, tokens) for line, tokens, words in _spans()
            if "pr-create" in words and "--body" in words]
    assert len(hits) == 1, hits
    return hits[0]


# ---- 6b3 -------------------------------------------------------------------------------------


def test_step_6b3_sits_between_6b2_and_6c():
    labels = list(_step_ranges())
    assert labels.index("b2") + 1 == labels.index("b3") and labels.index("b3") + 1 == labels.index("c")


def test_step_6b2_is_still_number_issues():
    assert "number_issues.py" in _step_text("b2")


def test_6b3_cites_the_protocol_doc_and_the_enabled_guard():
    assert "skills/_shared/explainer.md" in _step_text("b3")
    assert [name for _, name, _, _ in _cli_calls("b3")] == ["enabled"]


def test_6b3_under_auto_only_checks_for_the_caller_drafted_brief_and_never_spawns():
    body = _step_text("b3")
    assert "--auto" in body and "brief.md" in body
    assert re.search(r"never spawns?|does not spawn|no spawn", body, re.I), body


# ---- 6f --------------------------------------------------------------------------------------


@pytest.mark.parametrize("artifact", ["brief.md", "rulings.ndjson"])
def test_6f_stages_each_explainer_artifact_with_its_own_fail_open_git_add(artifact):
    first, last = _step_ranges()["f"]
    adds = [words for line, _, words in _spans()
            if first <= line <= last and words[:2] == ["git", "add"]
            and any(w.endswith("/" + artifact) for w in words)]
    assert len(adds) == 1, adds
    words = adds[0]
    pathspecs = [w for w in words[2:] if "/" in w and not w.startswith("2>")]
    assert pathspecs == [f"three-pillars-docs/completed-tp-designs/{{design-name}}/{artifact}"]
    assert "2>/dev/null" in words and "||" in words  # absent when the explainer is off


# ---- 6g --------------------------------------------------------------------------------------


def test_6g_starts_the_pr_body_with_the_headline_capture():
    _, args, headline_tokens = _call("g", "headline")
    assert "||" in args  # the headline never blocks the PR
    var = re.match(r"^(\w+)=\$\(", headline_tokens[0])
    assert var, headline_tokens
    pr_line, pr_tokens = _pr_create()
    assert _call("g", "headline")[0] < pr_line
    body = pr_tokens[pr_tokens.index("--body") + 1]
    assert body.startswith(("${%s}" % var.group(1), "$" + var.group(1))), body[:60]


def test_6g_posts_the_brief_then_syncs_rulings_after_the_pr_is_created():
    pr_line, _ = _pr_create()
    post_line, post_args, _ = _call("g", "post")
    sync_line, sync_args, _ = _call("g", "rulings-sync")
    assert pr_line < post_line < sync_line
    for args in (post_args, sync_args):
        assert "||" in args and "--pr" in args and "--slug" in args


def test_every_explainer_call_in_the_skill_but_enabled_is_fail_open():
    calls = _cli_calls()
    assert {name for _, name, _, _ in calls} >= {"enabled", "headline", "post", "rulings-sync"}
    for line, name, args, _ in calls:
        assert name == "enabled" or "||" in args, (line, name, args)


# ---- no spawn, no model literal --------------------------------------------------------------


def test_the_skill_never_spawns_tp_explainer_or_names_a_cheap_model():
    skill_spans = pytest.importorskip("skill_spans")
    agent_spans = [t for _, t in skill_spans.spans(_text()) if t.startswith("Agent(")]
    assert not [t for t in agent_spans if "tp-explainer" in t], agent_spans
    assert not re.search(r'model\s*=\s*"?(sonnet|haiku)\b', _text(), re.I)


# ---- explainer.md §Call points ---------------------------------------------------------------


def _call_points() -> tuple[str, list[str]]:
    """`(intro paragraph, [item text])` of explainer.md's `## Call points` section."""
    text = EXPLAINER_MD.read_text(encoding="utf-8")
    section = re.search(r"^## Call points\n(.*?)(?=^## )", text, re.M | re.S).group(1)
    intro, _, rest = section.partition("\n1. ")
    items = re.split(r"\n(?=\d+\. )", "1. " + rest.split("\n\n")[0])
    return intro, [re.sub(r"\s+", " ", item) for item in items]


def test_call_points_lists_6g_post_then_rulings_sync():
    _, items = _call_points()
    item = next(i for i in items if "/tp-design-complete" in i and "6g" in i)
    assert item.index("post") < item.index("rulings-sync")
    assert "PR" in item


def test_call_points_6b3_item_no_longer_commits_the_brief():
    _, items = _call_points()
    item = next(i for i in items if "6b3" in i and "/tp-design-complete" in i and "6g" not in i)
    assert not re.search(r"\bcommits?\b", item), item
    assert "6f" in item and "brief.md" in item


def test_call_points_count_line_matches_the_items():
    intro, items = _call_points()
    word = intro.strip().split()[0].lower()
    assert NUMBER_WORDS[word] == len(items), (intro, items)
