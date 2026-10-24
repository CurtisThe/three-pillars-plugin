"""test_seat_commit_guard.py — a Claude session that is not the run may not commit a
conflicted merge in a run's worktree.

design: seat-escalate-first 3.4 (B11 B13) — mid-merge in an orchestrator-held `tp/<slug>`
worktree, a seat (`CLAUDE_LAUNCHER_ROLE=seat`) or any Claude session (`CLAUDECODE=1`) is
refused unless an answered (not `stop-run`) `base-sync-hunk` / `scope-growth` ruling for the
slug is not older than the merge (`MERGE_HEAD`'s mtime); the run (`TP_DESIGN_RUN=1`), the
operator's terminal and a human-owned worktree pass. Every fixture is a tmp git repo with
a real conflicting merge and an explicit env mapping; no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
for _p in (_SHARED, _SHARED.parent / "tp-escalate" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import finalizer_cli  # noqa: E402
import finalizer_ruling as fr  # noqa: E402
import ruling_cli  # noqa: E402
import ruling_file  # noqa: E402
import seat_brief  # noqa: E402
import seat_commit_guard as guard  # noqa: E402

SEAT = {"CLAUDE_LAUNCHER_ROLE": "seat"}
CLAUDE = {"CLAUDECODE": "1"}
RUN_SEAT = {"CLAUDE_LAUNCHER_ROLE": "seat", "TP_DESIGN_RUN": "1"}
RUN_CLAUDE = {"CLAUDECODE": "1", "TP_DESIGN_RUN": "1"}
RULING_AT = "2026-10-21T12:00:00Z"
BEFORE_RULING = "2026-10-21T11:00:00Z"  # the merge started before the ruling was minted
AFTER_RULING = "2026-10-21T13:00:00Z"  # the merge (re)started after the ruling was minted
REFUSAL_NAMES = ("/tp-escalate", "base-sync-hunk", "scope-growth", "run-safety.md",
                 "aborted and redone")
RUN_SAFETY = _SHARED.parent / "tp-run-full-design" / "run-safety.md"


def _git(repo, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                           "-c", "user.name=fixture", *args],
                          check=check, capture_output=True, text=True, env=env)


def _merge_head(wt):
    line = _git(wt, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip()
    return Path(wt) / line


def _merge(wt):
    """Start the real conflicting merge of `other` into the worktree's branch."""
    _git(wt, "merge", "-q", "other", check=False)
    assert _merge_head(wt).exists(), "fixture: the merge must conflict"


def _setup(tmp_path, *, branch="tp/demo", owner="orchestrator:x@y", merge=True):
    """A base checkout on `main`, a run worktree beside it on `branch` carrying the design
    lock, and (by default) a conflicting merge of `other` in progress there."""
    base = tmp_path / "base"
    base.mkdir()
    _git(base, "init", "-q", "-b", "main")
    (base / "conflict.txt").write_text("base\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "base")
    _git(base, "checkout", "-q", "-b", "other")
    (base / "conflict.txt").write_text("other\n", encoding="utf-8")
    _git(base, "commit", "-q", "-am", "other")
    _git(base, "checkout", "-q", "main")
    wt = tmp_path / "wt-demo"
    _git(base, "worktree", "add", "-q", "-b", branch, str(wt), "main")
    lock_dir = wt / "three-pillars-docs" / "tp-designs" / "demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": owner, "phase": "plan"}), encoding="utf-8")
    (wt / "conflict.txt").write_text("wt\n", encoding="utf-8")
    _git(wt, "commit", "-q", "-am", "wt")
    if merge:
        _merge(wt)
    return base, wt


def _epoch(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp()


def _merge_started(wt, iso):
    """Pin MERGE_HEAD's mtime (when the merge started) to `iso`."""
    stamp = _epoch(iso)
    os.utime(_merge_head(wt), (stamp, stamp))


def _ruling(root, *, kind="base-sync-hunk", slug="demo", at=RULING_AT, question="Which side?"):
    """One ruling file through `ruling_file.write`, as a seat ruling; return its id."""
    stop = {"source": "question", "signal": kind, "target": slug,
            "detail": {"question": question}}
    path = ruling_file.write(root, scope=slug, entry="seat", stop=stop, key="q1",
                             result={"outcome": "escalate"}, model="fable", at=at)
    return ruling_file.parse(path)["front"]["id"]


def _answer(monkeypatch, root, rid, choice="Take theirs"):
    monkeypatch.chdir(root)
    assert ruling_cli.main(["answer", "--id", rid, "--choice", choice]) == 0


def _mint_seat_ruling(base, tmp_path, monkeypatch, capsys, kind="scope-growth"):
    """A ruling minted the seat's way: `seat_brief build`, then `finalizer_cli apply
    --entry seat` with an escalate-shaped reply, run from the base checkout."""
    monkeypatch.chdir(base)
    monkeypatch.setattr(seat_brief, "_default_registry_rows", lambda: [])
    question = tmp_path / "question.txt"
    question.write_text("Which side of the conflicted code stays?\n", encoding="utf-8")
    stop = tmp_path / "stop.json"
    assert seat_brief.main(["build", "--scope", "demo", "--question-file", str(question),
                            "--kind", kind, "--out", str(stop)]) == 0
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "outcome": "escalate", "actions": [], "diagnosis": "operator-only kind",
        "reasoning": "operator-only", "demoted": [], "blocked": [], **fr.EMPTY_RULING}),
        encoding="utf-8")
    capsys.readouterr()
    assert finalizer_cli.main([
        "apply", "--stop", str(stop), "--ledger", str(tmp_path / "ledger.json"),
        "--reply", str(reply), "--decisions", str(tmp_path / "decisions.md"),
        "--scope", "demo", "--entry", "seat"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["outcome"] == "escalate"
    return out["ruling_id"]


# --- the refusal (B11) -------------------------------------------------------------------

@pytest.mark.parametrize("env", [SEAT, CLAUDE], ids=["seat-role", "claude-code"])
def test_a_claude_session_mid_merge_in_a_run_worktree_is_refused(tmp_path, env):
    _, wt = _setup(tmp_path)
    msg = guard.check(wt, env)
    assert msg is not None
    for name in REFUSAL_NAMES:
        assert name in msg
    assert "TP_DESIGN_RUN" not in msg  # the refusal never names the env bypass
    assert msg.endswith("; the design run itself passes "
                        "(see skills/tp-run-full-design/run-safety.md)")
    assert "\n" not in msg
    if env.get("CLAUDE_LAUNCHER_ROLE") == "seat":
        # hand-resolve and stage the conflict: no unmerged paths, yet MERGE_HEAD still
        # disagrees. Run for the seat-role case only, so a mutant that drops this check
        # fails exactly one testcase of the node (the other case keeps the lines above).
        (wt / "conflict.txt").write_text("resolved by hand\n", encoding="utf-8")
        _git(wt, "add", "conflict.txt")
        assert not _git(wt, "ls-files", "-u").stdout.strip(), "fixture: no unmerged paths left"
        resolved = guard.check(wt, env)
        assert resolved is not None
        for name in REFUSAL_NAMES:
            assert name in resolved
        assert "TP_DESIGN_RUN" not in resolved
        assert resolved.endswith("; the design run itself passes "
                                 "(see skills/tp-run-full-design/run-safety.md)")
        assert "\n" not in resolved


def test_a_commit_from_a_subdirectory_of_the_worktree_is_refused(tmp_path):
    _, wt = _setup(tmp_path)
    (wt / "sub" / "deeper").mkdir(parents=True)
    assert guard.check(wt / "sub" / "deeper", SEAT) is not None


def test_run_safety_documents_the_hand_started_run_recipe():
    section = RUN_SAFETY.read_text(encoding="utf-8").split("## Lock ownership", 1)[1].split("\n## ", 1)[0]
    bullet = next(line for line in section.splitlines() if "seat_commit_guard" in line)
    assert "TP_DESIGN_RUN=1" in bullet  # pinned to the one named bullet of §Lock ownership


# --- who passes (B13) --------------------------------------------------------------------

@pytest.mark.parametrize("env", [RUN_SEAT, RUN_CLAUDE], ids=["seat-role", "claude-code"])
def test_the_design_run_itself_passes(tmp_path, env):
    _, wt = _setup(tmp_path)
    assert guard.check(wt, env) is None


def test_the_operator_terminal_passes(tmp_path):
    _, wt = _setup(tmp_path)
    assert guard.check(wt, {}) is None


def test_a_human_owned_worktree_passes(tmp_path):
    _, wt = _setup(tmp_path, owner="curtis@example.com")
    assert guard.check(wt, SEAT) is None


def test_no_merge_in_progress_passes(tmp_path):
    _, wt = _setup(tmp_path)
    _git(wt, "merge", "--abort")
    assert guard.check(wt, SEAT) is None


def test_a_non_tp_branch_passes(tmp_path):
    _, wt = _setup(tmp_path, branch="feature-demo")
    assert guard.check(wt, SEAT) is None


def test_a_directory_that_is_no_repository_passes(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert guard.check(plain, SEAT) is None


# --- the unlock: an answered ruling for this merge ---------------------------------------

@pytest.mark.parametrize("kind", ["base-sync-hunk", "scope-growth"])
def test_an_answered_ruling_newer_than_the_merge_unlocks_it(tmp_path, monkeypatch, kind):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, base, _ruling(base, kind=kind))
    assert guard.check(wt, SEAT) is None
    assert guard.check(wt, CLAUDE) is None


def test_a_ruling_in_the_run_worktree_unlocks_it_too(tmp_path, monkeypatch):
    _, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, wt, _ruling(wt))
    assert guard.check(wt, SEAT) is None


def test_a_seat_scope_growth_ruling_minted_the_seat_way_unlocks_it(
        tmp_path, monkeypatch, capsys):
    base, wt = _setup(tmp_path)
    rid = _mint_seat_ruling(base, tmp_path, monkeypatch, capsys)
    front = ruling_file.parse(ruling_file.find(base, rid))["front"]
    assert (front["kind"], front["slug"], front["entry"]) == ("scope-growth", "demo", "seat")
    _merge_started(wt, "2026-01-01T00:00:00Z")  # long before the ruling's wall-clock `at`
    assert guard.check(wt, SEAT) is not None  # minted but not yet answered
    _answer(monkeypatch, base, rid)
    assert guard.check(wt, SEAT) is None


def test_a_seat_base_sync_ruling_minted_the_seat_way_unlocks_it(
        tmp_path, monkeypatch, capsys):
    base, wt = _setup(tmp_path)
    rid = _mint_seat_ruling(base, tmp_path, monkeypatch, capsys, kind="base-sync-hunk")
    _merge_started(wt, "2026-01-01T00:00:00Z")
    _answer(monkeypatch, base, rid)
    assert guard.check(wt, SEAT) is None


# --- still refused ------------------------------------------------------------------------

def test_an_unanswered_ruling_does_not_unlock_it(tmp_path):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _ruling(base)
    assert guard.check(wt, SEAT) is not None


def test_a_stop_run_answer_does_not_unlock_it(tmp_path, monkeypatch):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, base, _ruling(base), choice=ruling_cli.STOP_RUN["label"])
    assert guard.check(wt, SEAT) is not None


def test_a_decision_ruling_does_not_unlock_it(tmp_path, monkeypatch):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, base, _ruling(base, kind="decision"))
    assert guard.check(wt, SEAT) is not None


def test_another_designs_ruling_does_not_unlock_it(tmp_path, monkeypatch):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, base, _ruling(base, slug="other-design"))
    assert guard.check(wt, SEAT) is not None


def test_a_ruling_older_than_the_merge_does_not_unlock_it(tmp_path, monkeypatch):
    base, wt = _setup(tmp_path)
    _merge_started(wt, AFTER_RULING)  # an earlier merge's ruling
    _answer(monkeypatch, base, _ruling(base))
    assert guard.check(wt, SEAT) is not None


def test_a_merge_aborted_and_redone_after_the_answer_needs_a_new_ruling(
        tmp_path, monkeypatch):
    base, wt = _setup(tmp_path)
    _merge_started(wt, BEFORE_RULING)
    _answer(monkeypatch, base, _ruling(base))
    assert guard.check(wt, SEAT) is None
    _git(wt, "merge", "--abort")
    _merge(wt)
    _merge_started(wt, AFTER_RULING)
    assert guard.check(wt, SEAT) is not None
    _answer(monkeypatch, base, _ruling(base, at=AFTER_RULING, question="Which side now?"))
    assert guard.check(wt, SEAT) is None


# --- main: exit code, one stderr line, fail-open, no writes -------------------------------

def test_main_exits_1_with_one_stderr_line_on_a_refusal(tmp_path, capsys):
    _, wt = _setup(tmp_path)
    assert guard.main(["--repo", str(wt)], env=SEAT) == 1
    captured = capsys.readouterr()
    lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert lines == [guard.check(wt, SEAT)]
    assert captured.out == ""


def test_main_exits_0_silently_when_nothing_is_refused(tmp_path, capsys):
    _, wt = _setup(tmp_path)
    assert guard.main(["--repo", str(wt)], env=RUN_SEAT) == 0
    assert guard.main(["--repo", str(wt)], env={}) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


def test_main_reads_the_process_environment_by_default(tmp_path, monkeypatch):
    _, wt = _setup(tmp_path)
    monkeypatch.delenv("TP_DESIGN_RUN", raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    monkeypatch.setenv("CLAUDE_LAUNCHER_ROLE", "seat")
    assert guard.main(["--repo", str(wt)]) == 1
    monkeypatch.setenv("TP_DESIGN_RUN", "1")
    assert guard.main(["--repo", str(wt)]) == 0


def test_an_internal_error_exits_0_with_one_stderr_line(tmp_path, monkeypatch, capsys):
    _, wt = _setup(tmp_path)

    def boom(repo, env):
        raise RuntimeError("guard exploded\nwith a second line")

    monkeypatch.setattr(guard, "check", boom)
    assert guard.main(["--repo", str(wt)], env=SEAT) == 0
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("seat-commit-guard: RuntimeError")


def test_a_bad_argument_exits_0_with_one_stderr_line(capsys):
    assert guard.main(["--no-such-flag"], env=SEAT) == 0
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("seat-commit-guard:")


def _snapshot(*roots):
    return sorted((str(p), p.stat().st_mtime_ns)
                  for root in roots for p in Path(root).rglob("*") if p.is_file())


def test_the_guard_never_writes(tmp_path):
    base, wt = _setup(tmp_path)
    _git(wt, "status", "--porcelain")  # settle the index so the snapshot is stable
    before = _snapshot(base, wt)
    assert guard.main(["--repo", str(wt)], env=SEAT) == 1
    assert guard.main(["--repo", str(wt)], env=RUN_SEAT) == 0
    assert _snapshot(base, wt) == before
