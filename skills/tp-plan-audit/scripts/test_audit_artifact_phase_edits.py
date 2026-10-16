"""M46: a phase's own `**Status**:` edits never stale the plan-audit pass artifact.

`/tp-phase-implement` step 8 (and `local-dispatch.md` §2's `done`/`blocked` marking)
writes `**Status**:` lines into plan.md after the audit. The digest ignores those
lines, so phase N+1's step-0b `--check` still passes; every other edit is stale.
Also covers the `--write` CLI that `/tp-run-full-design` Slot 6 calls on a pass.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_artifact  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "audit_artifact.py"

PLAN = """# Plan: demo

## Phase 1: core

### Task 1.1: add the parser
**File**: `src/parser.py` (new)
**Test**: `tests/test_parser.py::test_parses`
**Red**: the test fails on import.
**Green**: implement `parse()`.
**Done when**: the test passes.

### Task 1.2: wire it in
**Status**: pending
**File**: `src/cli.py` (modify)
**Test**: `tests/test_cli.py::test_cli_parses`
**Red**: the CLI ignores the flag.
**Green**: call `parse()` from the CLI.
**Done when**: the test passes.

## Phase 2: polish

### Task 2.1: error messages
**File**: `src/parser.py` (modify)
**Test**: `tests/test_parser.py::test_errors`
**Red**: a bad input raises a bare KeyError.
**Green**: raise `ParseError` with the line number.
**Done when**: the test passes.
"""


def _audited(tmp_path, body=PLAN):
    (tmp_path / "plan.md").write_text(body, encoding="utf-8")
    audit_artifact.write_pass_artifact(tmp_path, "council")
    return tmp_path


def _edit(design_dir, old, new):
    plan = design_dir / "plan.md"
    text = plan.read_text(encoding="utf-8")
    assert old in text, old
    plan.write_text(text.replace(old, new, 1), encoding="utf-8")


def _check(design_dir):
    return subprocess.run([sys.executable, str(SCRIPT), "--check", str(design_dir)],
                          capture_output=True, text=True)


# --- status-only edits stay fresh -------------------------------------------------

def test_phase_one_status_edits_keep_check_passing(tmp_path):
    """The live-check failure: phase 1's Status lines, then phase 2's step-0b check."""
    d = _audited(tmp_path)
    _edit(d, "### Task 1.1: add the parser\n", "### Task 1.1: add the parser\n**Status**: Done ✓\n")
    _edit(d, "**Status**: pending\n", "**Status**: Done ✓ (commit `ab12cd3`, 2026-09-30)\n")
    assert audit_artifact.artifact_status(d)[0] == "ok"
    r = _check(d)
    assert r.returncode == 0, r.stdout


def test_status_line_appended_after_a_blank_line_stays_fresh(tmp_path):
    d = _audited(tmp_path)
    _edit(d, "**Done when**: the test passes.\n\n## Phase 2",
          "**Done when**: the test passes.\n\n**Status**: Blocked (flaky fixture)\n\n## Phase 2")
    assert audit_artifact.artifact_status(d)[0] == "ok"


def test_every_status_value_the_phase_writes_stays_fresh(tmp_path):
    d = _audited(tmp_path)
    for value in ("Done ✓", "Done ✓ (unverified: targets-none)", "Skipped (pre-exists)",
                  "Blocked (env-error: no gh)", "Not started"):
        _edit(d, "### Task 2.1: error messages\n",
              f"### Task 2.1: error messages\n**Status**: {value}\n")
        assert audit_artifact.artifact_status(d)[0] == "ok", value
        (d / "plan.md").write_text(PLAN, encoding="utf-8")


def test_heading_blank_status_shape_stays_fresh(tmp_path):
    """PR #195 r1: fragile-test-prevention's workers wrote a blank line plus the Status
    line between each heading and its **File** line; the gate must not go stale."""
    d = _audited(tmp_path)
    for task in ("### Task 1.1: add the parser\n", "### Task 2.1: error messages\n"):
        _edit(d, task, task + "\n**Status**: Done ✓\n")
    assert audit_artifact.artifact_status(d)[0] == "ok"
    assert _check(d).returncode == 0


def test_status_after_last_field_before_a_gap_stays_fresh(tmp_path):
    d = _audited(tmp_path)
    _edit(d, "**Done when**: the test passes.\n\n### Task 1.2",
          "**Done when**: the test passes.\n**Status**: Done ✓\n\n### Task 1.2")
    assert audit_artifact.artifact_status(d)[0] == "ok"


def test_crlf_blank_gap_status_edit_stays_fresh(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_bytes(PLAN.replace("\n", "\r\n").encode("utf-8"))
    audit_artifact.write_pass_artifact(tmp_path, "council")
    gap = b"the test passes.\r\n\r\n## Phase 2"
    plan.write_bytes(plan.read_bytes().replace(
        gap, b"the test passes.\r\n\r\n" + "**Status**: Done ✓".encode("utf-8") + b"\r\n\r\n## Phase 2"))
    assert audit_artifact.artifact_status(tmp_path)[0] == "ok"


def test_blank_line_only_edits_stay_fresh(tmp_path):
    """Blank lines are layout: a snapshot cannot tell which ones a phase added."""
    d = _audited(tmp_path)
    _edit(d, "the test passes.\n\n### Task 1.2", "the test passes.\n### Task 1.2")
    _edit(d, "### Task 2.1: error messages\n", "### Task 2.1: error messages\n\n  \n")
    assert audit_artifact.artifact_status(d)[0] == "ok"


def test_crlf_status_edit_stays_fresh(tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_bytes(PLAN.replace("\n", "\r\n").encode("utf-8"))
    audit_artifact.write_pass_artifact(tmp_path, "council")
    heading = "### Task 1.1: add the parser\r\n".encode("utf-8")
    plan.write_bytes(plan.read_bytes().replace(heading, heading + "**Status**: Done ✓\r\n".encode("utf-8")))
    assert audit_artifact.artifact_status(tmp_path)[0] == "ok"
    plan.write_bytes(plan.read_bytes().replace(b"implement `parse()`", b"implement it"))
    assert audit_artifact.artifact_status(tmp_path)[0] == "stale"


# --- any other edit goes stale ----------------------------------------------------

def _assert_stale(tmp_path, old, new):
    d = _audited(tmp_path)
    _edit(d, old, new)
    status, reason = audit_artifact.artifact_status(d)
    assert status == "stale", (old, new)
    assert "digest mismatch" in reason
    assert _check(d).returncode == 1


def test_editing_a_task_field_goes_stale(tmp_path):
    _assert_stale(tmp_path, "**Green**: implement `parse()`.", "**Green**: implement `parse()` and `dump()`.")


def test_adding_a_task_goes_stale(tmp_path):
    _assert_stale(tmp_path, "## Phase 2: polish\n",
                  "### Task 1.3: extra\n**File**: `src/x.py` (new)\n\n## Phase 2: polish\n")


def test_status_label_mid_line_is_not_ignored(tmp_path):
    _assert_stale(tmp_path, "**Red**: the CLI ignores the flag.",
                  "**Red**: the CLI ignores the flag. **Status**: Done ✓")


def test_indented_or_quoted_status_line_is_not_ignored(tmp_path):
    _assert_stale(tmp_path, "**Done when**: the test passes.\n\n## Phase 2",
                  "**Done when**: the test passes.\n  **Status**: Done ✓\n\n## Phase 2")


def test_joining_two_lines_goes_stale(tmp_path):
    _assert_stale(tmp_path, "**Red**: the test fails on import.\n**Green**: implement `parse()`.",
                  "**Red**: the test fails on import. **Green**: implement `parse()`.")


def test_whitespace_inside_a_line_goes_stale(tmp_path):
    _assert_stale(tmp_path, "**Green**: implement `parse()`.", "**Green**:  implement `parse()`.")


def test_changing_a_status_line_into_other_content_goes_stale(tmp_path):
    _assert_stale(tmp_path, "**Status**: pending\n", "**Stat**: pending\n")


# --- backward compatibility and the Slot 6 --write CLI ----------------------------

def test_artifact_with_a_raw_bytes_digest_still_passes_when_plan_unchanged(tmp_path):
    """An artifact written before M46 stores sha256(plan.md bytes); keep it valid."""
    import hashlib

    d = _audited(tmp_path)
    art = d / audit_artifact.ARTIFACT_NAME
    rec = json.loads(art.read_text(encoding="utf-8"))
    rec["plan_digest"] = hashlib.sha256((d / "plan.md").read_bytes()).hexdigest()
    art.write_text(json.dumps(rec), encoding="utf-8")
    assert audit_artifact.artifact_status(d)[0] == "ok"
    _edit(d, "**Green**: implement `parse()`.", "**Green**: rewrite.")
    assert audit_artifact.artifact_status(d)[0] == "stale"


def test_write_cli_records_a_council_pass(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--write", str(tmp_path), "--mode", "council"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rec = json.loads((tmp_path / audit_artifact.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert rec["verdict"] == "pass" and rec["plan_audit_mode"] == "council"
    assert rec["plan_digest"] == audit_artifact.plan_digest(tmp_path / "plan.md")
    assert _check(tmp_path).returncode == 0


def test_write_cli_without_plan_md_fails_and_writes_nothing(tmp_path):
    r = subprocess.run([sys.executable, str(SCRIPT), "--write", str(tmp_path), "--mode", "council"],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert not (tmp_path / audit_artifact.ARTIFACT_NAME).exists()


def test_write_cli_requires_a_mode(tmp_path):
    (tmp_path / "plan.md").write_text(PLAN, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--write", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert not (tmp_path / audit_artifact.ARTIFACT_NAME).exists()
