"""Pins for `boundary-contracts.md` — the orchestrator's two boundary contracts.

design: audit-pass-does-not-bind (Task 6.4, P1). The pickup-contract schema and
the worker's `explicit_artifact_contract` moved out of the orchestrator
SKILL.md, verbatim, to free budget for the certification wiring. SKILL.md keeps
both headings, each with one pointer line; the bodies exist in one place only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
SKILL_MD = HERE / "SKILL.md"
CONTRACTS = HERE / "boundary-contracts.md"
WORKER = HERE.parent.parent / "agents" / "tp-worker.md"
for _dir in (Path(__file__).resolve().parent, HERE.parent / "_shared"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

import skill_text  # noqa: E402

# The never-grow pins of test_tier7_budget_docs.py; never raised.
from test_tier7_budget_docs import GRANDFATHERED_CHARS as PIN_CHARS  # noqa: E402
from test_tier7_budget_docs import GRANDFATHERED_LINES as PIN_LINES  # noqa: E402

# Each SKILL.md heading is found by its contract's name, whatever else it says.
PICKUP_HEADING = "Pickup contract v1"
WORKER_HEADING = "`explicit_artifact_contract`"
# What the pickup validation rules name: the schema fields they govern and the values
# they require (every rule cites at least one token no other rule does).
PICKUP_RULE_TOKENS = {"version", "slug", "branch", "dir", "task_metadata", "task_metadata.title",
                      "phase_hook", "writeup_hook", "escalate_hook", "[a-z0-9-]+", "tp/{slug}",
                      "three-pillars-docs/tp-designs/{slug}"}


def _text(path: Path) -> str:
    if path == SKILL_MD:
        return skill_text.read_skill_text("tp-run-full-design")
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str, level: str) -> str:
    start = text.index(heading)
    end = text.find(f"\n{level} ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


# Top-level CommonMark list items, whatever the marker: `-`/`*`/`+` bullets, `N.`/`N)` items.
BULLET = re.compile(r"^[-*+][ \t]+(\S.*)$", re.MULTILINE)
ORDERED = re.compile(r"^(\d+)[.)][ \t]+\S", re.MULTILINE)

# A CommonMark fence opener: three-or-more backticks or tildes, a `json` tag, no info-text
# after the tag. The closer is the same character, at least as long, tag-less.
FENCE_OPEN = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*json[ \t]*$")
INT_PLACEHOLDER = re.compile(r"<integer>|<int>")


def _fence_closer(run: str) -> re.Pattern:
    return re.compile(rf"^[ \t]*{run[0]}{{{len(run)},}}[ \t]*$")


def _bullet_keys(body: str) -> set[str]:
    """The backticked names the top-level bullets cite."""
    return {tok for item in BULLET.findall(body) for tok in re.findall(r"`([^`\s]+)`", item)}


def _ordered(body: str) -> list[str]:
    return ORDERED.findall(body)


def _json_examples(body: str) -> list[dict]:
    """Every fenced JSON example in `body`, parsed. The fence is matched CommonMark-style
    (three-or-more backticks or tildes, `json` tag, same character and at least as long a
    closer), so tilde fences, a space before the tag, four backticks, and an indented fence
    in a list item all read; an untagged fence is not an example. The `<int>`/`<integer>`
    placeholders are not JSON, so each reads as 0."""
    blocks, lines, closer = [], None, None
    for line in body.splitlines():
        if lines is None:
            m = FENCE_OPEN.match(line)
            if m:
                lines, closer = [], _fence_closer(m.group(2))
        elif closer.match(line):
            text = "\n".join(lines)
            blocks.append(json.loads(INT_PLACEHOLDER.sub("0", text)))
            lines, closer = None, None
        else:
            lines.append(line)
    return blocks


def _assert_pickup_example(body: str) -> None:
    """The pickup schema example: version 1 and the keys the validation rules require."""
    [example] = _json_examples(body)
    assert example["version"] == 1 and type(example["version"]) is int, example
    assert {"slug", "branch", "dir", "task_metadata"} <= example.keys(), example
    assert "title" in example["task_metadata"], example


def _assert_worker_example(body: str) -> None:
    """The worker's return envelope example names the candidate v1 schema."""
    [example] = _json_examples(body)
    assert example["schema"] == "tp-run-full-design/candidate/v1", example


def _pointer(name: str) -> str:
    """The body of the one SKILL.md heading naming `name`: exactly one non-blank line."""
    text = _text(SKILL_MD)
    heads = list(re.finditer(rf"^#{{1,6}} [^\n]*{re.escape(name)}[^\n]*$", text, re.MULTILINE))
    assert len(heads) == 1, f"{name}: expected one heading, got {len(heads)}"
    start = heads[0].end()
    nxt = re.search(r"\n#{1,6} ", text[start:])
    body = text[start:start + nxt.start()] if nxt else text[start:]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1, f"{name}: expected one pointer line, got {len(lines)}"
    assert "boundary-contracts.md" in lines[0]
    return lines[0]


def test_pickup_contract_body_moved():
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    _assert_pickup_example(body)
    for needle in ("unknown-pickup-version", "missing-required-field",
                   "invalid-slug", "branch-slug-mismatch", "task_metadata.title", "hook-omitted"):
        assert needle in body, needle
    assert PICKUP_RULE_TOKENS <= _bullet_keys(body), PICKUP_RULE_TOKENS - _bullet_keys(body)


def test_worker_contract_body_moved():
    body = _section(_text(CONTRACTS), "## explicit_artifact_contract", "##")
    # TRIPWIRE: "Six items, in order" is the stated contract (SKILL.md's heading and pointer
    # say six too); a seventh responsibility is a deliberate edit of all three.
    assert _ordered(body) == [str(n) for n in range(1, 7)], "six worker responsibilities"
    _assert_worker_example(body)
    assert "three-pillars-docs/tp-designs/{slug}/candidates/" in body


def test_skill_md_keeps_headings_with_one_pointer_each():
    _pointer(PICKUP_HEADING)
    assert "`worker_prompt`" in _pointer(WORKER_HEADING), "Tier 3 appends the list to worker_prompt"


def test_bodies_moved_not_duplicated():
    skill = _text(SKILL_MD)
    for literal in ("unknown-pickup-version", "hook-omitted", "tp-run-full-design/candidate/v1"):
        assert literal not in skill, literal


def test_worker_agent_cites_boundary_contracts():
    assert "tp-run-full-design/boundary-contracts.md" in _text(WORKER)


def test_contracts_doc_within_soft_cap():
    # file_size_guard is dev-only (release-tiers.json), so a plugin build skips this pin.
    caps = pytest.importorskip("file_size_guard").LINE_CAPS
    assert len(_text(CONTRACTS).splitlines()) <= caps["markdown"][0]


# P1 certification-wiring budget not yet spent: none. 7.1 spent 10 / 1,460 of 18 / 2,000,
# 7.2 spent 3 / 845 of 12 / 1,400 and 9.5 spent 1 / 191 of 4 / 500.
UNSPENT_LINES, UNSPENT_CHARS = 0, 0


def test_skill_md_headroom():
    """P1: the headroom under the never-grow pins still covers the unspent wiring budget."""
    text = _text(SKILL_MD)
    assert len(text.splitlines()) + UNSPENT_LINES <= PIN_LINES, "SKILL.md over its line pin"
    assert len(text) + UNSPENT_CHARS <= PIN_CHARS, "SKILL.md over its char pin"


def test_list_counts_do_not_depend_on_the_list_marker():
    """PR #162 l2r2: `*`/`+` bullets and `N)` items render the same list as `-` and `N.`."""
    pickup = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    worker = _section(_text(CONTRACTS), "## explicit_artifact_contract", "##")
    for marker in ("*", "+"):
        respelled = re.sub(r"^- ", f"{marker} ", pickup, flags=re.MULTILINE)
        assert respelled != pickup and _bullet_keys(respelled) == _bullet_keys(pickup), marker
    respelled = re.sub(r"^(\d+)\. ", r"\1) ", worker, flags=re.MULTILINE)
    assert respelled != worker and _ordered(respelled) == _ordered(worker)


def _respelled(body: str, render) -> str:
    """`body` with its one JSON example re-rendered as `render(parsed example)`."""
    [example] = _json_examples(body)
    start = body.index("```json") + len("```json")
    end = body.index("```", start)
    return body[:start] + "\n" + render(example) + "\n" + body[end:]


@pytest.mark.parametrize("heading, check", [("## Pickup contract v1", _assert_pickup_example),
                                            ("## explicit_artifact_contract", _assert_worker_example)])
def test_json_examples_are_read_as_json_not_spelling(heading, check):
    """PR #162 r1: compact and pretty JSON both pass; a wrong value fails."""
    body = _section(_text(CONTRACTS), heading, "##")
    for render in (lambda ex: json.dumps(ex, separators=(",", ":")), lambda ex: json.dumps(ex, indent=4)):
        respelled = _respelled(body, render)
        assert respelled != body
        check(respelled)
    key = "version" if "version" in _json_examples(body)[0] else "schema"
    for wrong in (2, "1", True, "tp-run-full-design/candidate/v2"):
        with pytest.raises(AssertionError):
            check(_respelled(body, lambda ex: json.dumps({**ex, key: wrong})))


def _respell_fence(body: str, opener: str, closer: str) -> str:
    """The example's fence in `body` respelled to `opener`/`closer`, body text unchanged.

    Locates the original closer (same character as the original opener, tag-less) so the
    swap works whether the respelling is within a fence character (tilde) or across one."""
    m = re.search(FENCE_OPEN.pattern, body, re.MULTILINE)
    assert m, "no json fence found"
    char, length = m.group(2)[0], len(m.group(2))
    closer_re = re.compile(rf"^[ \t]*{char}{{{length},}}[ \t]*$", re.MULTILINE)
    cm = closer_re.search(body, m.end())
    assert cm, "no closing fence found"
    return body[:m.start()] + opener + body[m.end():cm.start()] + closer + body[cm.end():]


def _example(body: str) -> dict:
    [example] = _json_examples(body)
    return example


def test_tilde_fence_is_read():
    """#162: a tilde fence is a CommonMark fence and the reader reads it."""
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    respelled = _respell_fence(body, "~~~json", "~~~")
    assert respelled != body
    _assert_pickup_example(respelled)


def test_space_before_json_tag_is_read():
    """#162: `json` separated from the fence by a space is still the info tag."""
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    respelled = body.replace("```json", "``` json", 1)
    assert respelled != body
    assert _example(respelled)["version"] == 1


def test_four_backtick_fence_is_read():
    """#162: a four-backtick fence reads, and the closer must match at four backticks."""
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    respelled = _respell_fence(body, "````json", "````")
    assert respelled != body
    assert _example(respelled)["version"] == 1


def test_integer_placeholder_reads_as_int():
    """#162: a `<integer>` placeholder stands in for the JSON value, like the `<int>` ones
    — each reads as the int 0, so the example parses instead of raising."""
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    respelled = body.replace('"version": 1', '"version": <integer>', 1)
    assert respelled != body
    example = _example(respelled)
    assert example["version"] == 0 and type(example["version"]) is int, example


def test_untagged_fence_is_not_a_json_example():
    """#162: only fenced JSON examples read; an untagged fence is prose, not a contract."""
    body = _section(_text(CONTRACTS), "## Pickup contract v1", "##")
    respelled = body.replace("```json", "```", 1)
    assert respelled != body
    assert _json_examples(respelled) == []
