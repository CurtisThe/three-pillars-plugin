"""test_stop_question_hook.py — the Stop hook routes a prose question once.

design: seat-escalate-first 3.2 (B7 B10 B13) — a gated session (a run past `design`, or the
seat, on the project root) whose turn ends on a prose question gets ONE `block` naming the
route; nothing under `stop_hook_active`, for a non-question, an allow-tagged message, an
ungated session, a `claude -p` child (its env carries `TP_CHILD_SESSION=1`), or on error.
Every fixture is a tmp git repo with an explicit env; no network. Oracle: example.
test-fragility.md: assertions go through the decision, the route the reason names and the
absence of what it must not teach, never a full-sentence pin.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import escalate_first_hook  # noqa: E402
import seat_scope  # noqa: E402
import stop_question_hook as hook  # noqa: E402

HOOK = _SHARED / "stop_question_hook.py"
SEAT = {"CLAUDE_LAUNCHER_ROLE": "seat"}
RUN = {"TP_DESIGN_RUN": "1"}
Q = "Two ways forward.\nWhich option?\n1. Rebase\n2. Merge\n"
Q_DEMO = "Two ways forward.\nWhich option?\n1. Rebase demo\n2. Merge\n"
DOC = "skills/_shared/escalation.md"


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if k not in escalate_first_hook._REPO_ENV}
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=fixture@test",
                    "-c", "user.name=fixture", *args],
                   check=True, capture_output=True, env=env)


def _base(tmp_path):
    """A tmp git repo on `main` with one commit: the seat's base checkout."""
    base = tmp_path / "base"
    base.mkdir()
    _git(base, "init", "-b", "main", "-q")
    (base / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(base, "add", "-A")
    _git(base, "commit", "-q", "-m", "fixture: base")
    return base


def _worktree(tmp_path, base, *, owner="orchestrator:x@y", phase="plan"):
    """`git worktree add -b tp/demo` beside the base, carrying the design lock."""
    wt = tmp_path / "wt-demo"
    _git(base, "worktree", "add", "-q", "-b", "tp/demo", str(wt))
    lock_dir = wt / "three-pillars-docs" / "tp-designs" / "demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(
        json.dumps({"owner": owner, "phase": phase}), encoding="utf-8")
    return wt


def _payload(cwd, text=Q, **over):
    payload = {"hook_event_name": "Stop", "cwd": str(cwd), "stop_hook_active": False,
               "last_assistant_message": text}
    payload.update(over)
    return payload


def _stop(cwd, env, text=Q, **over):
    return hook.run(_payload(cwd, text, **over), env=env)


def _reason(out):
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert set(decision) == {"decision", "reason"}
    return decision["reason"]


def _transcript(tmp_path, *lines):
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


def _assistant(*texts):
    return {"type": "assistant",
            "message": {"content": [{"type": "text", "text": t} for t in texts]}}


# --- (a) the seat: one block naming /tp-escalate -----------------------------------------

@pytest.mark.parametrize("where", ["base", "worktree"])
def test_a_seat_prose_question_is_blocked_naming_tp_escalate(tmp_path, where):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    out, rc = _stop(base if where == "base" else wt, SEAT, Q_DEMO)
    assert rc == 0
    reason = _reason(out)
    for part in ("/tp-escalate", "<slug|seat>", "--question", "base checkout"):
        assert part in reason
    assert "seat-allow" not in reason  # an untagged message is never taught the tag (B10)
    assert "Which option?" in reason   # the question summary is echoed back


def test_a_seat_in_the_base_with_a_live_run_is_gated_without_the_role(tmp_path):
    base = _base(tmp_path)
    _worktree(tmp_path, base)
    out, rc = _stop(base, {}, Q_DEMO)
    assert rc == 0
    assert "/tp-escalate" in _reason(out)


# --- (b) a run past design: one block naming escalation.md --------------------------------

def test_a_run_prose_question_is_blocked_naming_the_run_route(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path))
    out, rc = _stop(wt, RUN)
    assert rc == 0
    assert DOC in _reason(out)


def test_a_run_in_design_phase_is_not_gated(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path), phase="design")
    assert _stop(wt, RUN) == ("", 0)  # B13
    assert _stop(wt, {**RUN, **SEAT}) == ("", 0)


def test_a_human_owned_run_is_not_gated(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path), owner="curtis@example.com")
    assert _stop(wt, RUN) == ("", 0)


def test_a_claude_p_child_is_never_gated(tmp_path):
    base = _base(tmp_path)
    wt = _worktree(tmp_path, base)
    child = {"TP_CHILD_SESSION": "1"}
    assert _stop(wt, {**RUN, **child}) == ("", 0)
    assert _stop(base, {**SEAT, **child}) == ("", 0)


# --- (c)(d) the one-shot and the message gates --------------------------------------------

def test_stop_hook_active_never_blocks_twice(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path))
    assert _stop(wt, RUN, stop_hook_active=True) == ("", 0)


def test_a_non_question_is_allowed(tmp_path):
    base = _base(tmp_path)
    assert _stop(base, SEAT, "Done. Tests pass.") == ("", 0)
    assert _stop(base, SEAT, None) == ("", 0)
    assert _stop(base, SEAT, "") == ("", 0)


def test_an_allow_tagged_message_is_not_blocked(tmp_path):
    base = _base(tmp_path)
    assert _stop(base, SEAT, Q + "\nseat-allow: promote-confirm") == ("", 0)


def test_an_unknown_allow_kind_is_told_so_without_listing_the_kinds(tmp_path):
    base = _base(tmp_path)
    out, rc = _stop(base, SEAT, Q + "\nseat-allow: bogus")
    assert rc == 0
    reason = _reason(out)
    assert "bogus" in reason and "not an allowed kind" in reason
    assert not any(kind in reason for kind in seat_scope.ALLOW_KINDS)  # B7


# --- (e) ungated sessions ----------------------------------------------------------------

def test_an_ungated_session_is_allowed(tmp_path):
    base = _base(tmp_path)
    assert _stop(base, {}) == ("", 0)  # no role, no live run
    _worktree(tmp_path, base)
    assert _stop(base, {**SEAT, **RUN}) == ("", 0)  # a run is never a seat


# --- (f) where the text comes from -------------------------------------------------------

def test_the_transcript_is_read_when_the_field_is_absent(tmp_path):
    base = _base(tmp_path)
    path = _transcript(tmp_path, {"type": "user", "message": {"content": "hi"}},
                       _assistant("Earlier note."), _assistant(Q))
    payload = _payload(base, transcript_path=str(path))
    del payload["last_assistant_message"]
    out, rc = hook.run(payload, env=SEAT)
    assert rc == 0
    assert _reason(out)  # the block route depends on the live run, not on the transcript


def test_the_transcript_text_blocks_are_joined(tmp_path):
    base = _base(tmp_path)
    path = _transcript(tmp_path, _assistant("Two ways forward.\nWhich option?\n",
                                            "1. Rebase\n2. Merge\n"))
    payload = _payload(base, transcript_path=str(path))
    del payload["last_assistant_message"]
    assert "Which option?" in _reason(hook.run(payload, env=SEAT)[0])


def test_a_missing_transcript_allows(tmp_path):
    base = _base(tmp_path)
    payload = _payload(base, transcript_path=str(tmp_path / "gone.jsonl"))
    del payload["last_assistant_message"]
    assert hook.run(payload, env=SEAT)[1] == 0
    assert hook.run(payload, env=SEAT)[0] == ""


def test_the_message_field_wins_over_the_transcript(tmp_path):
    base = _base(tmp_path)
    path = _transcript(tmp_path, _assistant(Q))
    assert _stop(base, SEAT, "Done.", transcript_path=str(path)) == ("", 0)


# --- (g) the project root, not the cwd ---------------------------------------------------

def test_a_worktree_subdirectory_resolves_to_the_worktree(tmp_path):
    wt = _worktree(tmp_path, _base(tmp_path))
    sub = wt / "skills" / "_shared"
    sub.mkdir(parents=True)
    out, rc = _stop(sub, RUN)
    assert rc == 0
    assert DOC in _reason(out)


# --- (h) fail-open -----------------------------------------------------------------------

def test_a_seat_scope_crash_allows_with_one_stderr_line(tmp_path, monkeypatch, capsys):
    base = _base(tmp_path)

    def boom(cwd, env):
        raise RuntimeError("seat_scope exploded")

    monkeypatch.setattr(seat_scope, "is_seat", boom)
    assert _stop(base, SEAT) == ("", 0)
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("stop-question: RuntimeError")


# --- (i) main() over stdin ---------------------------------------------------------------

def _main(stdin, env_extra):
    env = {k: v for k, v in os.environ.items()
           if k not in escalate_first_hook._REPO_ENV
           and k not in ("TP_DESIGN_RUN", "CLAUDE_LAUNCHER_ROLE", "TP_CHILD_SESSION")}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, env=env,
                          capture_output=True, text=True, timeout=30)


def test_main_prints_the_block_and_exits_zero(tmp_path):
    base = _base(tmp_path)
    proc = _main(json.dumps(_payload(base)), SEAT)
    assert proc.returncode == 0
    assert "AskUserQuestion" in _reason(proc.stdout)  # its base has no live run (B5)


def test_main_on_bad_json_exits_zero_silently():
    proc = _main("not json", SEAT)
    assert proc.returncode == 0
    assert proc.stdout == ""


# --- (j) the manifest check --------------------------------------------------------------

def _manifest(tmp_path, groups):
    path = tmp_path / "hooks.json"
    path.write_text(json.dumps({"hooks": groups}), encoding="utf-8")
    return path


def test_check_manifest_finds_a_stop_entry(tmp_path):
    stop = {"hooks": [{"type": "command", "timeout": 10, "command":
                       'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/stop_question_hook.py"'}]}
    assert hook.check_manifest(_manifest(tmp_path, {"Stop": [stop]})) == 0


def test_check_manifest_rejects_a_manifest_with_no_stop_entry(tmp_path, capsys):
    pre = {"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command":
           'python3 "${CLAUDE_PLUGIN_ROOT:-.}/skills/_shared/stop_question_hook.py"'}]}
    assert hook.check_manifest(_manifest(tmp_path, {"PreToolUse": [pre]})) == 1
    assert capsys.readouterr().err.strip() != ""
    assert hook.check_manifest(tmp_path / "missing.json") == 1


def test_main_check_manifest_flag(tmp_path):
    stop = {"hooks": [{"type": "command", "command": "python3 stop_question_hook.py"}]}
    ok = subprocess.run([sys.executable, str(HOOK), "--check-manifest",
                         str(_manifest(tmp_path, {"Stop": [stop]}))],
                        capture_output=True, text=True, timeout=30)
    assert ok.returncode == 0
    bad = subprocess.run([sys.executable, str(HOOK), "--check-manifest",
                          str(_manifest(tmp_path, {"PreToolUse": []}))],
                         capture_output=True, text=True, timeout=30)
    assert bad.returncode == 1
