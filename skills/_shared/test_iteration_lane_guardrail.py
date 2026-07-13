"""test_iteration_lane_guardrail.py — B1 load-bearing guardrail (design: fast-lane-worker-wiring).

The fast (iteration) lane can NEVER mint a merge-gate stamp; the full (gate) lane is a
strictly different command that always carries the stamp write. This is verified against
the LIVE shipped `scripts/ci-local.sh` (not a fixture) plus the real seam.

DELIBERATE SUPERSESSION of design B1(a)'s "hermetic-execution round-trip" phrasing:
this test SCANS the shipped script's `--fast` region for any stamp write instead of
executing `--fast` once and re-reading `read_stamp`. Scanning the source is strictly
STRONGER than a happy-path run — it catches a *conditionally-gated* stamp write (one
behind an `if` a single execution would skip) without recursively running the whole
suite from inside a test. The full-lane region is scanned for exactly the stamp step so
"the stamp lives only on the gate lane" is pinned from both sides.

MUTATION-VERIFIED (non-vacuity). `_fast_region_is_stampless` was run against a /tmp copy
of ci-local.sh with `python3 skills/_shared/ci_local_stamp.py --write` injected INSIDE the
`--fast` block (before its `exit 0`): the helper returned False and
`test_fast_region_never_writes_stamp` REDDED — proving the scan is not vacuously green.
The full-region `== 1` count and the `iteration != gate` command assertion were likewise
confirmed to red when the stamp step is removed from the gate lane / the fast command is
aliased to the gate command, respectively.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from iteration_lane import gate_command, iteration_command

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_LOCAL = REPO_ROOT / "scripts" / "ci-local.sh"
ITERATION_LANE_PY = REPO_ROOT / "skills" / "_shared" / "iteration_lane.py"

_FAST_GUARD_MARKER = '"${1:-}" = "--fast"'
_STAMP_STEP = "ci_local_stamp.py --write"


# --- region split of the live ci-local.sh (mutation-verifiable helpers) ------

def _split_fast_full(content: str) -> tuple[str, str]:
    """Return (fast_region, full_region) of ci-local.sh.

    fast_region: from the `[ "${1:-}" = "--fast" ]` guard line through the fast
                 branch's own `exit 0` (inclusive).
    full_region: everything AFTER that `exit 0` (the default/gate lane).
    """
    lines = content.splitlines()
    starts = [i for i, ln in enumerate(lines) if _FAST_GUARD_MARKER in ln]
    assert starts, "ci-local.sh has no `${1:-} = --fast` guard line"
    start = starts[0]
    ends = [i for i in range(start, len(lines)) if lines[i].strip() == "exit 0"]
    assert ends, "the --fast block has no `exit 0`"
    end = ends[0]
    fast_region = "\n".join(lines[start:end + 1])
    full_region = "\n".join(lines[end + 1:])
    # Non-truncation guard (defense-in-depth): the fast lane runs framework-check
    # immediately before its `exit 0`. If a future refactor adds an EARLIER `exit 0`
    # inside the --fast block, `ends[0]` would truncate fast_region before that tail
    # and the stampless scan could go vacuously green over a stamp write hidden in
    # the (mis-attributed) remainder. Require the characteristic fast-lane content in
    # the captured region so a mis-split reds this suite instead of passing silently.
    assert "framework-check" in fast_region, (
        "fast region appears truncated (no framework-check) — an early `exit 0` in the "
        "--fast block mis-split the region; the stampless scan must not run vacuously"
    )
    return fast_region, full_region


def _fast_region_is_stampless(content: str) -> bool:
    """Predicate reused by the mutation check: True iff the fast region writes no stamp."""
    fast_region, _ = _split_fast_full(content)
    return "ci_local_stamp" not in fast_region and "--write" not in fast_region


# --- (a) the fast region never writes a stamp --------------------------------

def test_fast_region_never_writes_stamp():
    content = CI_LOCAL.read_text(encoding="utf-8")
    assert _fast_region_is_stampless(content), (
        "the `--fast` region of ci-local.sh must contain NO ci_local_stamp / --write "
        "invocation — the iteration lane can never mint a merge-gate stamp (B1)"
    )


def test_full_region_has_exactly_the_stamp_step():
    content = CI_LOCAL.read_text(encoding="utf-8")
    _, full_region = _split_fast_full(content)
    assert full_region.count(_STAMP_STEP) == 1, (
        "the default/gate lane must carry EXACTLY the ci_local_stamp.py --write step "
        "(the sole stamp source lives after the fast branch's exit 0)"
    )


# --- (b) the seam pins the stamp boundary ------------------------------------

def test_iteration_lane_never_writes_stamp_either_granularity():
    for gran in ("task", "phase"):
        r = iteration_command(REPO_ROOT, granularity=gran)
        assert r.writes_stamp is False, f"iteration lane ({gran}) must never write a stamp"


def test_gate_lane_writes_stamp_in_dev_repo():
    assert gate_command(REPO_ROOT).writes_stamp is True, (
        "the gate lane in the dev repo is the full stamp-writing ci-local.sh"
    )


def test_iteration_and_gate_commands_are_never_the_same():
    it = iteration_command(REPO_ROOT, granularity="phase").command
    gate = gate_command(REPO_ROOT).command
    assert it is not None and gate is not None
    assert it != gate, (
        "the iteration command and the gate command must be provably different — the "
        "fast lane can never stand in for the full stamp-writing run (B1)"
    )


# --- consumer-repo cwd guard (closes the plugin false-probe risk) ------------

def _git(repo: Path, *args) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_cli_from_consumer_cwd_never_probes_plugin_ci_local(tmp_path):
    """Run the CLI with cwd INSIDE a hermetic temp git repo that ships NO
    scripts/ci-local.sh. If the seam were `__file__`-anchored it would emit the
    plugin's own ci-local.sh --fast and exit 0; because it is cwd-anchored via
    find_project_root, fast_lane_available is False for that cwd and the CLI exits
    non-zero with an EMPTY stdout (never a green no-op a tee-pipe would swallow)."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("consumer repo, no scripts/ci-local.sh\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")

    from iteration_lane import fast_lane_available
    assert fast_lane_available(repo) is False

    proc = subprocess.run(
        [sys.executable, str(ITERATION_LANE_PY),
         "--lane", "iteration", "--granularity", "phase"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    assert proc.returncode != 0, (
        "an unresolvable lane in a consumer repo must exit non-zero — the plugin's own "
        "ci-local.sh must never be probed for the target repo"
    )
    assert proc.stdout == "", "must print NOTHING to stdout on an unresolvable lane"
