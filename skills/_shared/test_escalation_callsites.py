"""test_escalation_callsites.py - the escalation protocol doc and its callsites (design: fable-escalation).

Structural only (`test-fragility.md`): read via headings and `skill_spans`, never free prose; no char-count literal.
`skill_spans` / `release_tiers` are dev-only, so each is `importorskip`ped inside its helper, never at module top.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SHARED = REPO_ROOT / "skills" / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import skill_text  # noqa: E402

ESCALATION_MD = _SHARED / "escalation.md"

SECTIONS = ("Principles", "Run", "Commit points", "Seat", "Explain", "Hook", "Lessons")

# The two principles that move out of the run skill into §Principles. Each is matched
# inside the paragraph that states it, so the wording may be re-flowed across lines.
FALLBACK_NEEDLES = ("escalation to a human", "terminal fallback", "not the first response")
FLOOR_NEEDLES = ("floor is", "never removed", "who tries first")


def _text() -> str:
    return ESCALATION_MD.read_text(encoding="utf-8")


def _heading_lines() -> list[str]:
    return [ln for ln in _text().splitlines() if ln.startswith("#")]


def _section_body(name: str) -> str:
    """The lines after the `## <name>` heading, up to the next heading of any level."""
    lines = _text().splitlines()
    wanted = f"## {name}".lower()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == wanted), None)
    if start is None:
        return ""
    body = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        body.append(line)
    return "\n".join(body)


def _paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n[ \t]*\n", text) if p.strip()]


def _path_text(path: Path) -> str:
    if path == REPO_ROOT / "skills" / "tp-run-full-design" / "SKILL.md":
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _span_tokens(path: Path) -> list[str]:
    """Every token of every code span / fenced line of *path*, split the way skill_refs splits."""
    skill_spans = pytest.importorskip("skill_spans")
    tokens: list[str] = []
    for _line, span in skill_spans.spans(_path_text(path)):
        try:
            tokens.extend(skill_spans.tokens_of(span, shell=False))
        except ValueError:
            continue
    return tokens


def test_escalation_doc_sections():
    assert ESCALATION_MD.is_file(), "the escalation protocol doc is missing"
    headings = [h.lstrip("#").strip() for h in _heading_lines()]
    for name in SECTIONS:
        assert name in headings, f"escalation.md has no `## {name}` section"


def test_escalation_doc_holds_moved_principles():
    """§Principles states both principles moved out of the run skill (detailed design §Net-zero)."""
    body = _section_body("Principles").lower()
    assert body, "escalation.md §Principles is empty"
    paragraphs = _paragraphs(body)
    for needles in (FALLBACK_NEEDLES, FLOOR_NEEDLES):
        assert any(all(n in p for n in needles) for p in paragraphs), (
            f"§Principles states no paragraph holding {needles}"
        )


def test_escalation_doc_references_resolve():
    """Every `skills/...` path and `/tp-*` token the doc cites in a span exists."""
    missing = []
    for token in _span_tokens(ESCALATION_MD):
        if token.startswith("/tp-"):
            name = token[1:].split()[0]
            if not (REPO_ROOT / "skills" / name).is_dir():
                missing.append(token)
        elif token.startswith("skills/") or token.startswith("$TP_ROOT/skills/"):
            rel = token.split("$TP_ROOT/", 1)[-1].split("$TP_ROOT")[0]
            if not (REPO_ROOT / rel).exists():
                missing.append(token)
    assert missing == []


def test_escalation_doc_names_no_pro_skill():
    """The leak guard rule for shipped prose: no pro-exclusive skill name in the doc."""
    tiers = pytest.importorskip("release_tiers")
    names = [n for n in tiers.load_tiers(REPO_ROOT).get("pro_exclusive_skills", [])]
    text = _text().lower()
    assert names, "the pro-skill list is empty - the check would pass vacuously"
    assert [n for n in names if n.lower() in text] == []
# --- Task 6.5: the seat skill and the four run skills cite the protocol -------------

# The skills whose prose routes a question or an operator card: the three run skills
# plus the seat skill. The fleet seat skill is checked by its own test.
RUN_SKILLS = ("tp-run-full-design", "tp-pr-iterate", "tp-merge-from-main", "tp-escalate")
ESCALATION_SPAN = "skills/_shared/escalation.md"
# The card phrases, lower-cased: prose that mentions one of these must point at the
# protocol in the same heading section, so a card can never be re-invented locally.
CARD_PHRASES = ("askuserquestion", "ask the operator", "operator card")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _skill(name: str) -> Path:
    return REPO_ROOT / "skills" / name / "SKILL.md"


def _heading_sections(path: Path) -> list[tuple[int, int, list[str]]]:
    """`(first_line, last_line, lines)` per heading section, each ending at the next heading."""
    lines = _path_text(path).splitlines()
    heads = [i for i, ln in enumerate(lines) if ln.startswith("#")]
    out = []
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.append((start + 1, end, lines[start:end]))
    return out


def _prose(body: list[str]) -> str:
    """The section's prose: fenced bodies dropped, inline spans replaced, lower-cased."""
    kept: list[str] = []
    fence: str | None = None
    for line in body:
        opened = _FENCE.match(line)
        if fence is not None:
            if opened and line.strip().startswith(fence):
                fence = None
            continue
        if opened:
            fence = opened.group(1)
            continue
        kept.append(re.sub(r"`+[^`]*`+", " ", line))
    return "\n".join(kept).lower()


def _spans_by_line(path: Path) -> dict[int, set[str]]:
    skill_spans = pytest.importorskip("skill_spans")
    out: dict[int, set[str]] = {}
    for lineno, span in skill_spans.spans(_path_text(path)):
        out.setdefault(lineno, set()).add(span)
    return out


def test_tp_escalate_cites_escalation_md():
    """The seat skill cites the protocol as a code span (not a paraphrase of it)."""
    path = _skill("tp-escalate")
    assert path.is_file(), "skills/tp-escalate/SKILL.md is missing"
    cited = {s for spans in _spans_by_line(path).values() for s in spans}
    assert ESCALATION_SPAN in cited, "the seat skill never cites the protocol in a span"


def test_card_phrase_sections_cite_escalation():
    """Every heading section of the four run skills whose prose mentions a card cites
    `skills/_shared/escalation.md` in a code span, so one protocol owns every card."""
    flagged: list[str] = []
    for name in RUN_SKILLS:
        path = _skill(name)
        assert path.is_file(), f"{name} has no SKILL.md"
        spans = _spans_by_line(path)
        for first, last, body in _heading_sections(path):
            if not any(phrase in _prose(body) for phrase in CARD_PHRASES):
                continue
            in_section: set[str] = set()
            for lineno in range(first, last + 1):
                in_section |= spans.get(lineno, set())
            if ESCALATION_SPAN not in in_section:
                flagged.append(f"{name}: line {first} {body[0].strip()!r}")
    assert flagged == [], "card-phrase sections without an escalation.md span: " + "; ".join(flagged)

# --- Task 7.1: the run skill's §Cleanup pointer to the protocol ----------------------


def test_run_full_design_cites_escalation_md():
    """`tp-run-full-design` cites the protocol in a code span (detailed design §Net-zero:
    the §Cleanup step 0 pointer). Structural only - no byte literal here; the size pins
    live in the run skill's own doc tests."""
    path = _skill("tp-run-full-design")
    assert path.is_file(), "skills/tp-run-full-design/SKILL.md is missing"
    cited = {s for spans in _spans_by_line(path).values() for s in spans}
    assert ESCALATION_SPAN in cited, (
        "run-full-design never cites the protocol in a code span"
    )

# --- Task 7.2: the pr-iterate / merge-from-main pointers and the flush's ruling files --

TOPOLOGY_MD = REPO_ROOT / "skills" / "tp-pr-iterate" / "round-topology.md"
RULINGS_SPAN = "three-pillars-docs/escalations/rulings/"


def _lines(path: Path) -> list[str]:
    return _path_text(path).splitlines()


def _span_lines(path: Path, span: str) -> list[int]:
    """1-based line numbers of *path* whose code spans include *span*."""
    return [n for n, spans in _spans_by_line(path).items() if span in spans]


def _step_lines(path: Path, step: str) -> tuple[int, int]:
    """`(first, last)` 0-based line range of the numbered step starting `N. **`."""
    lines = _lines(path)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{step}. **")), None)
    assert start is not None, f"{path.name} has no step {step}"
    end = next((i for i, ln in enumerate(lines[start + 1:], start + 1)
                if re.match(r"^\d+\.\s", ln)), len(lines))
    return start, end


def _bullet_bounds(lines: list[str], start: int) -> tuple[int, int]:
    """`(first, last)` 0-based bounds of the markdown bullet holding *start*."""
    first = next(i for i in range(start, -1, -1) if lines[i].lstrip().startswith(("- ", "* ")))
    end = next((i for i in range(first + 1, len(lines))
                if lines[i].lstrip().startswith(("- ", "* ")) or lines[i].startswith("#")), len(lines))
    return first, end - 1


def _spans_in(path: Path, first: int, last: int) -> set[str]:
    """Every code span on the 0-based inclusive line range *first*..*last*."""
    spans = _spans_by_line(path)
    out: set[str] = set()
    for lineno in range(first + 1, last + 2):
        out |= spans.get(lineno, set())
    return out


def test_pr_iterate_cites_escalation_md():
    """The Step 6 line that runs the finalizer (its `finalizer-first.md` span) also cites the
    protocol in a span, so an operator question raised in the loop has one owner."""
    path = _skill("tp-pr-iterate")
    assert path.is_file(), "skills/tp-pr-iterate/SKILL.md is missing"
    lines = _lines(path)
    step6 = [n for n in _span_lines(path, "finalizer-first.md")
             if "finalizer_cli prepare" in lines[n - 1]]
    assert step6, "no Step 6 line runs `finalizer_cli prepare` with a `finalizer-first.md` span"
    cited = {s for n in step6 for s in _spans_by_line(path).get(n, set())}
    assert ESCALATION_SPAN in cited, (
        f"the Step 6 finalizer line(s) {step6} never cite the protocol in a code span"
    )


def test_merge_from_main_cites_escalation_md():
    """Step 4 (what the human must finish) cites the protocol in a span: each deferred
    living-doc file is one card under the shared protocol, never a locally invented question."""
    path = _skill("tp-merge-from-main")
    assert path.is_file(), "skills/tp-merge-from-main/SKILL.md is missing"
    first, last = _step_lines(path, "4")
    assert "Surface what the human must finish" in _lines(path)[first], "step 4 is not the deferral"
    assert ESCALATION_SPAN in _spans_in(path, first, last), (
        f"step 4 (lines {first + 1}-{last}) never cites the protocol in a span"
    )


def test_flush_names_ruling_files():
    """The `## Log flush` two-stable staging bullet names the run's ruling files, so the flush
    commit stages them (escalation.md §Commit points b)."""
    assert TOPOLOGY_MD.is_file(), "skills/tp-pr-iterate/round-topology.md is missing"
    lines = _lines(TOPOLOGY_MD)
    at = next((i for i, ln in enumerate(lines) if "committed and pushed only at" in ln), None)
    assert at is not None, "round-topology.md has no two-stable staging bullet"
    first, last = _bullet_bounds(lines, at)
    assert "## Log flush" in "\n".join(lines[:at]), "the staging bullet is not under `## Log flush`"
    spans = _spans_in(TOPOLOGY_MD, first, last)
    assert RULINGS_SPAN in spans, "the two-stable staging bullet names no ruling-files path"
    assert "escalation.md" in spans, "the bullet cites no escalation.md span"
    assert "Commit points" in " ".join(lines[first:last + 1]), "the bullet cites no §Commit points"


def test_fleet_cites_tp_escalate():
    """Fleet step 5 (Monitor) routes trouble and finalizer stops through `/tp-escalate`."""
    if not (path := _skill("-".join(["tp", "fleet"]))).is_file():
        pytest.skip("pro-only skill absent in this build")
    first, last = _step_lines(path, "5")
    assert any(s.startswith("/tp-escalate") for s in _spans_in(path, first, last)), "step 5 cites no /tp-escalate span"
def test_finalizer_first_has_question_row_and_pointer():
    path = _SHARED / "finalizer-first.md"
    lines, text = _lines(path), "\n".join(_lines(path))
    assert any(ln.startswith("| `question` |") for ln in lines), "no question row"
    assert any(ln.startswith("| `halt` |") and "unanswerable" not in ln for ln in lines), "halt"
    assert RULINGS_SPAN in text and "--scope" in text and _span_lines(path, ESCALATION_SPAN)

def test_explainer_points_at_escalation():
    path = _SHARED / "explainer.md"
    assert "not wired yet" not in "\n".join(_lines(path)), "explainer.md defers the wiring"
    assert _span_lines(path, ESCALATION_SPAN), "explainer.md has no protocol span"
