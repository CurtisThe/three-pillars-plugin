"""test_cheap_tier_prose_sites.py — the cheap-if-wrong prose sites (plan Phase 7).

design: cheap-tier-offload (Tasks 7.3, 7.4; slots doc §Phase 7, §Site wiring).

- `handoff`: `tp-session-save` drafts the handoff between steps 3 and 4, from a facts
  payload, and never under `--stage-boundary`.
- `history_line` / `docs_draft`: `tp-design-learn` (step 7) and `tp-docs-update` (step 6)
  draft the diff-style proposal the operator approves as today, never for `vision.md`.
- Every stub feeds the drafter a facts payload only, stores the draft through
  `prose_oracle.py save-draft` with `--reviewed <operator approved>`, and falls back to
  today's prose on a drop. `tp-design-learn --auto` is `--reviewed false`.
- Tier 5 forwards the run's flag to `/tp-design-learn`; the orchestrator holds no stub.

Imports `test_cheap_tier_sites.py`'s helpers; that file holds the guard itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_cheap_tier_sites import ROOT, STUB_RE, argument_hint, find_violations  # noqa: E402
import skill_text  # noqa: E402

SKILLS = ROOT / "skills"
SAVE = SKILLS / "tp-session-save" / "SKILL.md"
LEARN = SKILLS / "tp-design-learn" / "SKILL.md"
DOCS = SKILLS / "tp-docs-update" / "SKILL.md"
RUN = SKILLS / "tp-run-full-design" / "SKILL.md"
SITES = ((SAVE, "handoff"), (LEARN, "history_line"), (LEARN, "docs_draft"),
         (DOCS, "history_line"), (DOCS, "docs_draft"))
DOC_SITES = SITES[1:]
HINT = "[--cheap-tier[=ab]]"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _stub(path: Path, slot: str):
    found = [m for m in STUB_RE.finditer(_text(path)) if m.group(1) == slot]
    assert len(found) == 1, f"{path.parent.name}: expected one cheap-tier:{slot} stub"
    return found[0]


def _body(path: Path, slot: str) -> str:
    return _flat(_stub(path, slot).group(2))


def test_live_tree_is_clean():
    assert find_violations(ROOT) == []


def test_each_site_has_its_stub_and_hint():
    for path, slot in SITES:
        body = _body(path, slot)
        assert f"cheap_tier_cli.py spec --slot {slot} --root . --cheap-tier <mode>" in body
        assert f"cheap_oracle_run.py check --slot {slot}" in body and "`prose_shape`" in body
        assert f"ctx `kind` `{slot}`" in body, (path.parent.name, slot)
        assert HINT in argument_hint(path), path.parent.name
    assert "--stage-boundary" in argument_hint(SAVE)
    assert "--auto" in argument_hint(LEARN)


def test_each_stub_feeds_facts_only():
    for path, slot in SITES:
        body = _body(path, slot)
        assert "facts payload JSON" in body and "never the session context" in body, slot
        assert "Agent(subagent_type=<spec.agent_ref>, model=<spec.model>, …)" in body
        assert "one scratch file" in body


def test_each_stub_marks_review():
    for path, slot in SITES:
        body = _body(path, slot)
        assert '"$TP_ROOT"/skills/_shared/prose_oracle.py save-draft' in body
        assert f"--slot {slot} --draft <draft>" in body
        assert "--reviewed <operator approved>" in body, (path.parent.name, slot)
    for slot in ("history_line", "docs_draft"):
        assert "`--auto` means `--reviewed false`" in _body(LEARN, slot)


def test_each_final_is_a_file():
    # save-draft reads --final as a path (prose_oracle.main): a text placeholder would
    # fail the read, exit 0, and never record the edit metric (impl-audit #6)
    for path, slot in SITES:
        body = _body(path, slot)
        final = body[body.index("--final <") + len("--final <"):].split(">", 1)[0]
        want = "handoff.md" if slot == "handoff" else "a file holding the final text"
        assert final == want, (path.parent.name, slot, final)


def test_a_dropped_draft_means_today():
    for path, slot in SITES:
        body = _body(path, slot).lower()
        assert "a dropped draft means" in body and "as today" in body, (path.parent.name, slot)
        assert "record the attempt per the dispatch doc" in body
        assert "under `ab`, run its pure-slot pair and use neither arm" in body


def test_vision_is_never_drafted():
    for path, slot in DOC_SITES:
        assert "never for `vision.md`" in _body(path, slot), (path.parent.name, slot)
    learn = _text(LEARN)
    assert "**Never auto-edits `vision.md`.**" in learn
    assert "Do NOT stage `three-pillars-docs/vision.md`" in learn
    assert "never `vision.md`" in learn.split("## Auto Mode", 1)[1]


def test_handoff_stub_sits_between_steps_3_and_4():
    text = _text(SAVE)
    stub = _stub(SAVE, "handoff")
    assert text.index("3. **Review this conversation**") < stub.start()
    assert stub.end() < text.index("4. **Overwrite")
    assert "never with `--stage-boundary`" in _flat(stub.group(2))


def test_doc_stubs_sit_in_the_proposal_step():
    learn, docs = _text(LEARN), _text(DOCS)
    for slot in ("history_line", "docs_draft"):
        s = _stub(LEARN, slot)
        assert learn.index("7. **Propose updates**") < s.start() < learn.index("8. **Learn-")
        s = _stub(DOCS, slot)
        assert docs.index("6. **Propose specific edits**") < s.start()
        assert s.end() < docs.index("7. **On user confirmation**")


# --- Task 7.4: the Tier 5 forward -------------------------------------------------------

CHEAP_MD = SKILLS / "tp-run-full-design" / "cheap-tier.md"
FORWARD = "`/tp-design-learn {slug} --auto --cheap-tier`"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:end if end != -1 else len(text)]


def test_learn_forward():
    run = skill_text.read_skill_text("tp-run-full-design")
    assert "<!-- cheap-tier:" not in run  # the decisions_entry stub is dropped (Deviations 3)
    slot9 = next(ln for ln in run.splitlines()
                 if ln.startswith("Runs `/tp-design-learn {slug} --auto --cheap-tier`"))
    assert FORWARD in slot9
    step3 = _flat(_section(run, "### Step 3 — `design-learn` slot"))
    assert "runs `/tp-design-learn {slug} --auto --cheap-tier` inline" in step3
    assert FORWARD in step3 and "[`cheap-tier.md`](cheap-tier.md) §Tier 5" in step3
    tier5 = _flat(_section(_text(CHEAP_MD), "\n## Tier 5 — the design-learn forward"))
    assert "always dispatch `/tp-design-learn {slug} --auto --cheap-tier`" in tier5
    assert "`--reviewed false`" in tier5 and "never edits `vision.md`" in tier5
    # impl-audit #9: the Slot 9 drafter spawn is a sanctioned depth-2 site, stated here
    # (SKILL.md has no char budget left for it)
    assert "**Depth 2.**" in tier5 and "`tp-generator` → `tp-drafter`" in tier5
    assert "spawns nothing" in tier5
    assert "## Tier 5" in _text(CHEAP_MD).split("\n\n", 2)[1]  # the header lists it


def test_scratch_names_the_cheap_draft_output_file():
    # a drafter that writes one scratch file writes it under the repo, never /tmp
    scratch = _text(SKILLS / "_shared" / "cheap-dispatch.md").split("- **Scratch.**", 1)[1]
    scratch = scratch.split("\n", 1)[0]
    assert ".tp-scratch/cheap-draft/<slot>-<n>.md" in scratch
    assert "never `/tmp`" in scratch
