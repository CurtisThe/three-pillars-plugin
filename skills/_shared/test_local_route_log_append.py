"""test_local_route_log_append.py — `_append_entry` is a TRUE append.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py →
"`append` CLI": a non-null entry is "appended byte-for-byte")

The writer never reads-modify-rewrites decisions.md: ONE
`O_RDWR|O_CREAT|O_APPEND` open (never `O_TRUNC`), the schema header only when
the file is empty, and each entry is ONE write call — so a failed, partial or
short write can never truncate the prior log: the prior bytes survive and
`append` reports the error. The spy counts both write seams — `os.write` on a
writable `os.open` fd, and every writable `open` handle (so a rewrite through
`open`/`Path.write_text` is caught too).
"""
from __future__ import annotations

import builtins
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

CLI = _SHARED / "local_route_log.py"
HEADER = local_route_log.SCHEMA_HEADER.encode("utf-8")
CHECKED_AT = "2026-09-27T21:04:11Z"
_REAL_OPEN = builtins.open


def _entry() -> str:
    result = {"schema": local_route_check.SCHEMA, "state": "routed", "reason": "ok",
              "base_url": "http://127.0.0.1:8787", "checked_at": CHECKED_AT,
              "ollama": None, "detail": ""}
    return local_route_log.render_entry(result, "run-start", "none")


def _check_stdin(entry: str) -> str:
    result = local_route_check.decide({}, None, checked_at=CHECKED_AT)
    return json.dumps({**result, "transition": {"from": "none", "entry": entry}})


class _Spy:
    """Wrap a real file object; count (or fail) `write` calls."""

    def __init__(self, fh, log: list, fail: bool, partial: bool):
        self._fh, self._log, self._fail, self._partial = fh, log, fail, partial

    def write(self, data):
        self._log.append(data)
        if self._fail:
            if self._partial:  # some bytes land, then the device fills up
                self._fh.write(data[: len(data) // 2])
                self._fh.flush()
            raise OSError(27, "File too large")
        return self._fh.write(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._fh.close()
        return False

    def __getattr__(self, name):
        return getattr(self._fh, name)


def _install_spy(monkeypatch, *, fail: bool = False, partial: bool = False,
                 short: bool = False) -> list:
    """Spy both write seams. `os.open` records its flags and every writable
    fd; `os.write` on such an fd is logged (and failed: `partial` lands half
    the bytes first; `short` lands half and returns the short count). `open`
    (builtins and `io`) wraps every writable handle in `_Spy`."""
    writes: list = []
    fds: set = set()
    real_os_open, real_os_write, real_os_close = os.open, os.write, os.close

    def spy_os_open(path, flags, *args, **kwargs):
        assert not flags & os.O_TRUNC, "a truncating open is a rewrite"
        fd = real_os_open(path, flags, *args, **kwargs)
        if flags & (os.O_WRONLY | os.O_RDWR):
            fds.add(fd)
        return fd

    def spy_os_write(fd, data):
        if fd not in fds:
            return real_os_write(fd, data)
        writes.append(bytes(data))
        if short:
            return real_os_write(fd, data[: len(data) // 2])
        if fail:
            if partial:
                real_os_write(fd, data[: len(data) // 2])
            raise OSError(27, "File too large")
        return real_os_write(fd, data)

    def spy_os_close(fd):
        fds.discard(fd)
        return real_os_close(fd)

    def spy_open(file, mode="r", *args, **kwargs):
        fh = _REAL_OPEN(file, mode, *args, **kwargs)
        if any(flag in mode for flag in "wax+"):
            return _Spy(fh, writes, fail or short, partial or short)
        return fh

    monkeypatch.setattr(os, "open", spy_os_open)
    monkeypatch.setattr(os, "write", spy_os_write)
    monkeypatch.setattr(os, "close", spy_os_close)
    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_open)
    return writes


# ---------------------------------------------------------------------------
# byte output unchanged, one write call per entry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prior, prefix", [
    (None, HEADER + b"\n"),                   # missing -> header
    (b"", HEADER + b"\n"),                    # existing but empty -> header
    (b"earlier\n", b"earlier\n\n"),           # trailing newline -> blank line
    (b"earlier", b"earlier\n\n"),             # no trailing newline -> fix-up
])
def test_append_bytes_and_exactly_one_write(tmp_path, monkeypatch, prior, prefix):
    decisions = tmp_path / "decisions.md"
    if prior is not None:
        decisions.write_bytes(prior)
    entry = _entry()
    writes = _install_spy(monkeypatch)
    local_route_log._append_entry(decisions, entry)
    monkeypatch.undo()
    assert decisions.read_bytes() == prefix + entry.encode("utf-8") + b"\n"
    assert len(writes) == 1, writes


def test_two_appends_are_two_writes_and_keep_the_first(tmp_path, monkeypatch):
    decisions = tmp_path / "decisions.md"
    entry = _entry()
    writes = _install_spy(monkeypatch)
    local_route_log._append_entry(decisions, entry)
    local_route_log._append_entry(decisions, entry)
    monkeypatch.undo()
    body = entry.encode("utf-8")
    assert decisions.read_bytes() == HEADER + b"\n" + body + b"\n\n" + body + b"\n"
    assert len(writes) == 2


def test_append_entry_is_a_thin_wrapper_around_append_entry_impl(tmp_path, monkeypatch):
    """The public `append_entry` (run-throughput Task 4.1) does exactly what
    `_append_entry` does — same bytes, same one write."""
    decisions = tmp_path / "decisions.md"
    entry = _entry()
    writes = _install_spy(monkeypatch)
    local_route_log.append_entry(decisions, entry)
    monkeypatch.undo()
    assert decisions.read_bytes() == HEADER + b"\n" + entry.encode("utf-8") + b"\n"
    assert len(writes) == 1


def test_append_never_creates_parent_dirs(tmp_path):
    decisions = tmp_path / "missing-dir" / "decisions.md"
    with pytest.raises(OSError):
        local_route_log._append_entry(decisions, _entry())
    assert not decisions.parent.exists()


def test_unencodable_entry_never_creates_the_file(tmp_path):
    decisions = tmp_path / "decisions.md"
    with pytest.raises(UnicodeError):
        local_route_log._append_entry(decisions, _entry() + "\n\udcff")
    assert not decisions.exists()


# ---------------------------------------------------------------------------
# a failed write never destroys the prior log
# ---------------------------------------------------------------------------

def _prior_log() -> bytes:
    return HEADER + b"\n" + (b"### [decision] earlier entry\n" * 300)


@pytest.mark.parametrize("partial, short", [(False, False), (True, False), (False, True)])
def test_failed_write_keeps_prior_bytes_and_append_reports(tmp_path, monkeypatch,
                                                           partial, short):
    """`short`: the one write returns a short count — a failed write, never a
    second write call."""
    decisions = tmp_path / "decisions.md"
    prior = _prior_log()
    decisions.write_bytes(prior)
    entry = _entry()
    writes = _install_spy(monkeypatch, fail=not short, partial=partial, short=short)
    result = local_route_log._handle_append(decisions, _check_stdin(entry))
    monkeypatch.undo()
    data = decisions.read_bytes()
    if partial or short:
        assert data.startswith(prior) and len(data) > len(prior)
    else:
        assert data == prior
    assert result["appended"] is False
    assert result["error"] is not None and result["error"].startswith("append failed:")
    assert len(writes) == 1


def test_failed_write_propagates_oserror_from_append_entry(tmp_path, monkeypatch):
    decisions = tmp_path / "decisions.md"
    prior = _prior_log()
    decisions.write_bytes(prior)
    _install_spy(monkeypatch, fail=True)
    with pytest.raises(OSError):
        local_route_log._append_entry(decisions, _entry())
    monkeypatch.undo()
    assert decisions.read_bytes() == prior


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_FSIZE/SIGXFSZ semantics are Linux-pinned")
def test_rlimit_fsize_cli_keeps_prior_log(tmp_path):
    """The audit's repro: a file-size limit below the prior log's size. A
    rewrite would truncate the log to the limit; a true append fails EFBIG
    before touching a single prior byte."""
    import resource
    import signal

    decisions = tmp_path / "decisions.md"
    prior = _prior_log()
    assert len(prior) > 4096
    decisions.write_bytes(prior)

    def _limit():
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (4096, 4096))

    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "append", "--decisions", str(decisions)],
        input=_check_stdin(_entry()) + "\n", capture_output=True, text=True,
        timeout=30, env=env, preexec_fn=_limit,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["appended"] is False and out["error"].startswith("append failed:")
    assert decisions.read_bytes() == prior
