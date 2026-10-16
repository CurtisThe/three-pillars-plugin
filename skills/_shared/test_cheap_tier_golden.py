"""test_cheap_tier_golden.py — with the one off key set, cheap-tier changes nothing.

design: cheap-tier-offload (Task 4.2, Behavior 5, D6); rebased by one-cheap-engine 2.4.

A characterization test: it is red only on a leak. The cheap tier is always on (an absent
`--cheap-tier` is `on`), so the one key left that turns a site off is `models.<slot>: "off"`
(and `models.task: "off"` for the lever). With it set, every site runs today's path, so every
observable output here is byte-identical to the pre-cheap-tier behaviour:

- `cheap_tier_cli.py spec` prints a null rung for the slot and never probes the lease;
- `cheap_tier_cli.py task-table` prints `[]` and exits 1 when the lever is opted out
  (`models.task: "off"`), whatever the flag;
- `design_run_command.slash_command` / `window_command` without `cheap_tier` give
  today's strings (a pinned matrix);
- a legacy `dispatch_log.record` call gives a pinned row;
- the repo's own `.three-pillars/config.json` validates against the schema, and
  the loader prunes nothing from it.

With no off key, the no-flag cases expect the shipped rung (`test_spec_no_flag_gives_the_shipped_rung`).
"""
from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import cheap_tier  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402
import design_run_command as drc  # noqa: E402
import dispatch_log  # noqa: E402
import repo_config_load  # noqa: E402

ROOT = _SHARED.parents[1]
CONFIG = ROOT / ".three-pillars" / "config.json"
PLAN = ROOT / "three-pillars-docs" / "completed-tp-designs" / "cheap-tier-offload" / "plan.md"
UNSET = {"schema_version": 1}  # a config with no `models` key at all


@pytest.fixture
def no_lease(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the lease was probed with the keys unset")

    monkeypatch.setattr(cli.local_lease, "acquire", refuse)


def _root(tmp_path: Path, config: dict) -> Path:
    cfg = tmp_path / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def _plan(tmp_path: Path) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(
        "## Phase 1: Fixture\n\n### Task 1.1: a small edit\n"
        "**File**: `a.py` (modify)\n**Test**: t\n**Targets**: `test_a.py`\n"
        "**Red**: r\n**Green**: g\n", encoding="utf-8")
    return plan


# --- spec ---------------------------------------------------------------------------

PINNED_NULL = '{"rung": null, "slot": "%s"}\n'


SHIPPED_ON = {s for s, r in cheap_tier.SLOTS.items() if r.default is not None}
FLAGS = [[], ["--cheap-tier", "on"], ["--cheap-tier", "ab"]]


def _only_deprecation(err: str, flag: list) -> bool:
    """stderr is empty, or (for `--cheap-tier ab`) exactly one `deprecated:` line."""
    lines = err.splitlines()
    return len(lines) == (1 if flag[-1:] == ["ab"] else 0) and all(
        ln.startswith("deprecated: ") for ln in lines)


@pytest.mark.parametrize("slot", sorted(cheap_tier.SLOTS.keys() - {"task"}))
@pytest.mark.parametrize("flag", FLAGS)
def test_spec_is_null_for_every_slot(tmp_path, capsys, no_lease, slot, flag):
    """`models.<slot>: "off"`, with any flag: the pinned null line, exit 0. A slot with no
    shipped default (handoff) is also null with no `models.<slot>` at all."""
    roots = [_root(tmp_path / "off", {"models": {slot: "off"}})]
    if slot not in SHIPPED_ON:
        roots.append(_root(tmp_path / "unset", UNSET))
    for root in roots:
        code = cli.main(["spec", "--slot", slot, "--root", str(root), *flag])
        out, err = capsys.readouterr()
        assert (code, out) == (0, PINNED_NULL % slot) and _only_deprecation(
            err, flag), f"opt-out not honoured for {slot}"


@pytest.mark.parametrize("slot", sorted(SHIPPED_ON - {"task", "classifier_judge"}))
def test_spec_no_flag_gives_the_shipped_rung(tmp_path, capsys, no_lease, slot):
    """No flag and no `models.<slot>`: the shipped rung (its Sonnet mirror when unrouted).
    classifier_judge keeps its own eval-verdict gate, so it is not in this list."""
    code = cli.main(["spec", "--slot", slot, "--root", str(_root(tmp_path, UNSET))])
    out, err = capsys.readouterr()
    default = cheap_tier.SLOTS[slot].default
    want = cheap_tier.MIRROR.get(default, default)
    assert (code, err) == (0, "") and json.loads(out)["rung"] == want


def test_spec_flag_off_ignores_a_set_key(tmp_path, no_lease):
    """A programmatic `cheap_flag="off"` (no CLI value): null, and the config is never read."""
    root = _root(tmp_path, {"models": {"handoff": "sonnet-medium", "runbook": "code"}})
    for slot in ("handoff", "runbook"):
        assert cli.spec(slot, root, cheap_flag="off") == {"slot": slot, "rung": None}
    (root / ".three-pillars" / "config.json").write_text("{not json", encoding="utf-8")
    assert cli.spec("handoff", root, cheap_flag="off") == {"slot": "handoff", "rung": None}


def test_spec_cli_subprocess_prints_the_pinned_line():
    proc = subprocess.run([sys.executable, str(_SHARED / "cheap_tier_cli.py"), "spec",
                           "--slot", "handoff", "--root", str(ROOT)],
                          capture_output=True, text=True, encoding="utf-8")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, PINNED_NULL % "handoff", "")


# --- task-table ---------------------------------------------------------------------


OFF_TASK = {"models": {"task": "off"}}  # the lever's only opt-out (operator 2026-10-07)


@pytest.mark.parametrize("flag", FLAGS)
def test_task_table_is_off(tmp_path, capsys, flag):
    """`models.task: "off"`, with any flag: `[]` and exit 1, so the worker takes today's path."""
    code = cli.main(["task-table", "--plan", str(_plan(tmp_path)), "--phase", "1",
                     "--root", str(_root(tmp_path / "off", OFF_TASK)), *flag])
    out, err = capsys.readouterr()
    assert (code, out) == (1, "[]\n") and _only_deprecation(err, flag)


@pytest.mark.parametrize("flag", FLAGS)
def test_task_table_is_on_by_default(tmp_path, capsys, flag):
    """The shipped `task` default: no flag and no models key is enough (always on)."""
    for name, config in (("unset", UNSET), ("task", {"models": {"task": "sonnet-xhigh"}})):
        code = cli.main(["task-table", "--plan", str(_plan(tmp_path)), "--phase", "1",
                         "--root", str(_root(tmp_path / name, config)), *flag])
        out, err = capsys.readouterr()
        assert code == 0 and json.loads(out)[0]["task_id"] == "1.1"
        assert _only_deprecation(err, flag)


def test_task_table_on_the_live_plan_is_off(tmp_path, capsys):
    if not (ROOT / "three-pillars-docs").is_dir():  # a plugin install ships no docs
        pytest.skip("no three-pillars-docs/ in this tree")
    assert PLAN.is_file(), f"the archived plan is missing: {PLAN}"
    code = cli.main(["task-table", "--plan", str(PLAN), "--phase", "4",
                     "--root", str(_root(tmp_path, OFF_TASK)), "--cheap-tier", "on"])
    assert (code, capsys.readouterr().out) == (1, "[]\n")


# --- the run command ----------------------------------------------------------------

MODES = [None, "build"]
SLASH = {  # (mode, skip_design, local) -> today's string, pinned before the flag landed
    (None, False, False): "/tp-run-full-design foo",
    (None, False, True): "/tp-run-full-design foo --local",
    (None, True, False): "/tp-run-full-design foo --skip-design",
    (None, True, True): "/tp-run-full-design foo --skip-design --local",
    ("build", False, False): "/tp-run-full-design foo --mode build",
    ("build", False, True): "/tp-run-full-design foo --mode build --local",
    ("build", True, False): "/tp-run-full-design foo --mode build --skip-design",
    ("build", True, True): "/tp-run-full-design foo --mode build --skip-design --local",
}


@pytest.mark.parametrize("mode,skip,local", list(itertools.product(MODES, [False, True],
                                                                    [False, True])))
def test_slash_command_matrix_unchanged(mode, skip, local):
    want = SLASH[(mode, skip, local)]
    assert drc.slash_command("foo", mode=mode, skip_design=skip, local=local) == want
    assert drc.slash_command("foo", mode=mode, skip_design=skip, local=local,
                             cheap_tier=None) == want


def test_window_command_unchanged():
    assert drc.window_command("foo", "/w/foo", config_dir="/p", model="opus", local=True) == (
        "cd /w/foo && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR=/p "
        "claude --model opus --effort high --name foo '/tp-run-full-design foo --local'; exec bash")


# --- telemetry + config -------------------------------------------------------------

# Pinned from the pre-design `dispatch_log.py` (the plan-audit commit, before Phase 1).
LEGACY_ROW = (
    '{"agent": null, "effort": "inline (dispatcher effort)", '
    '"ended_at": "2026-01-01T00:01:00Z", "model": "opus", "outcome": "ok", "phase": "4", '
    '"reason": "phase 4", "role": "worker", "route": "-", "rung": null, '
    '"served_by": "opus", "started_at": "2026-01-01T00:00:00Z", "tokens": null, '
    '"tokens_reason": "the spawn reported no usage total", "wall_s": 60.0}'
)


def test_legacy_dispatch_record_is_pinned():
    rec = dispatch_log.record("unused", role="worker", agent=None, reason="phase 4",
                              outcome="ok", phase=4, started_at="2026-01-01T00:00:00Z",
                              ended_at="2026-01-01T00:01:00Z")
    assert not {"slot", "oracle", "escalated", "ab_pair"} & set(rec), "a cheap-tier key leaked"
    assert json.dumps(rec, sort_keys=True) == LEGACY_ROW


def test_repo_config_is_valid_and_nothing_is_pruned():
    if not CONFIG.is_file():  # a plugin install ships no repo config
        pytest.skip("no .three-pillars/config.json in this tree")
    jsonschema = pytest.importorskip("jsonschema")
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    schema = json.loads((_SHARED / "repo-config.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)
    assert repo_config_load.load_repo_config(str(ROOT)).config == raw  # nothing pruned
