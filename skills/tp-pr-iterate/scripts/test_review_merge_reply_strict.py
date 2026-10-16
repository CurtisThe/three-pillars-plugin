"""The review-angle reply contract is strict: no non-conforming reply is ever read as clean.

Known issue M27, PRs #188 and #191. The reply is exactly one JSON object
`{"findings": [...], "notes"?: str}`, bare or inside ONE fence (`strict_json_reply`, the
finalizer's contract). Prose around it, a second object or fence, a bare list (the old
format), a JSON string, a repeated key, an unknown key or a non-dict finding is unparseable:
the angle contributes its structural sentinel, never an empty list. A seeded generated-input
loop (hypothesis is not a dev dependency) mutates conforming replies into non-conforming ones.
Run with: python3 -m pytest skills/tp-pr-iterate/scripts/test_review_merge_reply_strict.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_merge  # noqa: E402

F = "\x60" * 3  # three backticks, built at runtime
CASES_PER_MUTATION = 300
# Hostile string content: fences, braces, brackets, quotes, and the clean fragment itself.
PIECES = ["bug", "a.py", F, F + "json", "~~~", "{", "}", "[]", '"', "\\", "\n",
          '{"findings": []}', F + "json\n[]\n" + F, "assert x == []", " "]


def _text(rng) -> str:
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 8)))


def _finding(rng) -> dict:
    f = {"file": rng.choice(["a.py", "b/c.py"]), "line_range": [1, rng.randint(1, 9)],
         "summary": "bug " + _text(rng), "class": rng.choice("PXTC"),
         "blocking": rng.random() < 0.5}
    if f["blocking"]:
        f["reproducer"] = {"kind": "test", "source": "def test_x():\n    " + _text(rng)}
    return f


def _reply(rng) -> dict:
    env = {"findings": [_finding(rng) for _ in range(rng.randint(1, 3))]}
    if rng.random() < 0.5:
        env["notes"] = _text(rng)
    return env


def _prose(rng) -> str:  # starts with a letter, so it is never itself JSON or a fence
    return rng.choice(["Done", "Review", "Clean", "Note"]) + rng.choice(
        ["", ":", ".", " " + json.dumps({"findings": []}), " " + F + "json", " []"])


def _conforming(rng, env) -> str:
    body = json.dumps(env, indent=rng.choice([None, 2]))
    if rng.random() < 0.5:
        return body
    fence = rng.choice([F, F + "\x60", "~~~"])
    return fence + rng.choice(["json", "", "JSON"]) + "\n" + body + "\n" + fence + "\n"


def _obj_text(env, extra="") -> str:
    return json.dumps(env)[:-1] + extra + "}"


def _cut(r, s: str) -> str:
    return s[:r.randint(1, len(s) - 1)]


MUTATIONS = {
    "prose-before": lambda r: _prose(r) + "\n" + _conforming(r, _reply(r)),
    "prose-after": lambda r: _conforming(r, _reply(r)) + "\n" + _prose(r),
    "two-objects": lambda r: _conforming(r, _reply(r)) + "\n" + _conforming(r, {"findings": []}),
    "two-fences": lambda r: (F + "\n" + json.dumps(_reply(r)) + "\n" + F + "\n") * 2,
    "clean-example-then-findings": lambda r: (F + "json\n" + json.dumps({"findings": []}) + "\n"
                                              + F + "\n" + _conforming(r, _reply(r))),
    "prose-in-fence": lambda r: F + "json\n" + _prose(r) + "\n" + json.dumps(_reply(r)) + "\n" + F,
    "truncated": lambda r: _cut(r, json.dumps(_reply(r))),
    "truncated-fenced": lambda r: F + "json\n" + _cut(r, json.dumps(_reply(r))) + "\n" + F,
    "trailing-comma": lambda r: _obj_text(_reply(r), ","),
    "duplicate-findings": lambda r: _obj_text(_reply(r), ', "findings": []'),
    "duplicate-key-in-finding": lambda r: json.dumps({"findings": [_finding(r)]})[:-3]
    + ', "blocking": false}]}',
    "unescaped-quote": lambda r: ('{"findings": [{"file": "a.py", "summary": "printed '
                                  '{"findings": []} ' + _text(r).replace('"', "") + '"}]}'),
    "unclosed-fence": lambda r: F + "json\n" + json.dumps(_reply(r)) + "\n",
    "mismatched-fence": lambda r: F + "json\n" + json.dumps(_reply(r)) + "\n~~~\n",
    "bare-list": lambda r: _conforming(r, _reply(r)["findings"]) if r.random() < 0.9
    else _conforming(r, []),
    "not-an-object": lambda r: r.choice(["null", "12", "true", '"clean"', ""]),
    "json-string": lambda r: json.dumps(_conforming(r, r.choice([_reply(r), {"findings": []}]))),
    "opener-line-prose": lambda r: F + "json " + _prose(r) + "\n" + json.dumps(_reply(r)) + "\n" + F,
    "opener-line-object": lambda r: (F + json.dumps({"findings": []}) + "\n"
                                     + json.dumps(_reply(r)) + "\n" + F),
    "long-opener-short-closer": lambda r: F + "\x60" + "json\n" + json.dumps(_reply(r)) + "\n" + F,
    "deep-nesting": lambda r: r.choice(["[", '{"a": '])[:6] * r.randint(10_000, 20_000),
    "unknown-key": lambda r: json.dumps(dict(r.choice([_reply(r), {"findings": []}]),
                                             **{r.choice(["blocking", "Findings", "extra"]): []})),
    "no-findings-key": lambda r: json.dumps(r.choice([{}, {"notes": _text(r)}])),
    "findings-not-list": lambda r: json.dumps({"findings": r.choice([None, {}, "[]", 0])}),
    "non-dict-finding": lambda r: json.dumps({"findings": _reply(r)["findings"]
                                              + [r.choice([1, "x", [], None])]}),
    "notes-not-str": lambda r: json.dumps({"findings": [], "notes": r.choice([[], {}, 1, True])}),
}


def test_the_generator_is_not_vacuous():
    """Every generated reply, sent conforming, parses to exactly its findings."""
    rng = random.Random(191)
    for _ in range(CASES_PER_MUTATION):
        env = _reply(rng)
        text = _conforming(rng, env)
        assert review_merge.parse_codereview_result(text) == (env["findings"], True), text
        assert review_merge.merge_codereview_angles([text]) != [], text


@pytest.mark.parametrize("text", ['{"findings": []}', F + "json\n{\"findings\": []}\n" + F + "\n",
                                  '{"findings": [], "notes": "context: read a.py only"}',
                                  '{"findings": [], "notes": null}',  # r1: null is absent
                                  '\ufeff{"findings": []}\n'])  # r1: a BOM is not prose
def test_the_clean_reply_is_clean(text):
    assert review_merge.parse_codereview_result(text) == ([], True)
    assert review_merge.merge_codereview_angles([text]) == []


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_no_non_conforming_reply_is_ever_clean(name):
    rng = random.Random(f"191:{name}")
    for _ in range(CASES_PER_MUTATION):
        text = MUTATIONS[name](rng)
        assert review_merge.parse_codereview_result(text) == ([], False), (name, text)
        merged = review_merge.merge_codereview_angles([text])
        assert review_merge.is_degraded_review(merged), (name, text, merged)


# --- reproducers ---

_BLOCKER = {"file": "a.py", "line_range": [1, 2], "summary": "blocker", "class": "P",
            "blocking": True,
            "reproducer": {"kind": "test", "source": f'assert parse("{F}json\\n[]\\n{F}") == []'}}


def test_m27_backticks_inside_a_finding_keep_the_blocker():
    """M27 / PR #170: a reproducer quoting a fence used to cut the reply short."""
    for text in (json.dumps({"findings": [_BLOCKER]}),
                 F + "json\n" + json.dumps({"findings": [_BLOCKER]}, indent=2) + "\n" + F + "\n"):
        assert review_merge.parse_codereview_result(text) == ([_BLOCKER], True)


def test_188_191_clean_example_fence_no_longer_hides_a_blocker():
    """PRs #188/#191: the lenient parser read this reply as ([], True) — clean — because the
    example `[]` fence parsed and the real findings fence broke on its inner backticks."""
    text = ("Output shape per the prompt; a clean reply would be:\n" + F + "json\n[]\n" + F
            + "\n\nThis one is not clean:\n" + F + "json\n" + json.dumps([_BLOCKER]) + "\n" + F + "\n")
    assert review_merge.parse_codereview_result(text) == ([], False)
    merged = review_merge.merge_codereview_angles([text])
    assert len(merged) == 1 and merged[0]["verdict"] == "structural"


def test_non_str_reply_is_unparseable_not_a_crash():
    for bad in (None, 123, {"findings": []}, ["a"]):
        assert review_merge.parse_codereview_result(bad) == ([], False)
