"""test_bg_wait_marker.py — a reused marker never answers with the previous run's exit.

design: prompt-cache-aware-dispatch (PR #298 review, round 1)

The start form lives in the `bg_wait.py` module docstring, the behaviour source the
worker and Slot 7 copy. This test takes that line, fills in a real `<M>` and a short
`<cmd>`, and runs it twice with the same marker name. The second command blocks on a
FIFO, so the test knows it is running (its shell is already past the start form's
setup) before it asks `bg_wait`. While it runs, `bg_wait` must say `running`, not the
first run's `done 1`; once it ends, `done 0`.
"""
from __future__ import annotations

import errno
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import bg_wait

SCRIPT = Path(__file__).resolve().parent / "bg_wait.py"
MARKER = ".tp-scratch/bg/suite"


def _start_form() -> str:
    lines = [ln.strip() for ln in (bg_wait.__doc__ or "").splitlines()
             if "echo $? > <M>" in ln]
    assert len(lines) == 1, lines
    return lines[0]


def _start(cwd: Path, cmd: str) -> subprocess.Popen:
    line = _start_form().replace("<cmd>", cmd).replace("<M>", MARKER)
    return subprocess.Popen(["bash", "-c", line], cwd=cwd)


def _bg_wait(cwd: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--marker", MARKER, "--for", "0"],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _open_writer(fifo: Path, deadline_s: float = 30.0) -> int:
    """Open the FIFO for writing once the second command has it open for reading."""
    end = time.monotonic() + deadline_s
    while True:
        try:
            return os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno != errno.ENXIO or time.monotonic() > end:
                raise
            time.sleep(0.05)


def test_a_reused_marker_reports_running_then_the_new_exit(tmp_path: Path) -> None:
    assert _start(tmp_path, "false").wait(timeout=30) == 0
    assert (tmp_path / MARKER).read_text(encoding="utf-8").strip() == "1"  # run 1 left its marker

    fifo = tmp_path / "gate"
    os.mkfifo(fifo)
    # `timeout` bounds the reader, so a failed open below never leaves it blocked.
    second = _start(tmp_path, f"timeout 30 cat {shlex.quote(str(fifo))} > /dev/null")
    fd = None
    try:
        fd = _open_writer(fifo)
        assert _bg_wait(tmp_path) == "running"
    finally:
        if fd is not None:
            os.close(fd)  # EOF: the second command ends with exit 0
        second.wait(timeout=60)

    assert _bg_wait(tmp_path) == "done 0"
