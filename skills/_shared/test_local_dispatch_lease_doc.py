"""Doc guard: `local-dispatch.md` §3 "Local rung" steps 1-2 on the task path.

design: cheap-tier-local-routing (Task 6.2; detailed-design.md §Data Flow 3a). A `--local`
dispatcher executes this prose literally, so the guard pins the literals the design names, each
assert scoped to its own list item of §3 (never a whole-file substring another section could
satisfy), and checks every command's flags against the script's own `--help` and its documented
exit and output shape against the real CLI. Slicing is by heading and list marker, never by line
number (`skills/_shared/test-fragility.md`).
"""
from __future__ import annotations

import contextlib
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import local_lease  # noqa: E402

DOC = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
TWO_LEVELS = ("\n1. **Orphan check**", "\n2. **Slot check**", "\n3. Right after")
SPAN_RE = re.compile(r"`([^`]+)`")
FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
SCRIPT_RE = re.compile(r"(attempt_watchdog|local_lease|tier_ladder)\.py(?:\s+([a-z][a-z-]*))?")


def _section3() -> str:
    start = DOC.index("\n## 3.")
    return DOC[start:DOC.index("\n## 4.", start)]


def _local_rung() -> str:
    sec = _section3()
    return sec[sec.index("**Local rung"):]


def _step(n: int) -> str:
    """The text of §3 "Local rung" list item `n` (1 or 2), up to the next item."""
    rung = _local_rung()
    start = rung.index(TWO_LEVELS[n - 1])
    return rung[start:rung.index(TWO_LEVELS[n], start + 1)]


def _flat(text: str) -> str:
    """Whitespace collapsed, backticks dropped: a phrase check ignores markdown code spans."""
    return " ".join(text.replace("`", "").split())


def test_step1_scans_both_orphan_dirs_before_the_gpu_verdict():
    step = _flat(_step(1))
    task = step.index("orphans --dir <L> --phase <N>")
    cheap = step.index("orphans --dir .tp-scratch/cheap-watch --phase cheap")
    verdict = step.index("holds_gpu")
    assert task < verdict and cheap < verdict
    assert "orphan-holds-gpu" in step[verdict:]


def test_step2_acquires_with_the_design_slug_and_a_long_bash_timeout():
    step = _flat(_step(2))
    assert "local_lease.py acquire --design <slug>" in step
    assert "timeout 300000" in step


@pytest.mark.parametrize("state,reason", [("busy", "local-busy"),
                                          ("busy-measure", "local-busy-measure")])
def test_step2_maps_each_busy_state_to_its_reason(state, reason):
    step = _flat(_step(2))
    at = re.search(rf"lease: {state}(?![-\w])", step)
    assert at, state
    after = re.search(r"--reason (\S+?)[;,.)]*(?:\s|$)", step[at.end():])
    assert after and after.group(1) == reason


def test_step2_passes_the_waited_seconds_to_every_following_next():
    step = _flat(_step(2))
    assert "waited=<s>" in step
    spans = [s for s in SPAN_RE.findall(_step(2)) if "tier_ladder.py next" in s or "--lease-wait-s" in s]
    assert any("--lease-wait-s <waited>" in " ".join(s.split()) for s in spans), spans


def test_the_local_rung_keeps_its_other_steps():
    rung = _local_rung()
    for needle in ("background-spawn-failed", "attempt_watchdog.py arm", "On `runaway`"):
        assert needle in rung, needle


def _help(script: str, sub: str | None) -> str:
    argv = [sys.executable, str(HERE / f"{script}.py")] + ([sub] if sub else []) + ["--help"]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, (argv, proc.stderr)
    return proc.stdout


def test_every_flag_in_steps_1_and_2_is_one_the_cli_accepts():
    seen: set[tuple[str, str | None]] = set()
    for step in (_step(1), _step(2)):
        for span in SPAN_RE.findall(step):
            span = " ".join(span.split())
            hit = SCRIPT_RE.search(span)
            if not hit or not FLAG_RE.search(span):
                continue
            script, sub = hit.groups()
            help_text = _help(script, sub)
            for flag in FLAG_RE.findall(span):
                assert flag in help_text, (script, sub, flag)
            seen.add((script, sub))
    assert {("attempt_watchdog", "orphans"), ("local_lease", "acquire"),
            ("tier_ladder", "next")} <= seen, seen


@pytest.mark.parametrize("state", ["busy", "busy-measure"])
def test_the_real_cli_exits_3_on_either_busy_state_and_prints_waited(state, monkeypatch):
    monkeypatch.setattr(local_lease, "acquire_timed", lambda *a, **k: (state, "held", 240.0))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = local_lease.main(["acquire", "--design", "demo"])
    assert code == 3
    assert out.getvalue().strip() == f"lease: {state} (held) waited=240"
