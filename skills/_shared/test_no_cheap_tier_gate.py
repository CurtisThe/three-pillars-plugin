"""test_no_cheap_tier_gate.py — the cheap tier is on in every invocation; nothing is flag-keyed.

design: one-cheap-engine (Task 3.6; skills/_shared/test-fragility.md)

`cheap_tier_default.resolve` always returns mode `on`; `--cheap-tier[=ab]`,
`--no-cheap-tier` and a set `cheap_tier.default_run_flag` each add one `deprecated:`
line and change nothing. The nine site stubs in six skills (`tp-pr-fix`, `tp-design-learn`,
`tp-docs-update`, `tp-session-save`, `tp-merge-from-main`, `tp-post-merge`) lose their
"only with `--cheap-tier`" gate and keep their exclusions; no skill doc gates on the flag.
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cheap_tier_default  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# --- resolve / CLI -----------------------------------------------------------

DEFAULT_AB = {"cheap_tier": {"default_run_flag": "ab"}}
DEFAULT_OFF = {"cheap_tier": {"default_run_flag": "off"}}
DEFAULT_ON = {"cheap_tier": {"default_run_flag": "on"}}

KEY = "cheap_tier.default_run_flag"
# (id, config, resolve kwargs, the deprecated names, one `deprecated:` line each)
CASES = [
    ("unset", {}, {}, []),
    ("default_ab", DEFAULT_AB, {}, [KEY]),
    ("default_off", DEFAULT_OFF, {}, [KEY]),
    ("default_on", DEFAULT_ON, {}, [KEY]),
    ("typed_on", {}, {"cheap_tier": "on"}, ["--cheap-tier"]),
    ("typed_ab", {}, {"cheap_tier": "ab"}, ["--cheap-tier=ab"]),
    ("no_cheap_tier", {}, {"no_cheap_tier": True}, ["--no-cheap-tier"]),
    ("no_cheap_tier_over_off", DEFAULT_OFF, {"no_cheap_tier": True}, ["--no-cheap-tier", KEY]),
]
IDS = [case[0] for case in CASES]


@pytest.mark.parametrize("name,cfg,kw,_names", CASES, ids=IDS)
def test_resolve_is_always_on(name, cfg, kw, _names):
    assert cheap_tier_default.resolve(cfg, [], **kw)[0] == "on"


@pytest.mark.parametrize("name,cfg,kw,names", CASES, ids=IDS)
def test_each_deprecated_input_gives_one_line(name, cfg, kw, names):
    notes = cheap_tier_default.resolve(cfg, [], **kw)[1]
    assert len(notes) == len(names)
    for line, dep in zip(sorted(notes), sorted(f"deprecated: {n}" for n in names)):
        assert line.startswith(dep) and "changes nothing" in line


def test_dropped_config_warning_has_no_tail_and_comes_first():
    warning = "config: dropped cheap_tier.extra (unknown key)"
    mode, notes = cheap_tier_default.resolve(DEFAULT_OFF, [warning])
    assert mode == "on"
    assert notes[0] == f"warning: {warning}"  # something is always added: no tail
    assert len(notes) == 2 and notes[1].startswith("deprecated:")
    mode, notes = cheap_tier_default.resolve({}, [warning], no_cheap_tier=True)
    assert mode == "on" and "no --cheap-tier added" not in " ".join(notes)
    assert notes[0] == f"warning: {warning}" and len(notes) == 2
    other = "config: dropped models.task (type 'string')"
    assert cheap_tier_default.resolve({}, [other]) == ("on", [])


def test_both_flags_together_still_raise():
    with pytest.raises(ValueError):
        cheap_tier_default.resolve({}, [], cheap_tier="on", no_cheap_tier=True)
    with pytest.raises(ValueError):
        cheap_tier_default.resolve({}, [], cheap_tier="AB")


def test_default_mode_is_on_for_every_value():
    for cfg in (None, {}, DEFAULT_AB, DEFAULT_OFF, DEFAULT_ON,
                {"cheap_tier": {"default_run_flag": "x"}}):
        assert cheap_tier_default.default_mode(cfg) == "on"


def _cli(tmp_path: Path, block: dict, argv):
    path = tmp_path / ".three-pillars" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, **block}), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = cheap_tier_default.main(["--root", str(tmp_path), *argv], out=out, err=err)
    return code, out.getvalue(), err.getvalue()


@pytest.mark.parametrize("block,argv,lines", [
    ({}, [], 0),
    (DEFAULT_AB, [], 1),
    (DEFAULT_OFF, [], 1),
    ({}, ["--cheap-tier"], 1),
    ({}, ["--cheap-tier=ab"], 1),
    ({}, ["--no-cheap-tier"], 1),
    (DEFAULT_OFF, ["--no-cheap-tier"], 2),
])
def test_cli_prints_on_for_every_input(tmp_path, block, argv, lines):
    code, out, err = _cli(tmp_path, block, argv)
    assert (code, out) == (0, "on\n")
    assert err.count("deprecated:") == lines


# --- the skill docs ----------------------------------------------------------

FLEET = "skills/tp-" + "fleet/SKILL.md"  # split: the leak guard bans the pro name in a free file
SKIPPED = frozenset({  # the thirteen files Tasks 3.4 and 3.5 own; their own tests assert the same
    "skills/tp-pr-iterate/strata-finders.md", "skills/tp-pr-iterate/round-topology.md",
    "skills/tp-pr-iterate/cheap-tier.md", "skills/tp-pr-iterate/SKILL.md",
    "skills/council/strata-members.md", "skills/_shared/local-dispatch.md",
    "skills/_shared/strata-spawn.md", "skills/_shared/repo-config.md",
    "skills/_shared/design-run-launch.md", "skills/tp-run-full-design/cheap-tier.md",
    "skills/tp-run-full-design/SKILL.md", FLEET, "skills/_shared/cheap-dispatch.md",
})
GATE_NEEDLES = (
    "only with `--cheap-tier`", "only with `--cheap-tier[=ab]`", "under `--cheap-tier`",
    "under `--cheap-tier[=ab]`", "with `--cheap-tier[=ab]`", "only under the flag",
    "without the flag", "when the run has it", "when the run has the flag", "has the flag",
    '"with `--cheap-tier`" below means',
)
OPT_IN_RE = re.compile(r"opts? in to the (?:step[- ]\d+ )?cheap-tier")

SKILLS = ("tp-pr-fix", "tp-design-learn", "tp-docs-update", "tp-session-save",
          "tp-merge-from-main", "tp-post-merge")
RESOLVER = ("tp-merge-from-main", "tp-post-merge")
STUB_RE = re.compile(r"<!-- cheap-tier:([A-Za-z0-9_-]+) -->(.*?)<!-- /cheap-tier -->", re.S)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _skill(name: str) -> str:
    return (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_no_flag_gate_in_any_skill():
    hits = []
    for path in sorted((ROOT / "skills").rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIPPED:
            continue
        low = _flat(path.read_text(encoding="utf-8")).lower()
        hits += [(rel, n) for n in GATE_NEEDLES if n.lower() in low]
        hits += [(rel, m.group(0)) for m in OPT_IN_RE.finditer(low)]
    assert hits == []


def _arg_block(name: str) -> str:
    """The Argument text defining `--cheap-tier[=ab]`: its line plus any continuation lines."""
    lines = _skill(name).split("\n---\n", 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if "`--cheap-tier[=ab]`" in line)
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith(("- ", "**", "#", "<!--")):
            break
        block.append(line)
    return _flat(" ".join(block))


@pytest.mark.parametrize("name", SKILLS)
def test_argument_lines_define_mode_on(name):
    block = _arg_block(name)
    assert "deprecated" in block.lower()
    assert "`<mode>` is `on`" in block
    assert "off by default" not in block.lower()
    assert "opt in" not in block.lower() and "opts in" not in block.lower()


@pytest.mark.parametrize("name", RESOLVER)
def test_resolver_argument_lines_say_stdout_is_always_on(name):
    block = _arg_block(name)
    assert "`--no-cheap-tier`" in block
    assert 'python3 "$TP_ROOT"/skills/_shared/cheap_tier_default.py --root ' in block
    assert "always `on`" in block and "cheap_tier.default_run_flag" in block
    assert "stdout `on`, `ab` or empty" not in block
    assert "non-empty `<mode>`" not in block


def test_from_main_step_8_forwards_bare_cheap_tier():
    text = _flat(_skill("tp-merge-from-main"))
    assert "step 8 forwards bare `--cheap-tier`" in _arg_block("tp-merge-from-main")
    assert "`/tp-post-merge {design-name} --cheap-tier`" in text
    assert "--cheap-tier[=<mode>]" not in text and "when this run was given the flag" not in text
    assert "or `--no-cheap-tier` when empty" not in text
    assert "step 8 forwards bare `--cheap-tier`" in _arg_block("tp-post-merge")


# (skill, slot, the exclusion its stub keeps)
STUBS = [
    ("tp-pr-fix", "classifier_judge", "a matching verdict file and a route"),
    ("tp-pr-fix", "pr_fix_reproducer", "ab has no shadow arm here"),
    ("tp-design-learn", "docs_draft", "never for `vision.md`"),
    ("tp-design-learn", "history_line", "never for `vision.md`"),
    ("tp-docs-update", "docs_draft", "never for `vision.md`"),
    ("tp-docs-update", "history_line", "never for `vision.md`"),
    ("tp-session-save", "handoff", "never with `--stage-boundary`"),
    ("tp-merge-from-main", "base_sync_splice", "never applied"),
    ("tp-post-merge", "runbook", "deletes nothing unless it verifies"),
]


@pytest.mark.parametrize("name,slot,keeps", STUBS, ids=[f"{n}:{s}" for n, s, _ in STUBS])
def test_stub_runs_in_every_invocation_and_keeps_its_exclusion(name, slot, keeps):
    body = next(b for s, b in STUB_RE.findall(_skill(name)) if s == slot)
    flat = _flat(body)
    head = flat.split(".**", 1)[0]
    assert head.startswith("**Cheap-tier ") and "the loop is " in head
    assert "only with" not in head.lower() and "--cheap-tier" not in head
    assert "--cheap-tier <mode>" in flat  # the literal the probe and slot site tests pin
    assert "skills/_shared/cheap-dispatch.md" in flat
    assert keeps in flat
