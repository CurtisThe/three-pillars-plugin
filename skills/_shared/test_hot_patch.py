"""test_hot_patch.py — hot_patch.py lane helper tests.

Covers Task 1.4 (Behavior 1: happy path, Behavior 6: no --no-verify, refusal
pre-flight assertions) from the hot-patch-protocol design.

Tests run hot_patch.py in --dry-run mode only — no real git/gh operations.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOT_PATCH_PY = REPO_ROOT / "skills" / "_shared" / "hot_patch.py"

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing hot_patch.py."""
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    return repo


# ---------------------------------------------------------------------------
# Task 1.4: --dry-run plan assertions
# ---------------------------------------------------------------------------

def test_dry_run_worktree_path(tmp_path):
    """Dry-run plan shows worktree at .claude/worktrees/hot-patch-<slug>."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"dry-run must exit 0; stderr={result.stderr!r}"
    plan = result.stdout
    # Worktree path must use .claude/worktrees/ prefix (NOT *-wt/ — inv #32)
    assert ".claude/worktrees/hot-patch-teardown-order" in plan, (
        f"Plan must name worktree at .claude/worktrees/hot-patch-<slug>; got:\n{plan}"
    )
    # Branch must be hot-patch/<slug> (NOT tp/* — inv #31/#32)
    assert "hot-patch/teardown-order" in plan, (
        f"Plan must name branch 'hot-patch/<slug>'; got:\n{plan}"
    )


def test_dry_run_no_verify_absent(tmp_path):
    """--no-verify must not appear anywhere in the dry-run plan (Behavior 6)."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert "--no-verify" not in combined, (
        f"--no-verify must NEVER appear in the hot_patch.py output; got:\n{combined}"
    )


def test_dry_run_trailer_in_commit(tmp_path):
    """Dry-run plan includes a commit step with the hot-patch: <trigger> trailer."""
    repo = _make_repo(tmp_path)
    trigger = "fix null ref in gate"
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", trigger,
         "--slug", "null-ref",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    plan = result.stdout
    assert "hot-patch:" in plan, (
        f"Plan must include the hot-patch: trailer; got:\n{plan}"
    )
    assert trigger in plan, f"Plan must include the trigger text; got:\n{plan}"


def test_dry_run_ledger_append_in_commit(tmp_path):
    """Dry-run plan includes the ledger append in the same commit step (Behavior 2).

    The ledger path must use the WORKTREE path (not repo_root) so the append
    rides in the same commit as the fix (Behavior 2, fix #3: structural).

    Asserts the JOINED path: worktree segment immediately followed by the ledger
    relative path — so a regression to f"{repo_root}/{LEDGER_RELPATH}" fails
    (that form uses repo_root, not the worktree path).

    Mutation-verify: reverting build_plan's ledger_path to
    f"{repo_root}/{LEDGER_RELPATH}" makes this assertion fail.
    """
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    plan = result.stdout
    assert result.returncode == 0, f"dry-run must exit 0; stderr={result.stderr!r}"
    # Assert the JOINED path: worktree segment + "/" + LEDGER_RELPATH must appear
    # in the plan as a contiguous substring (not just each part separately).
    from skills._shared.hot_patch import WORKTREE_PREFIX, LEDGER_RELPATH  # noqa: PLC0415
    worktree_segment = f"{WORKTREE_PREFIX}teardown-order"
    joined_ledger_path = f"{worktree_segment}/{LEDGER_RELPATH}"
    assert joined_ledger_path in plan, (
        f"Plan must contain the joined worktree ledger path {joined_ledger_path!r}; "
        f"got:\n{plan}"
    )


def test_dry_run_pr_step_merge_commit(tmp_path):
    """Dry-run plan includes gh pr create against default branch and merge-commit guidance."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    plan = result.stdout
    assert "gh pr create" in plan, f"Plan must include gh pr create; got:\n{plan}"
    assert "gh pr merge --merge" in plan, (
        f"Plan must include 'gh pr merge --merge' (merge commit required); got:\n{plan}"
    )


def test_dry_run_teardown_step(tmp_path):
    """Dry-run plan includes worktree + branch teardown after merge."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    plan = result.stdout
    assert "worktree remove" in plan or "worktree" in plan.lower(), (
        f"Plan must include worktree teardown step; got:\n{plan}"
    )


def test_dry_run_refuses_empty_trigger(tmp_path):
    """Helper refuses an empty trigger (required by design)."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "",
         "--slug", "teardown-order",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "Must refuse empty trigger"


# ---------------------------------------------------------------------------
# Task 1.4: pre-flight refusal path (exclusion + diff-cap)
# ---------------------------------------------------------------------------

def test_preflight_refuses_excluded_file(tmp_path):
    """Pre-flight refuses when file list hits the exclusion tuple.

    The refusal must emit a VIOLATION message AND no worktree-provision step
    must appear in the dry-run plan (refusal exits before provisioning).
    """
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix gate",
         "--slug", "gate-fix",
         "--dry-run",
         "--files", "framework-check.sh",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"Pre-flight must reject excluded files; exit was 0; output:\n{combined}"
    )
    assert "VIOLATION" in combined, (
        f"Pre-flight must emit VIOLATION message; got:\n{combined}"
    )
    # No provision step in the plan
    assert "worktree add" not in combined.lower(), (
        f"No worktree-provision step must appear when pre-flight fails; got:\n{combined}"
    )


def test_preflight_refuses_oversized_diff(tmp_path):
    """Pre-flight refuses when declared line count exceeds 150."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "big fix",
         "--slug", "big-fix",
         "--dry-run",
         "--estimated-lines", "200",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"Pre-flight must reject diff > 150 lines; exit was 0; output:\n{combined}"
    )
    assert "VIOLATION" in combined, (
        f"Pre-flight must emit VIOLATION on oversized diff; got:\n{combined}"
    )


# ---------------------------------------------------------------------------
# Task 1.4: module-level check — no --no-verify in source
# ---------------------------------------------------------------------------

def test_no_verify_not_in_module_source():
    """--no-verify must not appear anywhere in hot_patch.py source (Behavior 6)."""
    content = HOT_PATCH_PY.read_text()
    assert "--no-verify" not in content, (
        "hot_patch.py must NEVER contain '--no-verify'"
    )


# ---------------------------------------------------------------------------
# Item 11: slug validation + double-quote in trigger refusal
# ---------------------------------------------------------------------------

def test_slug_validation_rejects_uppercase(tmp_path):
    """hot_patch.py CLI refuses slugs with uppercase letters."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix thing",
         "--slug", "BadSlug",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "Must refuse slug with uppercase"
    assert "VIOLATION" in result.stderr or "invalid" in result.stderr.lower(), (
        f"Must emit VIOLATION for bad slug; got: {result.stderr!r}"
    )


def test_slug_validation_rejects_underscore(tmp_path):
    """hot_patch.py CLI refuses slugs with underscores."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix thing",
         "--slug", "bad_slug",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "Must refuse slug with underscore"


def test_trigger_rejects_double_quote(tmp_path):
    """hot_patch.py CLI refuses a trigger containing a double-quote character."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", 'fix "the" bug',
         "--slug", "fix-bug",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "Must refuse trigger with double-quote"
    assert "VIOLATION" in result.stderr, (
        f"Must emit VIOLATION for double-quote trigger; got: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Item 17: constants sync test
# ---------------------------------------------------------------------------

def test_constants_sync():
    """hot_patch.EXCLUDED_FILES, EXCLUDED_PREFIXES, DIFF_CAP, LEDGER_RELPATH
    all match hot_patch_check / hot_patch_ledger (single source of truth)."""
    from skills._shared import hot_patch as hp  # noqa: PLC0415
    from skills._shared import hot_patch_check as hpc  # noqa: PLC0415
    from skills._shared import hot_patch_ledger as hpl  # noqa: PLC0415

    assert hp.EXCLUDED_FILES == hpc.EXCLUDED_FILES, (
        "hot_patch.EXCLUDED_FILES must match hot_patch_check.EXCLUDED_FILES"
    )
    assert hp.EXCLUDED_PREFIXES == hpc.EXCLUDED_PREFIXES, (
        "hot_patch.EXCLUDED_PREFIXES must match hot_patch_check.EXCLUDED_PREFIXES"
    )
    assert hp.DIFF_CAP == hpc.DIFF_CAP, (
        "hot_patch.DIFF_CAP must match hot_patch_check.DIFF_CAP"
    )
    assert hp.LEDGER_RELPATH == hpl.LEDGER_RELPATH, (
        "hot_patch.LEDGER_RELPATH must match hot_patch_ledger.LEDGER_RELPATH"
    )


# ---------------------------------------------------------------------------
# Item 19: live-mode ordering (preflight before worktree provision)
# ---------------------------------------------------------------------------

def test_live_mode_preflight_before_provision(tmp_path):
    """In live mode, pre-flight refusal exits before any worktree-provision step.

    Uses a real git repo fixture so that if the guard were reversed (provision
    then preflight), git worktree add would actually succeed — verifying the
    ordering is enforced, not vacuously passing because git fails anyway.

    Asserts:
    - exit code 1 (pre-flight violation)
    - VIOLATION appears in stderr
    - "Provisioning worktree:" does NOT appear in stdout
    - the worktree directory does not exist on disk
    """
    import os  # noqa: PLC0415
    # Create a real git repo so worktree add would succeed if called
    repo = _make_repo(tmp_path)
    worktree_path = repo / ".claude" / "worktrees" / "hot-patch-gate-fix"

    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix gate",
         "--slug", "gate-fix",
         "--files", "framework-check.sh",
         "--repo-root", str(repo)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1, (
        f"Must refuse due to pre-flight exclusion; got rc={result.returncode}, "
        f"stderr={result.stderr!r}"
    )
    assert "VIOLATION" in result.stderr, (
        f"Pre-flight refusal must emit VIOLATION to stderr; got: {result.stderr!r}"
    )
    # Ordering: refusal must fire BEFORE the provision print
    assert "Provisioning worktree:" not in result.stdout, (
        f"'Provisioning worktree:' must NOT appear when pre-flight fails; "
        f"got stdout={result.stdout!r}"
    )
    # Verify no worktree directory was created (provision never ran)
    assert not worktree_path.exists(), (
        f"Worktree must not be provisioned on pre-flight failure; found {worktree_path}"
    )


# ---------------------------------------------------------------------------
# Trigger guard: each rejected char class (fix #5: structural)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_char,label", [
    ("`", "backtick"),
    ("$", "dollar"),
    ("\\", "backslash"),
    ("\n", "newline"),
    ("!", "exclamation"),
])
def test_trigger_rejects_injection_chars(tmp_path, bad_char, label):
    """hot_patch.py CLI refuses triggers containing shell-injection characters."""
    repo = _make_repo(tmp_path)
    trigger = f"fix{bad_char}bug"
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", trigger,
         "--slug", "fix-bug",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0, f"Must refuse trigger with {label}"
    assert "VIOLATION" in result.stderr, (
        f"Must emit VIOLATION for {label} trigger; got: {result.stderr!r}"
    )


def test_trigger_accepts_clean_text(tmp_path):
    """hot_patch.py accepts a clean trigger with no injection chars."""
    repo = _make_repo(tmp_path)
    result = subprocess.run(
        ["python3", str(HOT_PATCH_PY),
         "--trigger", "fix teardown order after fleet launch",
         "--slug", "teardown-fix",
         "--dry-run",
         "--repo-root", str(repo)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"Clean trigger must be accepted; stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# EXCLUDED_FILES completeness check (fix #1: structural)
# ---------------------------------------------------------------------------

def test_excluded_files_completeness():
    """Every skills/_shared/*hot_patch* file on disk must appear in EXCLUDED_FILES.

    This test fails if a new lane module is added but not added to EXCLUDED_FILES,
    so the exclusion list stays complete automatically.
    """
    from skills._shared import hot_patch_check as hpc  # noqa: PLC0415

    shared_dir = Path(hpc.__file__).resolve().parent
    on_disk = {
        p.name
        for p in shared_dir.glob("*hot_patch*")
        if p.is_file()
    }
    # Convert EXCLUDED_FILES to just basenames for comparison
    excluded_basenames = {
        p.rsplit("/", 1)[-1]
        for p in hpc.EXCLUDED_FILES
        if "hot_patch" in p
    }
    missing = on_disk - excluded_basenames
    assert not missing, (
        f"Lane modules on disk not in EXCLUDED_FILES: {sorted(missing)}. "
        "Add them to EXCLUDED_FILES in hot_patch_check.py and hot_patch.py."
    )
