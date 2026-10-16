"""test_ste_lint.py — STE lint length, passive and banned rules at their boundaries.

Covers explainer-agent plan Task 3.3 (detailed-design §Interfaces:
"ste_lint.lint(env) -> {"passed": bool, "issues": [{path, sentence, rule}]}.
Rules: description sentence <= 25 words, list item <= 20, hard fail > 30;
passive heuristic (be-verb + -ed/-en) on <= 20 % of sentences; no BANNED word
(... leverage, utilize, seamless, robust, simply, obviously, under the hood,
...). passed means no hard fail, no banned word, <= 10 % soft-length misses,
and a passive ratio <= 20 %."):
  - a description sentence of 25 words passes, 26 is a soft miss;
  - a list item of 20 words passes, 21 is a soft miss;
  - 30 words is still soft, 31 is a hard fail (passed False);
  - one banned word fails;
  - passive at 20 % passes, above fails; soft misses at 10 % pass, above fail;
  - the plan's sentence split: `.!?;:` + whitespace and newlines, a code span
    is one word, parenthesised text is not counted, ** markup is stripped.

Field forms: ste_summary and confidence_note are description prose; a section
item is a list item unless it carries "form": "description". Issue paths use
the evidence_refs naming (ste_summary, sections[<i>].items[<j>],
confidence_note). Rule names are the issue contract: soft-length,
hard-length, passive, banned. Every envelope is built here; no repo docs are
read (skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import ste_lint  # noqa: E402

# Neutral words: no be-verb, no -ed/-en word, nothing banned.
_VOCAB = ("the", "tool", "reads", "each", "file", "and", "writes", "one",
          "line", "for", "every", "rule", "it", "checks")
_REFS = ["design:problem"]
_SEVEN = ("leverage", "utilize", "seamless", "robust", "simply", "obviously",
          "under the hood")


def _words(n):
    """``n`` neutral words, no closing punctuation."""
    return " ".join(_VOCAB[i % len(_VOCAB)] for i in range(n))


def _sentence(n):
    return _words(n) + "."


def _clean(k):
    """``k`` short clean sentences of eight words each."""
    return " ".join(_sentence(8) for _ in range(k))


def _item(text, form=None):
    item = {"text": text, "refs": list(_REFS)}
    if form is not None:
        item["form"] = form
    return item


def _env(summary="", items=(), note=""):
    """An envelope; each entry of ``items`` is a text (list item) or an item dict."""
    return {
        "schema": "explain-envelope/v1",
        "kind": "auto-ruling",
        "ste_summary": {"text": summary, "refs": list(_REFS)},
        "sections": [{"id": "decided", "title": "Decided",
                      "items": [i if isinstance(i, dict) else _item(i)
                                for i in items]}],
        "diagram_specs": [],
        "confidence_note": {"text": note, "refs": list(_REFS)},
    }


def _issues(result, rule):
    return [i for i in result["issues"] if i["rule"] == rule]


def _bare(text):
    return text.strip().rstrip(".!?;:")


def test_thresholds_are_the_detailed_design_numbers():
    assert ste_lint.DESCRIPTION_MAX_WORDS == 25
    assert ste_lint.LIST_ITEM_MAX_WORDS == 20
    assert ste_lint.HARD_MAX_WORDS == 30
    assert ste_lint.MAX_PASSIVE_PCT == 20
    assert ste_lint.MAX_SOFT_MISS_PCT == 10


def test_banned_is_a_closed_tuple_holding_the_seven():
    assert isinstance(ste_lint.BANNED, tuple)
    assert set(_SEVEN) <= set(ste_lint.BANNED)


def _description_env(text, where):
    if where == "ste_summary":
        return _env(summary=text)
    if where == "confidence_note":
        return _env(note=text)
    return _env(items=[_item(text, form="description")])


_DESC_PATHS = ("ste_summary", "confidence_note", "sections[0].items[0]")


@pytest.mark.parametrize("where", _DESC_PATHS)
def test_description_sentence_of_25_words_passes(where):
    result = ste_lint.lint(_description_env(_sentence(25), where))
    assert result == {"passed": True, "issues": []}


@pytest.mark.parametrize("where", _DESC_PATHS)
def test_description_sentence_of_26_words_is_a_soft_miss(where):
    long = _sentence(26)
    result = ste_lint.lint(_description_env(long + " " + _clean(9), where))
    assert result["passed"] is True  # one soft miss in ten sentences
    assert len(result["issues"]) == 1
    issue = result["issues"][0]
    assert set(issue) == {"path", "sentence", "rule"}
    assert issue["path"] == where
    assert issue["rule"] == "soft-length"
    assert _bare(issue["sentence"]) == _bare(long)


def test_list_item_of_20_words_passes():
    assert ste_lint.lint(_env(items=[_sentence(20)])) == {
        "passed": True, "issues": []}


def test_list_item_of_21_words_is_a_soft_miss():
    items = [_sentence(21)] + [_sentence(8)] * 9
    result = ste_lint.lint(_env(items=items))
    assert result["passed"] is True
    assert result["issues"] == [{"path": "sections[0].items[0]",
                                 "sentence": result["issues"][0]["sentence"],
                                 "rule": "soft-length"}]
    assert _bare(result["issues"][0]["sentence"]) == _words(21)


def test_description_item_of_21_words_is_within_its_limit():
    result = ste_lint.lint(_env(items=[_item(_sentence(21), "description")]))
    assert result == {"passed": True, "issues": []}


def test_30_words_is_still_a_soft_miss():
    result = ste_lint.lint(_env(summary=_sentence(30) + " " + _clean(9)))
    assert [i["rule"] for i in result["issues"]] == ["soft-length"]
    assert result["passed"] is True


@pytest.mark.parametrize("field", ("summary", "item"))
def test_31_words_is_a_hard_fail(field):
    padding = _clean(30)  # one long sentence in 31 stays under 10 %
    if field == "summary":
        env = _env(summary=_sentence(31) + " " + padding)
    else:
        env = _env(summary=padding, items=[_sentence(31)])
    result = ste_lint.lint(env)
    assert result["passed"] is False
    assert [i["rule"] for i in result["issues"]] == ["hard-length"]
    assert _bare(result["issues"][0]["sentence"]) == _words(31)


@pytest.mark.parametrize("word", _SEVEN)
def test_one_banned_word_fails(word):
    bad = f"the tool runs {word} on each file."
    result = ste_lint.lint(_env(summary=bad + " " + _clean(30)))
    assert result["passed"] is False
    hits = _issues(result, "banned")
    assert [h["path"] for h in hits] == ["ste_summary"]
    assert _bare(hits[0]["sentence"]) == _bare(bad)


def test_banned_word_matches_any_case():
    result = ste_lint.lint(_env(items=["Simply run the tool on each file."]))
    assert result["passed"] is False
    assert [i["path"] for i in _issues(result, "banned")] == [
        "sections[0].items[0]"]


@pytest.mark.parametrize("text", (
    "The file is parsed by the tool.",
    "The rule was not written down.",
    "Each line is then checked once.",
))
def test_be_verb_then_ed_or_en_word_is_passive(text):
    result = ste_lint.lint(_env(items=[text]))
    assert [i["rule"] for i in result["issues"]] == ["passive"]


def test_active_sentence_is_not_passive():
    result = ste_lint.lint(_env(items=["The tool parses the file once."]))
    assert result == {"passed": True, "issues": []}


@pytest.mark.parametrize("passive,clean,passed", (
    (1, 4, True),    # 20 %
    (2, 8, True),    # 20 %
    (1, 3, False),   # 25 %
    (3, 7, False),   # 30 %
))
def test_passive_ratio_boundary(passive, clean, passed):
    text = " ".join(["The file is parsed by the tool."] * passive
                    + [_sentence(8)] * clean)
    result = ste_lint.lint(_env(summary=text))
    assert len(_issues(result, "passive")) == passive
    assert result["passed"] is passed


@pytest.mark.parametrize("soft,clean,passed", (
    (1, 9, True),     # 10 %
    (2, 18, True),    # 10 %
    (1, 8, False),    # 11.1 %
    (3, 17, False),   # 15 %
))
def test_soft_miss_ratio_boundary(soft, clean, passed):
    items = [_sentence(22)] * soft + [_sentence(8)] * clean
    result = ste_lint.lint(_env(items=items))
    assert len(_issues(result, "soft-length")) == soft
    assert result["passed"] is passed


@pytest.mark.parametrize("sep", ("; ", ": ", "\n", "! ", "? "))
def test_sentences_split_on_stop_marks_and_newlines(sep):
    # Two 15-word clauses: one 30-word sentence unless the separator splits.
    result = ste_lint.lint(_env(items=[_words(15) + sep + _sentence(15)]))
    assert result == {"passed": True, "issues": []}


def test_a_code_span_counts_as_one_word():
    text = _words(19) + " `explain_cli request --kind pr-brief`."
    assert ste_lint.lint(_env(items=[text])) == {"passed": True, "issues": []}


def test_text_in_parentheses_is_not_counted():
    text = _words(20) + " (and these six words are extra)."
    assert ste_lint.lint(_env(items=[text])) == {"passed": True, "issues": []}


def test_bold_markup_is_stripped_before_the_split():
    # "**Step.**" is its own sentence once the ** markup is gone.
    text = "**Step.** " + _sentence(20)
    assert ste_lint.lint(_env(items=[text])) == {"passed": True, "issues": []}


def test_every_issue_has_path_sentence_and_rule_only():
    env = _env(summary=_sentence(31) + " The file is parsed by the tool.",
               items=["the tool runs seamless checks.", _sentence(22)])
    result = ste_lint.lint(env)
    assert {i["rule"] for i in result["issues"]} == {
        "hard-length", "passive", "banned", "soft-length"}
    for issue in result["issues"]:
        assert set(issue) == {"path", "sentence", "rule"}
        assert all(isinstance(issue[k], str) for k in issue)


def test_empty_envelope_passes():
    assert ste_lint.lint(_env()) == {"passed": True, "issues": []}


def test_malformed_fields_are_skipped_not_raised():
    env = _env(items=[_sentence(8)])
    env["ste_summary"] = None
    env["sections"].append("not a section")
    env["sections"][0]["items"].append({"text": 7, "refs": []})
    assert ste_lint.lint(env) == {"passed": True, "issues": []}
