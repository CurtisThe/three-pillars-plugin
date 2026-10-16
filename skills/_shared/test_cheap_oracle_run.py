"""Tests for cheap_oracle_run.py — the executing oracles and the check CLI.

design: cheap-tier-offload (Tasks 2.2, 2.3). Real subprocesses in a tmp work
tree, with a stubbed test command (a python -c one-liner) in place of pytest.
No oracle calls version control, so the tree is a plain tmp dir.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_oracle  # noqa: E402
import cheap_oracle_run as cor  # noqa: E402

PY = sys.executable


def _stub(code: int) -> list:
    """A stubbed test command that exits code."""
    return [PY, "-c", f"raise SystemExit({code})"]


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "marker.txt").write_text("here\n", encoding="utf-8")
    return root


# --- Task 2.2: exit_code ---------------------------------------------------------


def test_exit_code_registered_into_cheap_oracle():
    assert cheap_oracle.ORACLES["exit_code"] is cor.exit_code


def test_exit_code_passes_on_exit_zero(tree):
    ok, reason = cor.exit_code({}, {"verify_argv": _stub(0), "cwd": str(tree)})
    assert ok is True and reason == ""


def test_exit_code_fails_on_nonzero_exit(tree):
    ok, reason = cor.exit_code({}, {"verify_argv": _stub(3), "cwd": str(tree)})
    assert ok is False and "exited 3" in reason


def test_exit_code_runs_in_ctx_cwd(tree, tmp_path):
    probe = [PY, "-c", "import os; raise SystemExit(0 if os.path.exists('marker.txt') else 1)"]
    assert cor.exit_code({}, {"verify_argv": probe, "cwd": str(tree)})[0] is True
    assert cor.exit_code({}, {"verify_argv": probe, "cwd": str(tmp_path)})[0] is False


def test_exit_code_fails_on_timeout(tree):
    slow = [PY, "-c", "import time; time.sleep(10)"]
    ok, reason = cor.exit_code({}, {"verify_argv": slow, "cwd": str(tree), "timeout": 0.5})
    assert ok is False and "timeout" in reason


def test_exit_code_ignores_artifact_claims(tree):
    art = {"exit": 0, "ran": True, "passed": True, "ok": True}
    v = cheap_oracle.check("runbook", art, {"verify_argv": _stub(1), "cwd": str(tree)})
    assert v["ok"] is False and v["oracle"] == "exit_code"
    assert cheap_oracle.settle("runbook", v) == "escalate"


def test_check_lazily_finds_exit_code(tree, monkeypatch):
    # A scratch registry: the re-import registers fresh functions, which must not
    # leak into the tests that compare ORACLES entries with cor.* by identity.
    scratch = dict(cheap_oracle.ORACLES)
    del scratch["exit_code"]
    monkeypatch.setattr(cheap_oracle, "ORACLES", scratch)
    monkeypatch.delitem(sys.modules, "cheap_oracle_run")
    v = cheap_oracle.check("runbook", {}, {"verify_argv": _stub(0), "cwd": str(tree)})
    assert v == {"ok": True, "oracle": "exit_code", "reason": ""}


# --- Task 2.3: reproducer_fixed ------------------------------------------------------

_IS_FIXED = ("import pathlib; text = pathlib.Path('a.py').read_text(encoding='utf-8'); "
             "raise SystemExit(0 if text == 'fixed' else 1)")


def _finding():
    return {"verdict": "structural", "file": "a.py", "blocking": True,
            "reproducer": {"kind": "command", "argv": [PY, "-c", _IS_FIXED],
                           "expect": {"exit": 0}}}


def _fix_ctx(tree, content, test_code=0):
    (tree / "a.py").write_text(content, encoding="utf-8")
    return {"finding": _finding(), "cwd": str(tree), "scratch_dir": str(tree.parent / "scr"),
            "test_argv": _stub(test_code)}


def test_reproducer_fixed(tree):
    assert cheap_oracle.ORACLES["reproducer_fixed"] is cor.reproducer_fixed
    assert cor.reproducer_fixed({}, _fix_ctx(tree, "fixed")) == (True, "")
    still, reason = cor.reproducer_fixed({}, _fix_ctx(tree, "broken"))
    assert still is False and "reproduced" in reason
    red_tests, reason = cor.reproducer_fixed({}, _fix_ctx(tree, "fixed", test_code=1))
    assert red_tests is False and "test_argv exited 1" in reason


def test_reproducer_fixed_needs_a_runnable_reproducer(tree):
    ctx = _fix_ctx(tree, "fixed")
    ctx["finding"] = dict(ctx["finding"], reproducer=None)
    ok, reason = cor.reproducer_fixed({}, ctx)
    assert ok is False and "reproducer" in reason


def test_reproducer_fixed_ignores_claims(tree):
    art = {"exit": 0, "ran": True, "passed": True, "ok": True}
    v = cheap_oracle.check("pr_fix_reproducer", art, _fix_ctx(tree, "broken"))
    assert v["ok"] is False
    assert cheap_oracle.settle("pr_fix_reproducer", v) == "escalate"


# --- Task 2.3: zero_drop ---------------------------------------------------------

OURS = "### L1: Alpha entry\n\nbody a\n"
THEIRS = "### L2: Beta entry\n\nbody b\n"


def _splice_ctx(tree, ours=OURS, theirs=THEIRS):
    (tree / "ours.md").write_text(ours, encoding="utf-8")
    (tree / "theirs.md").write_text(theirs, encoding="utf-8")
    return {"ours_path": str(tree / "ours.md"), "theirs_path": str(tree / "theirs.md")}


def test_zero_drop(tree):
    assert cheap_oracle.ORACLES["zero_drop"] is cor.zero_drop
    both = {"resolved": OURS + "\n" + THEIRS}
    assert cor.zero_drop(both, _splice_ctx(tree)) == (True, "")
    ok, reason = cor.zero_drop({"resolved": OURS}, _splice_ctx(tree))
    assert ok is False and "DROPS_DETECTED" in reason
    v = cheap_oracle.check("base_sync_splice", {"resolved": OURS}, _splice_ctx(tree))
    assert v["ok"] is False and cheap_oracle.settle("base_sync_splice", v) == "drop"


def test_zero_drop_unverifiable_drops(tree):
    ctx = _splice_ctx(tree, ours="plain prose\n", theirs="more prose\n")
    v = cheap_oracle.check("base_sync_splice", {"resolved": "plain prose\nmore prose\n"}, ctx)
    assert v["ok"] is False and "UNVERIFIABLE" in v["reason"]
    assert cheap_oracle.settle("base_sync_splice", v) == "drop"


# A one-side retitle on disk: base and ours carry the old title, theirs retitled it, and the
# proposed splice keeps theirs' (new) title. The three-way verifier excuses the old title only
# when it is handed the merge base.
RETITLE_BASE = "### M44: old title\nclosed body\n\n### L1: other\ntail\n"
RETITLE_NEW = "### M44: renamed title\nclosed body\n\n### L1: other\ntail\n"


def _retitle_ctx(tree, with_base):
    ctx = _splice_ctx(tree, ours=RETITLE_BASE, theirs=RETITLE_NEW)
    (tree / "base.md").write_text(RETITLE_BASE, encoding="utf-8")
    if with_base:
        ctx["base_path"] = str(tree / "base.md")
    return ctx


def test_zero_drop_with_base_path_excuses_a_one_side_retitle(tree):
    ok, reason = cor.zero_drop({"resolved": RETITLE_NEW}, _retitle_ctx(tree, with_base=True))
    assert (ok, reason) == (True, "")


def test_zero_drop_without_base_path_is_two_way(tree):
    ok, reason = cor.zero_drop({"resolved": RETITLE_NEW}, _retitle_ctx(tree, with_base=False))
    assert ok is False and reason.startswith("DROPS_DETECTED (dropped: ")


# --- Task 2.3: the check CLI ---------------------------------------------------------


def _cli(tmp_path, *args):
    proc = subprocess.run([PY, str(Path(cor.__file__)), "check", *args],
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def _json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_check_cli(tree, tmp_path):
    ctx = _json(tmp_path / "c.json", {"verify_argv": _stub(0), "cwd": str(tree)})
    art = _json(tmp_path / "a.json", {"exit": 1})
    rc, out = _cli(tmp_path, "--slot", "runbook", "--artifact", art, "--ctx", ctx)
    assert rc == 0 and out == {"verdict": {"ok": True, "oracle": "exit_code", "reason": ""},
                               "action": "accept"}
    splice = _json(tmp_path / "s.json", _splice_ctx(tree))
    drop = _json(tmp_path / "d.json", {"resolved": OURS})
    rc, out = _cli(tmp_path, "--slot", "base_sync_splice", "--artifact", drop, "--ctx", splice)
    assert rc == 0 and out["action"] == "drop" and out["verdict"]["ok"] is False


@pytest.mark.parametrize("slot, artifact", [("task", "a.json"), ("nope", "a.json"),
                                            ("runbook", "missing.json"),
                                            ("runbook", "bad.json")])
def test_check_cli_errors_still_exit_zero(tmp_path, slot, artifact):
    _json(tmp_path / "a.json", {})
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    ctx = _json(tmp_path / "c.json", {})
    rc, out = _cli(tmp_path, "--slot", slot, "--artifact", str(tmp_path / artifact),
                   "--ctx", ctx)
    assert rc == 0 and out["verdict"]["ok"] is False and out["action"] == "escalate"


# --- PR #191 review r1: an unresolved splice, and cli-error follows on_fail -----------

SHARED_OURS = "## Known issues\n\n### L1: alpha\nbody a\n"
SHARED_THEIRS = "## Known issues\n\n### L2: beta\nbody b\n"


@pytest.mark.parametrize("resolved", [
    "<<<<<<< HEAD\n" + SHARED_OURS + "=======\n" + SHARED_THEIRS + ">>>>>>> origin/master\n",
    "## Known issues\n\n<<<<<<< ours\n### L1: alpha\nbody a\n||||||| base\n=======\n"
    "### L2: beta\nbody b\n>>>>>>> theirs\n",
    SHARED_OURS + SHARED_THEIRS,
    SHARED_THEIRS + "\n" + SHARED_OURS,
])
def test_zero_drop_refuses_an_unresolved_splice(tree, resolved):
    ctx = _splice_ctx(tree, ours=SHARED_OURS, theirs=SHARED_THEIRS)
    v = cheap_oracle.check("base_sync_splice", {"resolved": resolved}, ctx)
    assert v["ok"] is False and cheap_oracle.settle("base_sync_splice", v) == "drop", v
    good = "## Known issues\n\n### L1: alpha\nbody a\n\n### L2: beta\nbody b\n"
    assert cor.zero_drop({"resolved": good}, ctx) == (True, "")


def test_zero_drop_keeps_a_marker_like_line_both_sides_carry(tree):
    ours = "Title\n=======\n\n### L1: alpha\nbody a\n"
    theirs = "Title\n=======\n\n### L2: beta\nbody b\n"
    good = "Title\n=======\n\n### L1: alpha\nbody a\n\n### L2: beta\nbody b\n"
    assert cor.zero_drop({"resolved": good}, _splice_ctx(tree, ours, theirs)) == (True, "")


@pytest.mark.parametrize("slot, action", [("base_sync_splice", "drop"), ("handoff", "drop"),
                                          ("runbook", "escalate"), ("nope", "escalate")])
def test_cli_error_maps_to_the_slot_on_fail(tmp_path, slot, action):
    missing = str(tmp_path / "missing.json")
    out = cor.run_check(slot, missing, missing)
    assert out["verdict"]["ok"] is False and out["verdict"]["reason"].startswith("cli-error")
    assert out["action"] == action, out
