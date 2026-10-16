"""test_cheap_tier_review_sites.py — the guard reads the argument-hint from the
owning skill's SKILL.md when the stub sits in a non-SKILL .md (Phase 1, Task 1.3).

design: cheap-tier-review-prep (Task 1.3).

A review-prep stub may sit in a skill's cheap-tier.md rather than its SKILL.md
(Phase 6 lands the first one). The guard's argument-hint check must then read the
flag from the owning SKILL.md, not the stub's own file. Imports the guard and its
tmp-tree helpers from test_cheap_tier_sites.py; that file holds the guard itself.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import test_cheap_tier_sites as sites  # noqa: E402
from test_cheap_tier_sites import GOOD, HINT, ROOT, _put, _tree, find_violations  # noqa: E402
import skill_text  # noqa: E402

STUB_FILE = "skills/x/cheap-tier.md"
STUB = GOOD.replace("handoff", "review_refs")
MISSING = "---\nname: x\n---\n"


def _review_tree(tmp_path: Path) -> Path:
    root = _tree(tmp_path)
    _put(root, STUB_FILE, STUB)
    return root


def test_non_skill_stub_reads_own_skill_hint(tmp_path, monkeypatch):
    monkeypatch.setitem(sites.SLOT_SITES, "review_refs", (STUB_FILE,))
    root = _review_tree(tmp_path)
    # Clean when the owning SKILL.md carries the flag.
    _put(root, "skills/x/SKILL.md", HINT)
    assert find_violations(root) == []
    # Reports the missing flag (on the stub file) when the SKILL.md lacks it.
    _put(root, "skills/x/SKILL.md", MISSING)
    assert f"{STUB_FILE}: argument-hint lacks --cheap-tier" in find_violations(root)


def test_skill_md_stub_still_reads_own_hint(tmp_path):
    root = _tree(tmp_path)  # handoff stub sits in skills/tp-session-save/SKILL.md
    assert find_violations(root) == []
    _put(root, "skills/tp-session-save/SKILL.md", MISSING + GOOD)
    assert ("skills/tp-session-save/SKILL.md: argument-hint lacks --cheap-tier"
            in find_violations(root))


def test_live_tree_is_clean():
    assert find_violations(ROOT) == []


# --- Phase 6, Task 6.5: the protocol body lands in tp-pr-iterate/cheap-tier.md ----

PROTOCOL = "skills/tp-pr-iterate/cheap-tier.md"
PREP_SLOTS = ("review_refs", "review_slice", "ci_log_triage", "repro_scaffold")
TAIL_LINE = ("Labelled cheap-tier reproducer scaffolds (drafted cheap, red on head by an "
             "assertion; adopt one only after your own check): R/prep/scaffolds/index.json")


def _sections(path: str) -> dict[str, str]:
    """`## ` heading -> the section's joined body (a small helper for the tail test)."""
    text = (ROOT / path).read_text(encoding="utf-8")
    out: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name is not None:
            out[name].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def test_prep_stubs_once_in_protocol():
    for slot in PREP_SLOTS:
        files = [f for f, s, _ in sites.stubs(ROOT) if s == slot]
        assert files == [PROTOCOL], f"{slot}: {files}"
    cj = [f for f, s, _ in sites.stubs(ROOT) if s == "classifier_judge"]
    assert cj.count(PROTOCOL) == 1, cj
    hint = sites.argument_hint(ROOT / "skills/tp-pr-iterate/SKILL.md")
    assert "[--cheap-tier[=ab]]" in hint
    assert find_violations(ROOT) == []


def test_tail_lines_verbatim():
    sections = _sections(PROTOCOL)
    tail = sections["Tail lines"]
    assert "CHEAP_TIER: <mode>" in tail
    assert TAIL_LINE in tail
    assert "repro_scaffold" in tail and "pr_fix_reproducer" in tail
    for name in ("Pre-round", "Scaffold"):
        assert "immediately before" in sections[name]
        assert "only after every unit of the batch has settled" in sections[name]
    assert "R/prep/work/meta.json" in sections["Scaffold"]


def test_no_gate_names_in_protocol():
    bodies = [b for f, s, b in sites.stubs(ROOT) if f == PROTOCOL]
    assert bodies, "no stubs found in " + PROTOCOL
    for body in bodies:
        assert "post_codereview_comment" not in body
        assert "digest_post" not in body


# --- Phase 6, Task 6.6: the tp-pr-iterate SKILL.md flag + stub and the pointers ------

SKILL = "skills/tp-pr-iterate/SKILL.md"
TOPOLOGY = "skills/tp-pr-iterate/round-topology.md"


def _section(path: str, name: str) -> str:
    """The text between `## <name>` and the next `## ` heading (pointer-check helper)."""
    full = skill_text.read_skill_text("tp-run-full-design") if path == RUN_FULL else (ROOT / path).read_text(encoding="utf-8")
    lines = full.splitlines()
    out, keep = [], False
    for line in lines:
        if line.startswith("## "):
            keep = line[3:].strip() == name
            continue
        if keep:
            out.append(line)
    return "\n".join(out)


def test_skill_md_flag_and_classifier_stub():
    assert "[--cheap-tier[=ab]]" in sites.argument_hint(ROOT / SKILL)
    cj = [(s, b) for f, s, b in sites.stubs(ROOT) if f == SKILL]
    assert [slot for slot, _ in cj] == ["classifier_judge"], cj
    for _, body in cj:
        assert len([ln for ln in body.splitlines() if ln.strip()]) <= 3, body
    text = (ROOT / SKILL).read_text(encoding="utf-8")
    assert text.index("<!-- cheap-tier:classifier_judge -->") < text.index(
        'model=model_policy.model_for("classifier", config),')
    assert len(text.splitlines()) < 490
    assert find_violations(ROOT) == []


def test_pointers_cite_protocol():
    text = (ROOT / SKILL).read_text(encoding="utf-8").splitlines()
    i = next(idx for idx, ln in enumerate(text)
             if "`cheap-tier.md` §Pre-round runs before sub-step 1" in ln)
    for token in ("cheap-tier.md", "§Pre-round", "§Scaffold", "§Tail lines"):
        assert token in text[i] + text[i + 1], token
    one_round = _section(TOPOLOGY, "One round")
    line = next(ln for ln in one_round.splitlines() if "cheap-tier.md" in ln)
    for token in ("cheap-tier.md", "§Pre-round", "§Scaffold", "§Tail lines"):
        assert token in line, token
    contract = _section(TOPOLOGY, "Inline-fix contract")
    assert "[cheap-tier] pr_fix_reproducer: round tail cannot spawn; today's generation" in contract
    assert "CHEAP_TIER:" in contract


# --- Phase 7, Task 7.6: the A/B section and the cheap-dispatch pointer ----------------

DISPATCH = "skills/_shared/cheap-dispatch.md"


def test_ab_section():
    ab = " ".join(_sections(PROTOCOL)["A/B"].split())
    for needle in ("`prepare`", "without `--prep-dir`", "review_prep_cli.py shadow",
                   "one parallel batch", "review_prep_cli.py ab-record", "`rp-draft:",
                   "[cheap-tier] ab budget exhausted: review prep ships opt-in",
                   "`ab_arm: base`", "--rung opus", "ab-unparseable: <angle>"):
        assert needle in ab, needle
    assert "never listed to the tail" in ab
    mode = " ".join(_sections(DISPATCH)["`ab` mode"].split())
    assert "skills/tp-pr-iterate/cheap-tier.md" in mode and "§A/B" in mode


# --- Phase 7, Task 7.7: the Tier 7 forward and §Reach narrowing -----------------------
# (the L152 known-issue check is dev-only: test_cheap_tier_review_l152.py)

RUN_FULL = "skills/tp-run-full-design/SKILL.md"
RUN_CHEAP = "skills/tp-run-full-design/cheap-tier.md"
NEW_REACH = ("the forward reaches the loop's fixes only as the round tail's `CHEAP_TIER:` line, "
             "a log line")
NEW_INERT = "its `pr_fix_reproducer` stub is inert in-loop and standalone"


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_tier7_line_and_reach():
    tier7 = _section(RUN_FULL, "Tier 7 — PR-iterate (review loop to reviewed-stable)")
    assert any("skills/tp-pr-iterate/cheap-tier.md" in ln and "mode" in ln
               and "--cheap-tier" not in ln for ln in tier7.splitlines())
    cheap = (ROOT / RUN_CHEAP).read_text(encoding="utf-8")
    assert "tp-pr-iterate/cheap-tier.md" in _section(RUN_CHEAP, "Tier 7 — the loop forward")
    assert "cheap_tier_cli.py spec" not in cheap
    reach = _flat(_section(RUN_CHEAP, "Reach"))
    assert "is not wired" not in reach
    assert NEW_REACH in reach and NEW_INERT in reach
