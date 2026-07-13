"""test_ci_local_fast_lane.py — ci-local.sh fast/full lane wiring (design: iteration-speed).

Task 2.1 — the `--fast` inner lane:
  * detected via `${1:-}` (NOT a bare `$1`, which trips `set -u` on the no-arg default);
  * runs `python -m pytest` + `framework-check.sh` only;
  * NEVER reaches the stamp, either install smoke, or `pre-commit run --all-files`
    (it exits 0 from the fast block, so the whole default lane is unreachable).

Task 2.2 — the default (full/gate) lane:
  * main pytest pass filters `-m 'not serial'` (a future serial test is excluded from
    the parallel run, not left to flake);
  * a `-m serial -n0` single-process pass follows, exit-guarded so 0/5 pass but any
    other code (e.g. a real failure = 1) propagates and aborts before the stamp;
  * both install smokes + the stamp stay on the default lane only.

Structural scans on the script text — no subprocess, no real git.

See also test_ci_local_sh_wiring.py — the DEFAULT-lane ordering guard (stamp AFTER
pytest + AFTER test-framework-check.sh) which must stay green alongside these.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_LOCAL = REPO_ROOT / "scripts" / "ci-local.sh"


def _content() -> str:
    return CI_LOCAL.read_text(encoding="utf-8")


def _fast_block_bounds(content: str) -> tuple[int, int]:
    """Return (start, end) line indices of the `--fast` if-block: from its
    `if [ "${1:-}" ... ]` opener through its matching `fi`, tracking if/fi depth."""
    lines = content.splitlines()
    starts = [
        i for i, ln in enumerate(lines) if "--fast" in ln and "${1:-}" in ln
    ]
    assert starts, "ci-local.sh has no `${1:-}`-guarded `--fast` detection line"
    start = starts[0]
    depth = 0
    for j in range(start, len(lines)):
        stripped = lines[j].strip()
        if stripped.startswith("if ") or stripped.startswith("if["):
            depth += 1
        if stripped == "fi" or stripped.endswith("; fi") or stripped == "fi;":
            depth -= 1
            if depth == 0:
                return start, j
    raise AssertionError("unterminated --fast if-block in ci-local.sh")


def _fast_block_lines(content: str) -> list[str]:
    start, end = _fast_block_bounds(content)
    return content.splitlines()[start:end + 1]


def _default_lane_text(content: str) -> str:
    """The default/gate lane text: everything AFTER the --fast block's closing `fi`."""
    _, end = _fast_block_bounds(content)
    return "\n".join(content.splitlines()[end + 1:])


# ---------------------------------------------------------------------------
# Task 2.1: --fast inner lane
# ---------------------------------------------------------------------------

class TestFastLane:
    def test_flag_detected_via_default_expansion_not_bare_dollar_one(self):
        content = _content()
        assert '"${1:-}"' in content, (
            "--fast must be detected via ${1:-} so the no-arg default lane is safe "
            "under `set -u`"
        )
        assert '"$1"' not in content, (
            "a bare $1 reference trips `set -u` on the no-arg default lane; use ${1:-}"
        )

    def test_fast_block_runs_pytest_and_framework_check(self):
        block = "\n".join(_fast_block_lines(_content()))
        assert "python -m pytest" in block, "fast lane must run xdist pytest"
        assert "framework-check.sh" in block, "fast lane must run framework-check.sh"

    def test_fast_block_excludes_serial_from_parallel_pass(self):
        """The fast lane is the earmarked fleet inner loop; its -n auto pass must
        exclude `serial`-marked tests (design Constraint: parallel-unsafe tests are
        excluded from ANY parallel pass), with a single-process serial fallback whose
        exit code is guarded exactly like the gate lane's."""
        block = "\n".join(_fast_block_lines(_content()))
        assert "-m 'not serial'" in block, (
            "fast lane's -n auto main pass must run `-m 'not serial'` so a future "
            "serial-marked test is excluded from the parallel pass, not left to flake"
        )
        assert "-m serial -n0" in block, (
            "fast lane must run a `-m serial -n0` single-process serial fallback"
        )
        assert "[ $rc -eq 0 ] || [ $rc -eq 5 ] || exit $rc" in block, (
            "fast lane's serial fallback must guard exit code so a real failure "
            "(non-0/5) propagates and fails the lane"
        )

    def test_fast_block_skips_stamp_smokes_and_precommit(self):
        block = "\n".join(_fast_block_lines(_content()))
        assert "ci_local_stamp.py --write" not in block, (
            "fast lane must NOT write the merge-gate stamp (iteration-only)"
        )
        assert "clean-room-smoke.sh" not in block, "fast lane must skip clean-room-smoke"
        assert "plugin-parity-smoke.sh" not in block, "fast lane must skip plugin-parity-smoke"
        assert "pre-commit run" not in block, "fast lane must skip pre-commit --all-files"

    def test_fast_block_exits_before_default_lane(self):
        block = "\n".join(_fast_block_lines(_content()))
        assert "exit 0" in block, (
            "fast lane must `exit 0` from its block so the default gate lane "
            "(stamp/smokes) is never reached in --fast mode"
        )


# ---------------------------------------------------------------------------
# Task 2.2: default (full/gate) lane — parallel main pass + guarded serial fallback
# ---------------------------------------------------------------------------

class TestFullLane:
    def test_main_pytest_pass_filters_not_serial(self):
        lane = _default_lane_text(_content())
        assert "-m 'not serial'" in lane, (
            "default lane's main pytest pass must run `-m 'not serial'` so a future "
            "serial-marked test is EXCLUDED from the -n auto pass (not left to flake)"
        )

    def test_serial_fallback_pass_is_single_process(self):
        lane = _default_lane_text(_content())
        assert "-m serial -n0" in lane, (
            "default lane must run a `-m serial -n0` single-process fallback pass for "
            "any parallel-unsafe test"
        )

    def test_serial_pass_exit_code_is_guarded(self):
        lane = _default_lane_text(_content())
        # 0 = passed, 5 = pytest 'no tests matched' (no serial tests yet) → tolerate.
        assert "rc=$?" in lane, "serial pass must capture its exit code into rc"
        assert "$rc -eq 0" in lane, "serial pass guard must tolerate rc 0 (passed)"
        assert "$rc -eq 5" in lane, "serial pass guard must tolerate rc 5 (no match)"
        assert "exit $rc" in lane, (
            "any OTHER serial-pass exit code (e.g. 1 = real failure) must propagate "
            "via `exit $rc` and abort the lane"
        )
        # set -e must be restored around the tolerated pass so pipefail is not lost.
        assert "set +e" in lane and "set -e" in lane, (
            "serial pass must bracket the tolerated exit with `set +e` / `set -e`"
        )

    def test_smokes_and_stamp_are_default_lane_only(self):
        lane = _default_lane_text(_content())
        for needle in (
            "clean-room-smoke.sh",
            "plugin-parity-smoke.sh",
            "ci_local_stamp.py --write",
        ):
            assert needle in lane, f"{needle} must remain on the default/gate lane"

    def test_serial_failure_aborts_before_the_stamp(self):
        """The Red case: a real serial-pass failure (exit 1) must abort the lane
        BEFORE the green stamp — so the `exit $rc` propagation is wired ahead of
        `ci_local_stamp.py --write`."""
        lane = _default_lane_text(_content())
        propagate_pos = lane.find("exit $rc")
        stamp_pos = lane.find("ci_local_stamp.py --write")
        assert propagate_pos != -1 and stamp_pos != -1
        assert propagate_pos < stamp_pos, (
            "serial-pass `exit $rc` propagation must appear BEFORE the stamp write, "
            "so a real serial failure can never mask into a false-green stamp"
        )
