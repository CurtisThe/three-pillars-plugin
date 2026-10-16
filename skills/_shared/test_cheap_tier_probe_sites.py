"""test_cheap_tier_probe_sites.py: the three routed stubs' `spec` lines carry `--probe`.

design: cheap-tier-local-routing (Task 6.3; detailed-design.md §Data Flow 1, §Notes 2 and 6).
Only the routed prose-drafter sites (`docs_draft`, `history_line`, `handoff`) run `spec --probe`
(cheap-dispatch.md §Routing). The test pins:

- each routed stub's `spec` command literal: `--probe` appended after `--cheap-tier <mode>`
  (so the `spec --slot {slot} --root . --cheap-tier <mode>` prefix stays whole), run in Bash
  with timeout 300000; `--design {design-name}` after `--probe` in tp-design-learn and
  tp-session-save, none in tp-docs-update (it takes no design argument);
- exactly those stubs carry `--probe` (no other skill file does, bar the protocol doc);
- every unrouted stub's `spec` command is byte-identical to its literal pinned here;
- each routed stub's `Record the attempt per the dispatch doc` sentence is unchanged and no
  stub spells a `dispatch_log.py record` line or its flags (they live in cheap-dispatch.md
  step 4 only); no stub names a model.

Imports `test_cheap_tier_sites.py`'s helpers; that file holds the guard itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_cheap_tier_exclusions import CHEAP_MODEL_RE  # noqa: E402
from test_cheap_tier_sites import ROOT, stubs  # noqa: E402

CLI = 'python3 "$TP_ROOT"/skills/_shared/cheap_tier_cli.py spec'
SPEC_RE = re.compile(r"`(python3 \"\$TP_ROOT\"/skills/_shared/cheap_tier_cli\.py spec [^`]*)`")
PROBE_SKIP = {"skills/_shared/cheap-dispatch.md"}
RECORD_SENTENCE = ("Record the attempt per the dispatch doc; under `ab`, run its pure-slot "
                   "pair and use neither arm.")
RECORD_FLAGS = ("dispatch_log.py", "--local-requests", "--fallback-requests", "--wall-s",
                "--measure", "--escalated")
BASH_TIMEOUT = "in Bash with timeout 300000"

DOCS, LEARN, SAVE = ("skills/tp-docs-update/SKILL.md", "skills/tp-design-learn/SKILL.md",
                     "skills/tp-session-save/SKILL.md")


def _routed(slot: str, design: bool) -> str:
    tail = " --design {design-name}" if design else ""
    return f"{CLI} --slot {slot} --root . --cheap-tier <mode> --probe{tail}"


ROUTED = {
    (DOCS, "docs_draft"): _routed("docs_draft", False),
    (DOCS, "history_line"): _routed("history_line", False),
    (LEARN, "docs_draft"): _routed("docs_draft", True),
    (LEARN, "history_line"): _routed("history_line", True),
    (SAVE, "handoff"): _routed("handoff", True),
}

# Every other stub's `spec` command, byte for byte as it stood before Task 6.3.
UNROUTED = {
    ("skills/tp-pr-iterate/cheap-tier.md", "classifier_judge"):
        f"{CLI} --slot classifier_judge --root . --cheap-tier <mode>",
    ("skills/tp-pr-fix/SKILL.md", "classifier_judge"):
        f"{CLI} --slot classifier_judge --root . --cheap-tier <mode>",
    ("skills/tp-pr-fix/SKILL.md", "pr_fix_reproducer"):
        f"{CLI} --slot pr_fix_reproducer --root . --cheap-tier <mode>",
    ("skills/tp-merge-from-main/SKILL.md", "base_sync_splice"):
        f"{CLI} --slot base_sync_splice --root . --cheap-tier <mode>",
    ("skills/tp-post-merge/SKILL.md", "runbook"):
        f"{CLI} --slot runbook --root <resolved seat> --cheap-tier <mode>",
    ("skills/tp-pr-iterate/cheap-tier.md", "review_refs"):
        f"{CLI} --slot review_refs --root . --cheap-tier <mode>",
    ("skills/tp-pr-iterate/cheap-tier.md", "review_slice"):
        f"{CLI} --slot review_slice --root . --cheap-tier <mode>",
    ("skills/tp-pr-iterate/cheap-tier.md", "ci_log_triage"):
        f"{CLI} --slot ci_log_triage --root . --cheap-tier <mode>",
    ("skills/tp-pr-iterate/cheap-tier.md", "repro_scaffold"):
        f"{CLI} --slot repro_scaffold --root . --cheap-tier <mode>",
}


def _bodies() -> dict[tuple[str, str], str]:
    return {(file, slot): " ".join(body.split()) for file, slot, body in stubs(ROOT)}


def _spec_spans(body: str) -> list[str]:
    return SPEC_RE.findall(body)


def test_each_routed_stub_has_one_probe_spec_line():
    bodies = _bodies()
    for key, literal in ROUTED.items():
        assert key in bodies, f"{key}: stub missing"
        assert _spec_spans(bodies[key]) == [literal], key


def test_each_routed_spec_line_runs_in_bash_with_the_long_timeout():
    bodies = _bodies()
    for key, literal in ROUTED.items():
        assert f"`{literal}` {BASH_TIMEOUT}" in bodies[key], key


def test_the_spec_prefix_stays_whole():
    # test_cheap_tier_prose_sites.py asserts this literal for each routed stub
    bodies = _bodies()
    for (file, slot), literal in ROUTED.items():
        prefix = f"cheap_tier_cli.py spec --slot {slot} --root . --cheap-tier <mode>"
        assert prefix in bodies[(file, slot)], (file, slot)
        assert literal.index("--probe") > literal.index("--cheap-tier <mode>")


def test_design_follows_probe_only_where_the_skill_takes_a_design():
    for (file, slot), literal in ROUTED.items():
        if file == DOCS:
            assert "--design" not in literal, (file, slot)
        else:
            assert literal.endswith("--probe --design {design-name}"), (file, slot)


def test_exactly_the_routed_stubs_carry_probe():
    got = {key for key, body in _bodies().items()
           if any("--probe" in span for span in _spec_spans(body))}
    assert got == set(ROUTED)


def test_no_other_skill_doc_has_a_probe_spec_line():
    hits = set()
    for path in sorted((ROOT / "skills").rglob("*.md")):
        file = path.relative_to(ROOT).as_posix()
        if file in PROBE_SKIP:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "cheap_tier_cli.py spec" in line and "--probe" in line:
                hits.add(file)
    assert hits == {DOCS, LEARN, SAVE}


def test_unrouted_spec_lines_are_byte_identical():
    bodies = _bodies()
    for key, literal in UNROUTED.items():
        assert key in bodies, f"{key}: stub missing"
        assert _spec_spans(bodies[key]) == [literal], key


def test_the_record_sentence_is_unchanged_and_no_stub_spells_record_flags():
    bodies = _bodies()
    for key in ROUTED:
        assert RECORD_SENTENCE in bodies[key], key
    for key, body in bodies.items():
        spelled = [flag for flag in RECORD_FLAGS if flag in body]
        assert spelled == [], (key, spelled)


def test_no_stub_names_a_model():
    for key, body in _bodies().items():
        assert CHEAP_MODEL_RE.search(body) is None, key
        assert set(re.findall(r"model=\S+?(?=[,)\s])", body)) <= {"model=<spec.model>"}, key
