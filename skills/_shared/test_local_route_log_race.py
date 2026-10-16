"""test_local_route_log_race.py — two writers on a MISSING decisions.md.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py →
"`append` CLI"; impl-audit attempt 3, seat ruling 11(b))

`_append_entry` opens with ONE `O_RDWR|O_CREAT|O_APPEND` open (no exists-check,
no create-then-write) and makes the empty-file header decision + the write
atomic under an exclusive `flock`. Which interleaving each test pins:

- the two open-hook tests run writer B right after writer A's FIRST writable
  open returns (hooking both `os.open` and `open`, whatever the writer uses).
  They pin SINGLE-OPEN versus create-then-write: a writer that creates the file
  in one open and writes in another lets B land its header in the gap. They do
  NOT pin the lock — B runs to completion before A takes it;
- the process test is a real (timing-dependent) smoke check of the whole path;
- the LOCK itself (held across the `fstat` size read AND the `os.write`) is
  pinned timing-free by the sibling test_local_route_log_lock.py.
"""
from __future__ import annotations

import builtins
import io
import os
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

HEADER = local_route_log.SCHEMA_HEADER


def _entry(tag: str) -> str:
    result = {"schema": local_route_check.SCHEMA, "state": "routed", "reason": "ok",
              "base_url": "http://127.0.0.1:8787", "checked_at": tag,
              "ollama": None, "detail": ""}
    return local_route_log.render_entry(result, "run-start", "none")


def _assert_log(decisions: Path, expected: list[str]) -> None:
    text = decisions.read_text(encoding="utf-8")
    assert text.startswith(HEADER)
    assert text.count(HEADER) == 1, text[:400]
    assert len(local_route_log.entries(text)) == len(expected)
    for entry in expected:
        assert text.count("\n" + entry + "\n") == 1, entry


# ---------------------------------------------------------------------------
# deterministic interleave: writer B runs right after writer A's open returns
# ---------------------------------------------------------------------------

def _hook_first_open(monkeypatch, decisions: Path, writer_b) -> list:
    """After the FIRST writable open of `decisions` returns (via `os.open` or
    `open`), run `writer_b` before writer A gets to write anything."""
    fired: list = []
    real_os_open, real_open = os.open, builtins.open

    def _maybe_fire(path) -> None:
        if not fired and Path(os.fsdecode(path)) == decisions:
            fired.append(True)
            writer_b()

    def hooked_os_open(path, flags, *args, **kwargs):
        fd = real_os_open(path, flags, *args, **kwargs)
        if flags & (os.O_WRONLY | os.O_RDWR):
            _maybe_fire(path)
        return fd

    def hooked_open(file, mode="r", *args, **kwargs):
        fh = real_open(file, mode, *args, **kwargs)
        if isinstance(file, (str, bytes, os.PathLike)) and any(f in mode for f in "wax+"):
            _maybe_fire(file)
        return fh

    monkeypatch.setattr(os, "open", hooked_os_open)
    monkeypatch.setattr(builtins, "open", hooked_open)
    monkeypatch.setattr(io, "open", hooked_open)
    return fired


def test_interleaved_writers_on_a_missing_file_keep_one_header_and_both_entries(
        tmp_path, monkeypatch):
    decisions = tmp_path / "decisions.md"
    entry_a, entry_b = _entry("writer-A"), _entry("writer-B-with-a-longer-tag")
    fired = _hook_first_open(
        monkeypatch, decisions, lambda: local_route_log._append_entry(decisions, entry_b))
    local_route_log._append_entry(decisions, entry_a)
    monkeypatch.undo()
    assert fired == [True], "the hook never ran writer B"
    _assert_log(decisions, [entry_b, entry_a])


def test_writer_b_first_then_a_orders_b_before_a(tmp_path, monkeypatch):
    """The header lands with whichever writer holds the lock first (B here)."""
    decisions = tmp_path / "decisions.md"
    entry_a, entry_b = _entry("A"), _entry("B")
    _hook_first_open(
        monkeypatch, decisions, lambda: local_route_log._append_entry(decisions, entry_b))
    local_route_log._append_entry(decisions, entry_a)
    monkeypatch.undo()
    body = decisions.read_text(encoding="utf-8")
    assert body == HEADER + "\n" + entry_b + "\n\n" + entry_a + "\n"


# ---------------------------------------------------------------------------
# real concurrency: several processes appending to one missing file
# ---------------------------------------------------------------------------

WRITERS, PER_WRITER = 4, 40

_WORKER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import local_route_check, local_route_log
decisions, go, writer = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
while not go.exists():
    time.sleep(0.001)
for i in range(int(sys.argv[5])):
    result = {"schema": local_route_check.SCHEMA, "state": "routed", "reason": "ok",
              "base_url": "http://127.0.0.1:8787", "checked_at": f"w{writer}-i{i}",
              "ollama": None, "detail": ""}
    local_route_log._append_entry(
        decisions, local_route_log.render_entry(result, "run-start", "none"))
"""


def test_concurrent_processes_on_a_missing_file_keep_every_entry(tmp_path):
    decisions, go = tmp_path / "decisions.md", tmp_path / "go"
    procs = [subprocess.Popen(
        [sys.executable, "-I", "-c", _WORKER, str(_SHARED), str(decisions), str(go),
         str(w), str(PER_WRITER)], stderr=subprocess.PIPE, text=True)
        for w in range(WRITERS)]
    go.touch()  # release every writer at once
    errors = [proc.communicate(timeout=60)[1] for proc in procs]
    assert [proc.returncode for proc in procs] == [0] * WRITERS, errors
    expected = [_entry(f"w{w}-i{i}") for w in range(WRITERS) for i in range(PER_WRITER)]
    _assert_log(decisions, expected)
