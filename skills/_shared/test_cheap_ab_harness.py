"""Tests for the cheap_ab.py harness gaps from PR #191 review r1.

design: none (just-do-it, roadmap row "cheap-tier A/B runs"). Two gaps live here:

- `alt_arm` parity survives the rows tp-post-merge step 6 reverts: `alt-arm` keeps
  its own pick count in the git common dir, shared by every worktree;
- `budget` sees the in-flight `ab` rows of every worktree of the repo, and charges a
  `tokens: null` inline row from the measured rows before the UNKNOWN placeholder.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_ab as ab  # noqa: E402

NDJSON = "dispatch-telemetry.ndjson"


def _git(cwd, *args) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


def _append(root: Path, rel: str, *rows: dict) -> None:
    path = root / "three-pillars-docs" / rel / NDJSON
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, sort_keys=True) + "\n" for r in rows)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "seat"
    root.mkdir()
    _git(root, "init", "-q", "-b", "master")
    _git(root, "commit", "-q", "--allow-empty", "-m", "init")
    return root


def _alt(root: Path, capsys) -> str:
    assert ab.main(["alt-arm", "--slot", "runbook", "--root", str(root)]) == 0
    return capsys.readouterr().out.strip()


# --- (b) alternation state outside the reverted row --------------------------------


def test_alt_arm_takes_the_larger_of_rows_and_picks():
    rows = [{"slot": "runbook", "ab_pair": "alt:runbook", "rung": "code"}]
    assert ab.alt_arm(rows, "runbook") == "opus"
    assert ab.alt_arm(rows, "runbook", taken=None) == "opus"
    assert ab.alt_arm(rows, "runbook", taken=2) == "cheap"  # one pick's row was reverted
    assert ab.alt_arm(rows, "runbook", taken=0) == "opus"  # a stale count never lowers it


def test_alt_arm_cli_alternates_when_every_row_is_reverted(repo, capsys):
    """Step 6 reverts the row on a no-commit run: the parity still alternates."""
    assert [_alt(repo, capsys) for _ in range(4)] == ["cheap", "opus", "cheap", "opus"]
    assert not list(repo.rglob(NDJSON))  # no row was ever written
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                          text=True).stdout == ""  # the state never dirties the tree


def test_alt_arm_state_is_shared_by_every_worktree(repo, tmp_path, capsys):
    other = tmp_path / "wt" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "tp/foo", str(other))
    assert _alt(repo, capsys) == "cheap"
    assert _alt(other, capsys) == "opus"
    assert _alt(repo, capsys) == "cheap"


def test_alt_arm_cli_outside_git_uses_row_parity(tmp_path, capsys):
    _append(tmp_path, "completed-tp-designs/a",
            {"slot": "runbook", "ab_pair": "alt:runbook", "rung": "code", "oracle": "pass"})
    assert _alt(tmp_path, capsys) == "opus"
    assert _alt(tmp_path, capsys) == "opus"  # no state to advance: rows only, exit 0


# --- (c) budget across worktrees + telemetry charging ------------------------------


def _ab(slot, rung, pair, tokens, agent="tp-drafter") -> dict:
    return {"slot": slot, "rung": rung, "ab_pair": pair, "tokens": tokens, "agent": agent,
            "oracle": "pass"}


def test_budget_sees_in_flight_rows_of_every_worktree(repo, tmp_path, capsys):
    _append(repo, "completed-tp-designs/old", _ab("handoff", "sonnet-medium", "p1", 1000))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "row")
    other = tmp_path / "wt" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "tp/foo", str(other))
    _append(other, "tp-designs/foo", _ab("handoff", "sonnet-medium", "p2", 3000))
    _append(repo, "completed-tp-designs/old", _ab("docs_draft", "sonnet-medium", "p3", 500))
    for root in (repo, other):
        assert ab.main(["budget", "--root", str(root)]) == 0
        got = json.loads(capsys.readouterr().out)
        assert got["spent"] == 4500, root  # the shared committed row counts once


def test_load_all_rows_outside_git_is_this_checkout(tmp_path):
    _append(tmp_path, "tp-designs/a", _ab("handoff", "sonnet-medium", "p1", 700))
    rows, malformed = ab.load_all_rows(tmp_path)
    assert [r["tokens"] for r in rows] == [700] and malformed == 0


def test_budget_charges_null_inline_rows_from_measured_rows():
    measured = [_ab("runbook", "opus-xhigh", "alt:runbook", 30_000),
                _ab("runbook", "opus-xhigh", "alt:runbook", 50_000)]
    inline = _ab("runbook", "opus-xhigh", "alt:runbook", None, agent=None)
    assert ab.budget(measured + [inline])["spent"] == 80_000 + 40_000  # the slot-arm mean


def test_budget_falls_back_to_the_arm_mean_then_the_placeholder():
    inline = _ab("runbook", "opus-xhigh", "alt:runbook", None, agent=None)
    other_slot = _ab("handoff", "opus-medium", "p1", 60_000)
    assert ab.budget([other_slot, inline])["spent"] == 60_000 + 60_000
    cheap_only = _ab("handoff", "sonnet-medium", "p1", 9_000)
    assert ab.budget([cheap_only, inline])["spent"] == 9_000 + ab.UNKNOWN_ROW_TOKENS


def test_budget_keeps_the_placeholder_for_spawned_null_rows_and_zero_for_code():
    measured = _ab("handoff", "opus-medium", "p1", 10_000)
    spawned = _ab("handoff", "opus-medium", "p2", None)
    code = _ab("runbook", "code", "alt:runbook", None, agent=None)
    assert ab.budget([measured, spawned, code])["spent"] == 10_000 + ab.UNKNOWN_ROW_TOKENS


# --- PR #196 r1 notes ----------------------------------------------------------------


def test_report_budget_line_matches_the_budget_cli(repo, tmp_path, capsys):
    other = tmp_path / "wt" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "tp/foo", str(other))
    _append(other, "tp-designs/foo", _ab("handoff", "sonnet-medium", "p1", 3000))
    assert ab.main(["budget", "--root", str(repo)]) == 0
    cli = json.loads(capsys.readouterr().out)
    line = [ln for ln in ab.report(repo).splitlines() if ln.startswith("budget: ")][0]
    assert json.loads(line[len("budget: "):]) == cli and cli["spent"] == 3000


def test_budget_skips_an_unreadable_worktree(repo, tmp_path, capsys):
    other = tmp_path / "wt" / "foo"
    _git(repo, "worktree", "add", "-q", "-b", "tp/foo", str(other))
    _append(repo, "tp-designs/a", _ab("handoff", "sonnet-medium", "p1", 700))
    _append(other, "tp-designs/foo", _ab("handoff", "sonnet-medium", "p2", 900))
    locked = other / "three-pillars-docs" / "tp-designs"
    locked.chmod(0)
    try:
        assert ab.main(["budget", "--root", str(repo)]) == 0
        assert json.loads(capsys.readouterr().out)["spent"] == 700
    finally:
        locked.chmod(0o755)


def test_a_non_int_stored_count_is_ignored(repo, capsys):
    import cheap_ab_state
    path = cheap_ab_state.state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"runbook": True}), encoding="utf-8")
    assert _alt(repo, capsys) == "cheap"
    assert json.loads(path.read_text(encoding="utf-8")) == {"runbook": 1}


# --- PR #196 r2 notes ----------------------------------------------------------------


def test_concurrent_alt_arm_calls_never_lose_a_pick(repo):
    procs = [subprocess.Popen([sys.executable, str(Path(ab.__file__)), "alt-arm", "--slot",
                               "runbook", "--root", str(repo)], stdout=subprocess.PIPE,
                              text=True) for _ in range(12)]
    arms = sorted(p.communicate()[0].strip() for p in procs)
    assert arms == ["cheap"] * 6 + ["opus"] * 6
    import cheap_ab_state
    assert cheap_ab_state.read_state(cheap_ab_state.state_path(repo)) == {"runbook": 12}


def test_alt_arm_runs_unlocked_when_flock_fails(repo, capsys, monkeypatch):
    import cheap_ab_state

    def no_locks(*args):
        raise OSError(37, "No locks available")

    monkeypatch.setattr(cheap_ab_state.fcntl, "flock", no_locks)
    assert [_alt(repo, capsys) for _ in range(2)] == ["cheap", "opus"]
