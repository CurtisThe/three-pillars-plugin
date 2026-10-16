"""Tests for the always-on cheap tier in `cheap_tier_cli.py`.

design: one-cheap-engine (Task 2.4; skills/_shared/test-fragility.md).

`spec` and `task-table` with no `--cheap-tier` behave as `on`. `--cheap-tier=ab` parses, runs
as `on` and prints one `deprecated:` line on stderr. `models.<slot>: "off"` is the one switch
left, and it still turns a slot off. Every case uses a tmp repo root holding only
`.three-pillars/config.json`; the lease is never reached (the route is absent, so an unrouted
site never probes it) and `TP_LOCAL` / `TP_LOCAL_MODE` are cleared.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_tier  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402
import task_eligibility  # noqa: E402

PLAN = ("## Phase 1: Fixture\n\n### Task 1.1: a small edit\n"
        "**File**: `a.py` (modify)\n**Test**: t\n**Targets**: `test_a.py`\n"
        "**Red**: r\n**Green**: g\n")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("TP_LOCAL", raising=False)
    monkeypatch.delenv("TP_LOCAL_MODE", raising=False)

    def refuse(*_a, **_k):
        raise AssertionError("the lease was probed without a route")

    monkeypatch.setattr(cli.local_lease, "acquire", refuse)


def _root(tmp_path: Path, config) -> Path:
    cfg = tmp_path / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path


def _run(capsys, argv):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


def _spec(capsys, root: Path, slot: str, *extra: str):
    return _run(capsys, ["spec", "--slot", slot, "--root", str(root), *extra])


def _table(capsys, root: Path, *extra: str):
    plan = root / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    return _run(capsys, ["task-table", "--plan", str(plan), "--phase", "1",
                         "--root", str(root), *extra])


def test_absent_flag_is_on(tmp_path, capsys):
    """No `--cheap-tier`: the shipped rung runs (it was a null rung before)."""
    code, spec, err = _spec(capsys, _root(tmp_path, {}), "docs_draft")
    assert (code, err) == (0, "")
    assert spec["rung"] == "sonnet-medium" and spec["mode"] == "on"  # unrouted: the mirror
    assert "missing-route" in spec["why"]
    code, spec, _err = _spec(capsys, _root(tmp_path / "c", {"models": {"runbook": "code"}}),
                             "runbook")
    assert (code, spec["rung"], spec["mode"]) == (0, "code", "on")
    explicit = _spec(capsys, _root(tmp_path / "e", {}), "docs_draft", "--cheap-tier", "on")
    assert explicit[:2] == _spec(capsys, _root(tmp_path / "f", {}), "docs_draft")[:2]


def test_absent_flag_is_on_for_the_function_too(tmp_path):
    """`spec()` and `task_table()` default the flag to on; an unset slot stays null."""
    root = _root(tmp_path, {})
    assert cli.spec("docs_draft", root)["rung"] == "sonnet-medium"
    assert cli.spec("handoff", root) == {"slot": "handoff", "rung": None}  # no shipped default
    plan = root / "plan.md"
    plan.write_text(PLAN, encoding="utf-8")
    assert cli.task_table(str(plan), 1, root)


def test_task_table_sonnet_first_without_local(tmp_path, capsys):
    root = _root(tmp_path, {})
    code, rows, err = _table(capsys, root)
    assert (code, err) == (0, "")
    want = cheap_tier.task_table(task_eligibility.phase_rows(PLAN, 1, root))
    assert rows == json.loads(json.dumps(want))
    assert rows and all(r["tier"] != "local" for r in rows)
    assert all(str(r["start_rung"]).startswith("sonnet") for r in rows if r["tier"] == "sonnet")


def test_ab_runs_as_on_with_one_deprecation_line(tmp_path, capsys):
    root = _root(tmp_path, {})
    on = _spec(capsys, root, "docs_draft", "--cheap-tier", "on")
    code, spec, err = _spec(capsys, root, "docs_draft", "--cheap-tier", "ab")
    assert (code, spec) == (0, on[1]) and spec["mode"] == "on"
    lines = err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("deprecated: ") and "--cheap-tier=ab" in lines[0]
    assert on[2] == ""  # bare `--cheap-tier on` (the sites' literal) stays quiet
    tcode, rows, terr = _table(capsys, root, "--cheap-tier", "ab")
    assert (tcode, rows) == (0, _table(capsys, root)[1])
    tlines = terr.strip().splitlines()
    assert len(tlines) == 1 and tlines[0].startswith("deprecated: ")


def test_slot_off_still_off(tmp_path, capsys):
    off = _root(tmp_path, {"models": {"docs_draft": "off", "task": "off"}})
    for extra in ((), ("--cheap-tier", "on"), ("--cheap-tier", "ab")):
        code, spec, _err = _spec(capsys, off, "docs_draft", *extra)
        assert (code, spec) == (0, {"slot": "docs_draft", "rung": None})
        tcode, rows, _terr = _table(capsys, off, *extra)
        assert (tcode, rows) == (1, [])
    code, spec, _err = _spec(capsys, off, "history_line")  # only the named slot is off
    assert code == 0 and spec["rung"] == "sonnet-medium"
