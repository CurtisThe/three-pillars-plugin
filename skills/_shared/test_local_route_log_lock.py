"""test_local_route_log_lock.py — the exclusive `flock` is HELD across the
size read AND the write.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py →
"`append` CLI"; impl-audit attempt 3 LOW finding, seat ruling 13 item 1)

`_append_entry` decides "empty file -> write the schema header" from
`os.fstat(fd).st_size` and then issues ONE `os.write`. That decision is only
race-free if the exclusive lock is held from before the size read until after
the write; otherwise two writers on a missing decisions.md can both see size 0
and both write a header. This test is timing-free: it hooks `os.fstat` and
`os.write` for writer A's decisions fd and, at each of those two moments,
probes with a SECOND open file description whether a non-blocking exclusive
`flock` is refused (`BlockingIOError`). `flock` locks conflict across open file
descriptions even inside one process, so the probe sees A's lock iff A holds
it. Red for: no lock at all; a lock taken only after the `fstat`; a lock
released before the `write`.
"""
from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402


def _entry(tag: str) -> str:
    result = {"schema": local_route_check.SCHEMA, "state": "routed", "reason": "ok",
              "base_url": "http://127.0.0.1:8787", "checked_at": tag,
              "ollama": None, "detail": ""}
    return local_route_log.render_entry(result, "run-start", "none")


def _install_lock_probes(monkeypatch, decisions: Path) -> dict:
    """Hook `os.open` (to learn writer A's decisions fd), then `os.fstat` and
    `os.write` on THAT fd: each fires ONCE and records whether a second open
    file description was refused a non-blocking exclusive lock."""
    real_os_open, real_fstat, real_write = os.open, os.fstat, os.write
    state: dict = {"fd": None, "fstat": None, "write": None}

    def probe() -> bool:
        fd2 = real_os_open(decisions, os.O_RDWR)
        try:
            fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True  # A holds the exclusive lock
        finally:
            os.close(fd2)  # also drops fd2's lock if the probe took it
        return False

    def hooked_open(path, flags, *args, **kwargs):
        fd = real_os_open(path, flags, *args, **kwargs)
        if state["fd"] is None and Path(os.fsdecode(path)) == decisions:
            state["fd"] = fd
        return fd

    def hooked_fstat(fd, *args, **kwargs):
        if state["fstat"] is None and fd == state["fd"]:
            state["fstat"] = probe()
        return real_fstat(fd, *args, **kwargs)

    def hooked_write(fd, data):
        if state["write"] is None and fd == state["fd"]:
            state["write"] = probe()
        return real_write(fd, data)

    monkeypatch.setattr(os, "open", hooked_open)
    monkeypatch.setattr(os, "fstat", hooked_fstat)
    monkeypatch.setattr(os, "write", hooked_write)
    return state


def _append_and_probe(tmp_path, monkeypatch, existing: str | None) -> dict:
    decisions = tmp_path / "decisions.md"
    if existing is not None:
        decisions.write_text(existing, encoding="utf-8")
    state = _install_lock_probes(monkeypatch, decisions)
    local_route_log._append_entry(decisions, _entry("writer-A"))
    monkeypatch.undo()
    assert state["fd"] is not None, "writer A never os.open()ed decisions.md"
    return state


def test_lock_is_held_across_the_size_read_and_the_write_on_a_missing_file(
        tmp_path, monkeypatch):
    """The racing-writers case: a MISSING decisions.md (header decision)."""
    state = _append_and_probe(tmp_path, monkeypatch, existing=None)
    assert state["fstat"] is True, "no exclusive flock held at the os.fstat size read"
    assert state["write"] is True, "no exclusive flock held at the os.write"
    text = (tmp_path / "decisions.md").read_text(encoding="utf-8")
    assert text.count(local_route_log.SCHEMA_HEADER) == 1


def test_lock_is_held_across_the_size_read_and_the_write_on_an_existing_file(
        tmp_path, monkeypatch):
    """Same property when the file exists (the trailing-newline decision)."""
    existing = local_route_log.SCHEMA_HEADER + "\n" + _entry("earlier")  # no final \n
    state = _append_and_probe(tmp_path, monkeypatch, existing=existing)
    assert state["fstat"] is True, "no exclusive flock held at the os.fstat size read"
    assert state["write"] is True, "no exclusive flock held at the os.write"
