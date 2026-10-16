"""test_context_rollover_handoff_land.py — the rollover against a real, gitignored handoff.

design: strata-spend-leaks (PR #277 review round 1). Two shipped defects, pinned here:

- `/tp-session-save` writes `handoff.md` gitignored and never commits it, so a driver
  that waited for a *commit* of the handoff aborted every real rollover. The save is
  landed when the file changes on disk.
- The resume line carried a literal `<slot>` placeholder, so the restored run was told
  to read a handoff path that does not exist. It now names the run's own handoff.

Real git repo and real handoff file; tmux, transcripts, clock and sleep are fakes.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import context_rollover_drive as drive  # noqa: E402

SLUG = "my-design"
HANDOFF = f"three-pillars-docs/tp-designs/{SLUG}/handoff.md"


def _git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=repo, check=True, capture_output=True, env=env)


def _assistant(size=320_000):
    return {"type": "assistant", "isSidechain": False,
            "message": {"id": "m1", "role": "assistant", "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "done"}],
                        "usage": {"input_tokens": 2_000,
                                  "cache_read_input_tokens": size - 10_000,
                                  "cache_creation_input_tokens": 8_000}}}


def _run(tmp_path, repo, *, save_writes=True, save_timeout_s=30.0):
    state = {"sid": "sess-0001", "now": 1000.0, "sent": []}
    lines = []

    def send(slug, line):
        state["sent"].append(line)
        if save_writes and line.startswith("/tp-session-save"):
            path = repo / HANDOFF  # session-save writes the gitignored file, never commits it
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# handoff\n", encoding="utf-8")
        if line == "/clear":
            state["sid"] = "sess-0002"
        return "delivered"

    def sleep(s):
        state["now"] += s

    seams = drive.real_seams(SLUG, str(repo), {"PATH": "/nonexistent"}, out=lines.append)
    seams.update(send=send, records=lambda: [_assistant()], pane=lambda: "idle",
                 session=lambda: state["sid"], clock=lambda: state["now"], sleep=sleep,
                 ledger=tmp_path / "ledger.json", tmux_blocker=None, out=lines.append)
    rc = drive.rollover(SLUG, str(repo), threshold=300_000, idle_s=1.0,
                        save_timeout_s=save_timeout_s, boundary_timeout_s=30.0, **seams)
    return rc, state["sent"], lines


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".gitignore").write_text("three-pillars-docs/tp-designs/*/handoff.md\n",
                                     encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_rollover_proceeds_after_save_writes_the_gitignored_handoff(tmp_path):
    repo = _repo(tmp_path)
    rc, sent, lines = _run(tmp_path, repo)
    assert "/clear" in sent, lines
    assert rc == 0, lines


def test_resume_line_names_the_runs_own_handoff(tmp_path):
    repo = _repo(tmp_path)
    rc, sent, lines = _run(tmp_path, repo)
    assert rc == 0, lines
    assert "<slot>" not in sent[-1]
    assert f"three-pillars-docs/tp-designs/{SLUG}/handoff.md" in sent[-1]
    assert drive.sequence(SLUG)[-1] == sent[-1]


def test_save_that_never_writes_the_handoff_still_aborts(tmp_path):
    repo = _repo(tmp_path)
    rc, sent, lines = _run(tmp_path, repo, save_writes=False, save_timeout_s=5.0)
    assert rc == 1
    assert sent == [f"/tp-session-save {SLUG}"]
    assert any(ln.startswith("rollover aborted: handoff save did not land") for ln in lines)
