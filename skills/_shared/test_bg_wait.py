"""test_bg_wait.py — one bounded wait on a background command (Behavior 2).

design: prompt-cache-aware-dispatch (Task 1.1)

The caller starts a background command as
`mkdir -p .tp-scratch/bg && { <cmd>; } > <M>.out 2> <M>.err; echo $? > <M>` and
then asks `bg_wait` whether it is finished (stderr in its own file so `<M>.out`
stays parseable). Every wait is bounded by `wait_budget.WAIT_BUDGET_S` so it lands
inside the 300 s prompt cache. The clock and the sleep are injected seams: the
fake sleep advances the fake clock and records every call, so the budget is
asserted as slept time rather than wall clock — except the CLI test, which is
the one place the real timers run and is bounded only by the subprocess timeout.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import bg_wait
import wait_budget


class FakeClock:
    """A monotonic clock advanced only by the injected sleep seam."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    @property
    def total(self) -> float:
        return sum(self.slept)


def test_done_marker_prints_exit(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    marker.write_text("3\n")
    (tmp_path / "M.out").write_text("hi\n")
    fake = FakeClock()

    assert bg_wait.wait(marker, clock=fake.clock, sleep=fake.sleep) == ("done 3", 0)
    assert fake.slept == []


def test_running_returns_inside_the_budget(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    (tmp_path / "M.out").write_text("still going\n")
    fake = FakeClock()

    result = bg_wait.wait(
        marker,
        for_s=270,
        interval_s=5,
        clock=fake.clock,
        sleep=fake.sleep,
    )

    assert result == ("running", 0)
    assert fake.total <= 270


def test_for_is_clamped_to_the_budget(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    (tmp_path / "M.out").write_text("still going\n")
    fake = FakeClock()

    bg_wait.wait(marker, for_s=999, interval_s=5, clock=fake.clock, sleep=fake.sleep)

    assert fake.total <= wait_budget.WAIT_BUDGET_S


def test_marker_written_mid_wait_is_done(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    (tmp_path / "M.out").write_text("working\n")
    fake = FakeClock()
    calls = {"n": 0}

    def sleep_on_second_call(seconds: float) -> None:
        fake.sleep(seconds)
        calls["n"] += 1
        if calls["n"] == 2:
            marker.write_text("0\n")

    assert bg_wait.wait(
        marker, for_s=270, interval_s=5, clock=fake.clock, sleep=sleep_on_second_call
    ) == ("done 0", 0)


def test_empty_marker_reads_running(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    marker.write_text("")
    (tmp_path / "M.out").write_text("partial\n")
    fake = FakeClock()

    assert bg_wait.wait(marker, for_s=0, clock=fake.clock, sleep=fake.sleep) == (
        "running",
        0,
    )


def test_missing_marker_and_output_is_an_error(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    fake = FakeClock()

    line, exit_code = bg_wait.wait(marker, clock=fake.clock, sleep=fake.sleep)

    assert line.startswith("error: no marker or output")
    assert exit_code == 2
    assert fake.slept == []


def test_unreadable_marker_is_an_error(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    marker.write_text("abc")
    (tmp_path / "M.out").write_text("done badly\n")
    fake = FakeClock()

    line, exit_code = bg_wait.wait(marker, for_s=0, clock=fake.clock, sleep=fake.sleep)

    assert line.startswith("error:")
    assert exit_code == 2


def test_cli_prints_one_line(tmp_path: Path) -> None:
    marker = tmp_path / "M"
    (tmp_path / "M.out").write_text("running still\n")
    script = Path(__file__).resolve().parent / "bg_wait.py"

    proc = subprocess.run(
        [sys.executable, str(script), "--marker", str(marker), "--for", "1"],
        capture_output=True,
        text=True,
        timeout=100,
    )

    assert proc.stdout == "running\n"
    assert proc.returncode == 0
