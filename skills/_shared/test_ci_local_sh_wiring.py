"""test_ci_local_sh_wiring.py — ci-local.sh shell-wiring tests.

Covers:
  TestCiLocalShStructural — structural assertions on ci-local.sh:
                            --expect-head and --start-dirty flag wiring,
                            ordering (before first check), and capture positions
                            (Task 3.2 / STRUCTURAL 3)
  TestCiLocalShDelegation — ci-local.sh invokes ci_local_stamp.py --write after
                            pytest and framework-check; fail-fast on dirty start
                            (Task 3.4)

See also:
  test_ci_local_stamp.py       — write_stamp/read_stamp/StampError unit tests
  test_ci_local_stamp_pred.py  — pred_ci_local_stamp predicate matrix
  test_ci_local_stamp_cli.py   — --write CLI tests (exit codes, drift guard)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))


# ---------------------------------------------------------------------------
# Helpers: scan ci-local.sh for non-comment invocation and assignment lines
# ---------------------------------------------------------------------------

def _find_stamp_invocation_line(ci_local_sh_path):
    """Return the actual (non-comment) invocation line of ci_local_stamp.py --write,
    with any trailing inline comment stripped.

    Locates the line containing 'ci_local_stamp.py --write' that does NOT start
    with '#' after lstrip — i.e. the real invocation, not a comment.  This pins
    STRUCTURAL 3: the comment block in ci-local.sh contains '--expect-head' and
    '--start-dirty' literals, so asserting on the full file content would pass
    even if the flags were stripped from the real invocation line.

    Trailing inline comments (e.g. 'cmd arg # note') are stripped before the
    caller's substring asserts so a comment can never satisfy a flag check.
    Note: this strip is simple (splits on the first unquoted ' #') and does not
    handle backslash-continued multi-line commands.
    """
    with open(ci_local_sh_path) as fh:
        lines = fh.readlines()
    for line in lines:
        stripped = line.lstrip()
        if "ci_local_stamp.py --write" in line and not stripped.startswith("#"):
            # Strip trailing inline comment so ' # note' cannot satisfy flag asserts
            code_part = line.split(" #")[0]
            return code_part
    return None


def _find_var_assignment_line_pos(lines, var_name):
    """Return the character offset (in the joined file) of the first non-comment
    line that assigns to var_name (i.e. starts with 'VAR=' after lstrip, not '#').

    This mirrors _find_stamp_invocation_line: using whole-file content.find() on
    a variable name can hit the first occurrence in a comment block, so we locate
    the actual assignment line and compute its offset in the file.
    """
    offset = 0
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#") and stripped.startswith(f"{var_name}="):
            return offset
        offset += len(line)
    return -1


def _find_pattern_line_pos(lines, pattern):
    """Return the character offset of the first non-comment line containing pattern.

    Trailing inline comments (e.g. 'cmd arg # note') are stripped before the
    pattern test so a comment containing the pattern cannot shift first_check_pos.
    Mirrors the inline-comment strip in _find_stamp_invocation_line.
    """
    offset = 0
    for line in lines:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            # Strip trailing inline comment before pattern check
            code_part = line.split(" #")[0]
            if pattern in code_part:
                return offset
        offset += len(line)
    return -1


# ---------------------------------------------------------------------------
# TestCiLocalShStructural: STRUCTURAL 3 — flag wiring and ordering anchors
# ---------------------------------------------------------------------------

class TestCiLocalShStructural:
    """Structural assertions: ci-local.sh passes --expect-head and --start-dirty
    on the real (non-comment) invocation line, with captures before first check.
    """

    def test_ci_local_sh_uses_expect_head(self):
        """ci-local.sh captures HEAD before the FIRST CHECK and passes --expect-head.

        The actual non-comment invocation line must contain BOTH --expect-head AND
        the $CI_START_HEAD expansion.  This pins STRUCTURAL 3: asserting on the full
        file content is comment-satisfiable; we assert only on the real invocation line.
        """
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"

        with open(ci_local_sh) as fh:
            lines = fh.readlines()

        # Locate the real (non-comment) invocation line
        invocation_line = _find_stamp_invocation_line(ci_local_sh)
        assert invocation_line is not None, (
            "ci-local.sh must have a non-comment line invoking ci_local_stamp.py --write"
        )
        assert "--expect-head" in invocation_line, (
            f"Real invocation line must contain --expect-head, got: {invocation_line!r}"
        )
        assert "$CI_START_HEAD" in invocation_line, (
            f"Real invocation line must expand $CI_START_HEAD, got: {invocation_line!r}"
        )

        # CI_START_HEAD capture must come before the FIRST CHECK (pre-commit run),
        # not just before the stamp write.  Positions are derived from non-comment
        # assignment lines so comments cannot satisfy the ordering invariant.
        capture_pos = _find_var_assignment_line_pos(lines, "CI_START_HEAD")
        first_check_pos = _find_pattern_line_pos(lines, "pre-commit run")
        stamp_pos = _find_pattern_line_pos(lines, "ci_local_stamp.py --write")
        assert first_check_pos != -1, "pre-commit run step not found in ci-local.sh"
        assert capture_pos != -1, "CI_START_HEAD assignment not found in ci-local.sh"
        assert capture_pos < first_check_pos, (
            "CI_START_HEAD must be captured before the first check (pre-commit run), "
            f"not just before the stamp step (capture at {capture_pos}, "
            f"first-check at {first_check_pos})"
        )
        assert capture_pos < stamp_pos, (
            "HEAD must be captured (CI_START_HEAD) before the stamp step"
        )

    def test_ci_local_sh_uses_start_dirty(self):
        """ci-local.sh captures dirty state before the FIRST CHECK and passes --start-dirty.

        The actual non-comment invocation line must contain BOTH --start-dirty AND
        the $CI_START_DIRTY expansion.  This pins STRUCTURAL 3: asserting on the full
        file content is comment-satisfiable; we assert only on the real invocation line.
        """
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"

        with open(ci_local_sh) as fh:
            lines = fh.readlines()

        # Locate the real (non-comment) invocation line
        invocation_line = _find_stamp_invocation_line(ci_local_sh)
        assert invocation_line is not None, (
            "ci-local.sh must have a non-comment line invoking ci_local_stamp.py --write"
        )
        assert "--start-dirty" in invocation_line, (
            f"Real invocation line must contain --start-dirty, got: {invocation_line!r}"
        )
        assert "$CI_START_DIRTY" in invocation_line, (
            f"Real invocation line must expand $CI_START_DIRTY, got: {invocation_line!r}"
        )

        # CI_START_DIRTY capture must come before the FIRST CHECK (pre-commit run).
        # Positions are derived from non-comment assignment lines so comments cannot
        # satisfy the ordering invariant.
        dirty_capture_pos = _find_var_assignment_line_pos(lines, "CI_START_DIRTY")
        first_check_pos = _find_pattern_line_pos(lines, "pre-commit run")
        stamp_pos = _find_pattern_line_pos(lines, "ci_local_stamp.py --write")
        assert first_check_pos != -1, "pre-commit run step not found in ci-local.sh"
        assert dirty_capture_pos != -1, "CI_START_DIRTY assignment not found in ci-local.sh"
        assert dirty_capture_pos < first_check_pos, (
            "CI_START_DIRTY must be captured before the first check (pre-commit run), "
            f"capture at {dirty_capture_pos}, first-check at {first_check_pos}"
        )
        assert dirty_capture_pos < stamp_pos, (
            "CI_START_DIRTY must be captured before the stamp step"
        )


# ---------------------------------------------------------------------------
# Task 3.4: TestCiLocalShDelegation
# ---------------------------------------------------------------------------

class TestCiLocalShDelegation:
    """ci-local.sh invokes ci_local_stamp.py --write after pytest and framework-check."""

    def test_ci_local_sh_invokes_stamp_write(self):
        """The script contains a call to ci_local_stamp.py --write."""
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"
        content = ci_local_sh.read_text(encoding="utf-8")
        assert "ci_local_stamp.py --write" in content, (
            "ci-local.sh does not invoke ci_local_stamp.py --write"
        )

    def test_stamp_step_comes_after_pytest(self):
        """The stamp step appears AFTER the pytest step in ci-local.sh."""
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"
        content = ci_local_sh.read_text(encoding="utf-8")
        pytest_pos = content.find("python -m pytest")
        stamp_pos = content.find("ci_local_stamp.py --write")
        assert pytest_pos != -1, "pytest step not found in ci-local.sh"
        assert stamp_pos != -1, "stamp step not found in ci-local.sh"
        assert stamp_pos > pytest_pos, (
            "stamp step must come AFTER pytest step "
            f"(pytest at {pytest_pos}, stamp at {stamp_pos})"
        )

    def test_stamp_step_comes_after_framework_check(self):
        """The stamp step appears AFTER the framework-check step (real invocation line).

        content.find("framework-check") binds to the header comment block, not the
        actual ./test-framework-check.sh invocation step.  We scan line-by-line and
        use the first non-comment line that contains 'test-framework-check.sh' so
        that moving the stamp write before the real framework-check step will fail.
        """
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"

        with open(ci_local_sh) as fh:
            lines = fh.readlines()

        fw_pos = -1
        stamp_pos = -1
        offset = 0
        for line in lines:
            stripped = line.lstrip()
            if not stripped.startswith("#"):
                code_part = line.split(" #")[0]
                if fw_pos == -1 and "test-framework-check.sh" in code_part:
                    fw_pos = offset
                if stamp_pos == -1 and "ci_local_stamp.py --write" in code_part:
                    stamp_pos = offset
            offset += len(line)

        assert fw_pos != -1, (
            "Non-comment line invoking test-framework-check.sh not found in ci-local.sh"
        )
        assert stamp_pos != -1, "stamp step not found in ci-local.sh"
        assert stamp_pos > fw_pos, (
            "stamp step must come AFTER framework-check step "
            f"(test-framework-check.sh at {fw_pos}, stamp at {stamp_pos})"
        )

    def test_fail_fast_on_ci_start_dirty_between_capture_and_first_check(self):
        """ci-local.sh has a non-comment fail-fast exit on CI_START_DIRTY between
        the dirty capture and the first check ('pre-commit run').

        Pins the fail-fast block wiring: a deleted or misplaced fail-fast block
        would allow the full check suite to burn on a dirty tree that can never
        produce a valid stamp.

        The assertion locates the non-comment assignment lines for CI_START_DIRTY
        (reusing the non-comment-line technique from _find_stamp_invocation_line)
        and confirms that a non-comment conditional on CI_START_DIRTY and a
        subsequent non-comment 'exit' line both appear AFTER the CI_START_DIRTY
        capture AND BEFORE 'pre-commit run'.
        """
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"

        with open(ci_local_sh) as fh:
            lines = fh.readlines()

        # Scan line-by-line, tracking character offsets.
        # We look for:
        #   dirty_capture_offset  — first non-comment line starting with CI_START_DIRTY=
        #   fail_fast_cond_offset — first non-comment line that is guard-shaped:
        #                           contains '"$CI_START_DIRTY" -eq 1' AND does NOT
        #                           contain 'CI_START_DIRTY=' (i.e. not the normalization
        #                           assignment line, which matches the old unanchored check)
        #   exit_offset           — first non-comment line with a NONZERO exit
        #                           (\bexit\s+[1-9]\d*\b) after the guard condition
        #   first_check_offset    — first non-comment line with 'pre-commit run'
        dirty_capture_offset = -1
        fail_fast_cond_offset = -1
        exit_offset = -1
        first_check_offset = -1
        offset = 0
        for line in lines:
            stripped = line.lstrip()
            is_comment = stripped.startswith("#")
            if not is_comment:
                if dirty_capture_offset == -1 and stripped.startswith("CI_START_DIRTY="):
                    dirty_capture_offset = offset
                elif (
                    fail_fast_cond_offset == -1
                    and dirty_capture_offset != -1
                    # Guard-shaped: must reference the guard condition, not the normalization
                    and '"$CI_START_DIRTY" -eq 1' in line
                    and "CI_START_DIRTY=" not in line
                ):
                    # Non-comment guard on CI_START_DIRTY after the capture
                    fail_fast_cond_offset = offset
                if (
                    exit_offset == -1
                    and fail_fast_cond_offset != -1
                    and re.search(r"\bexit\s+[1-9]\d*\b", stripped)
                ):
                    exit_offset = offset
                if first_check_offset == -1 and "pre-commit run" in line:
                    first_check_offset = offset
            offset += len(line)

        assert dirty_capture_offset != -1, (
            "CI_START_DIRTY non-comment assignment not found in ci-local.sh"
        )
        assert first_check_offset != -1, (
            "'pre-commit run' non-comment line not found in ci-local.sh"
        )
        assert fail_fast_cond_offset != -1, (
            "No non-comment conditional on CI_START_DIRTY found after the capture "
            "in ci-local.sh; expected a guard like "
            "'if [ \"$CI_START_DIRTY\" -eq 1 ]; then ... exit 1; fi'"
        )
        assert exit_offset != -1, (
            "No non-comment nonzero 'exit N' (N >= 1) line found after the "
            "CI_START_DIRTY conditional in ci-local.sh; the fail-fast block must "
            "contain a nonzero exit statement (e.g. 'exit 1'), not 'exit 0'"
        )
        assert exit_offset < first_check_offset, (
            "Fail-fast exit on CI_START_DIRTY must appear BEFORE 'pre-commit run' "
            "(the first check); "
            f"exit at {exit_offset}, first-check at {first_check_offset}"
        )
        assert dirty_capture_offset < fail_fast_cond_offset, (
            "CI_START_DIRTY conditional must appear AFTER the CI_START_DIRTY capture"
        )

    def test_plugin_parity_smoke_wired_after_clean_room_smoke(self):
        """ci-local.sh runs plugin-parity-smoke.sh, positioned directly after
        clean-room-smoke.sh and before the stamp write (plugin-mode-parity Task 2.6).
        """
        ci_local_sh = _SHARED_DIR.parent.parent / "scripts" / "ci-local.sh"

        with open(ci_local_sh) as fh:
            lines = fh.readlines()

        clean_room_pos = _find_pattern_line_pos(lines, "clean-room-smoke.sh")
        parity_pos = _find_pattern_line_pos(lines, "plugin-parity-smoke.sh")
        stamp_pos = _find_pattern_line_pos(lines, "ci_local_stamp.py --write")

        assert clean_room_pos != -1, "clean-room-smoke.sh step not found in ci-local.sh"
        assert parity_pos != -1, "plugin-parity-smoke.sh is not wired into ci-local.sh"
        assert stamp_pos != -1, "stamp step not found in ci-local.sh"
        assert clean_room_pos < parity_pos < stamp_pos, (
            "plugin-parity-smoke.sh must run AFTER clean-room-smoke.sh and BEFORE "
            f"the stamp write (clean-room at {clean_room_pos}, parity-smoke at "
            f"{parity_pos}, stamp at {stamp_pos})"
        )
