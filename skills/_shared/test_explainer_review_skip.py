"""test_explainer_review_skip.py — the review loop skips the explainer's own comments.

Covers explainer-agent plan Task 10.3: both review skills (`tp-pr-iterate`
step 4 "Heuristic prefilter", `tp-pr-fix` §"First-pass classification") name
`explainer_marker`'s `drop_marked` and run the comment list through it *before*
`classifier_heuristic.classify`, so a rendered brief and a rulings comment are
never classified while a real reviewer comment still is. Assertions read the
rendered bodies and the prose order, not pinned markup
(skills/_shared/test-fragility.md).
"""
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXPLAINER_DIR = _HERE / "explainer"
_PROOF_DIR = _HERE.parent / "tp-pr-iterate" / "scripts"
for _p in (_PROOF_DIR, _HERE, _EXPLAINER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explainer_marker as em  # noqa: E402
from explain_markdown import render_markdown, render_rulings_comment  # noqa: E402

HEAD = "abc123"
SLUG = "demo-design"

ITERATE_SKILL = _HERE.parent / "tp-pr-iterate" / "SKILL.md"
FIX_SKILL = _HERE.parent / "tp-pr-fix" / "SKILL.md"


def _brief_body() -> str:
    env = {
        "kind": "design",
        "ste_summary": {"text": "What the design does, in plain words.",
                        "refs": []},
        "sections": [{"id": "s1", "title": "Shape",
                      "items": [{"text": "One module, one caller.",
                                 "refs": []}]}],
        "confidence_note": {"text": "High.", "refs": []},
    }
    return render_markdown(env, head=HEAD,
                           marker=em.marker("brief", SLUG, HEAD))


def _rulings_body() -> str:
    rows = [{"id": "r1",
             "ste_summary": {"text": "Ruling one picks the marker.", "refs": []},
             "sections": [{"id": "s1", "title": "Why",
                           "items": [{"text": "Cheaper to skip than to classify.",
                                      "refs": []}]}],
             "confidence_note": {"text": "High.", "refs": []}}]
    return render_rulings_comment(rows, head=HEAD, slug=SLUG)


def test_brief_and_rulings_bodies_carry_the_marker():
    assert em.is_explainer(_brief_body())
    assert em.is_explainer(_rulings_body())


def test_drop_marked_keeps_only_the_reviewer_comment():
    comments = [{"body": _brief_body()}, {"body": _rulings_body()},
                {"body": "please rename x"}]
    kept = em.drop_marked(comments)
    assert [c["body"] for c in kept] == ["please rename x"]


def _section(path: Path, start: str, end: str) -> str:
    """The prose of one numbered step, sliced by its headings."""
    text = path.read_text(encoding="utf-8")
    m = re.search(start, text)
    assert m, f"{path.name}: no step matching {start!r}"
    tail = text[m.end():]
    stop = re.search(end, tail)
    return tail[: stop.start()] if stop else tail


def _drop_precedes_classify(step: str) -> None:
    assert "drop_marked" in step, "step never names drop_marked"
    assert "classify" in step
    assert step.find("drop_marked") < step.find("classify"), (
        "drop_marked must be named before classify")


def test_pr_iterate_prefilter_drops_before_classify():
    step = _section(ITERATE_SKILL, r"\n4\. \*\*Heuristic prefilter\*\*",
                    r"\n5\. \*\*")
    _drop_precedes_classify(step)


def test_pr_fix_first_pass_drops_before_classify():
    step = _section(FIX_SKILL, r"### 2\. First-pass classification[^\n]*\n",
                    r"\n### 3\. ")
    _drop_precedes_classify(step)
