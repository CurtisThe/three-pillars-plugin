"""test_hot_patch_check.py — check_exclusions, check_diff_cap, CLI, and wiring tests.

Covers Task 1.2 (exclusions + diff-cap), Task 1.5 (framework-check wiring),
and Task 1.6 (protocol prose anchors) from the hot-patch-protocol design.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


# ---------------------------------------------------------------------------
# Shared fixture: minimal git repo for hot-patch testing
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, env: dict) -> Path:
    """Create a minimal git repo and return its Path."""
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


def _trailered_commit(repo: Path, files: dict[str, str], env: dict, lines: int = 5) -> str:
    """Stage files and make a trailered hot-patch commit; return full SHA."""
    for relpath, content in files.items():
        fpath = repo / relpath
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)
        subprocess.run(["git", "add", relpath], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: test trigger",
         "-m", "Hotfix: fixture fix"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()


@pytest.fixture
def git_env():
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)
    return env


# ---------------------------------------------------------------------------
# Task 1.2: check_exclusions
# ---------------------------------------------------------------------------

def test_exclusions_fail_dot_three_pillars(tmp_path, git_env):
    """check_exclusions fails when commit touches .three-pillars/ prefix."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(repo, {".three-pillars/config.json": "{}\n"}, git_env)
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, f"Must fail on .three-pillars/ touch; got {violations}"


def test_exclusions_fail_framework_check_sh(tmp_path, git_env):
    """check_exclusions fails when commit touches framework-check.sh."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(repo, {"framework-check.sh": "#!/bin/bash\n"}, git_env)
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Must fail on framework-check.sh touch"


def test_exclusions_fail_deterministic_gate(tmp_path, git_env):
    """check_exclusions fails when commit touches deterministic_gate.py."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(
        repo, {"skills/_shared/deterministic_gate.py": "# gate\n"}, git_env,
    )
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Must fail on deterministic_gate.py touch"


def test_exclusions_fail_hot_patch_check_itself(tmp_path, git_env):
    """check_exclusions fails when commit touches the hot_patch_check.py module itself."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(
        repo, {"skills/_shared/hot_patch_check.py": "# self\n"}, git_env,
    )
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Must fail on hot_patch_check.py self-touch"


def test_exclusions_fail_worktree_isolation_guard(tmp_path, git_env):
    """check_exclusions fails when commit touches worktree_isolation_guard.py."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(
        repo, {"skills/_shared/worktree_isolation_guard.py": "# guard\n"}, git_env,
    )
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Must fail on worktree_isolation_guard.py touch"


def test_exclusions_fail_land_py(tmp_path, git_env):
    """check_exclusions fails when commit touches skills/tp-merge/scripts/land.py."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(
        repo, {"skills/tp-merge/scripts/land.py": "# land\n"}, git_env,
    )
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Must fail on land.py touch"


def test_exclusions_pass_innocent_file(tmp_path, git_env):
    """check_exclusions passes on a commit touching a non-excluded file."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(repo, {"skills/tp-guide/SKILL.md": "# guide\n"}, git_env)
    violations = check_exclusions(sha=sha, repo=str(repo))
    assert violations == [], f"Non-excluded file must pass; got {violations}"


# ---------------------------------------------------------------------------
# Task 1.2: check_diff_cap
# ---------------------------------------------------------------------------

def test_diff_cap_pass_small_diff(tmp_path, git_env):
    """check_diff_cap passes when diff is under 150 lines."""
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    content = "\n".join(f"line{i}" for i in range(10)) + "\n"
    sha = _trailered_commit(repo, {"skills/tp-guide/SKILL.md": content}, git_env)
    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert violations == [], f"Small diff must pass; got {violations}"


def test_diff_cap_fail_large_diff(tmp_path, git_env):
    """check_diff_cap fails when diff exceeds 150 lines."""
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    content = "\n".join(f"line{i}" for i in range(200)) + "\n"
    sha = _trailered_commit(repo, {"skills/tp-guide/SKILL.md": content}, git_env)
    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Diff >150 lines must fail"


def test_diff_cap_ledger_excluded_from_sum(tmp_path, git_env):
    """Ledger file (hot-patches.md) is excluded from the diff-cap sum."""
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    # 10-line fix + 200-line ledger — total would exceed cap if ledger counted
    fix_content = "\n".join(f"line{i}" for i in range(10)) + "\n"
    ledger_content = "\n".join(f"entry{i}" for i in range(200)) + "\n"
    sha = _trailered_commit(
        repo,
        {
            "skills/tp-guide/SKILL.md": fix_content,
            "three-pillars-docs/tp-designs/orchestration/hot-patches.md": ledger_content,
        },
        git_env,
    )
    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert violations == [], f"Ledger should be excluded; got {violations}"


# ---------------------------------------------------------------------------
# Task 1.2: CLI — VIOLATION lines + exit codes
# ---------------------------------------------------------------------------

def test_cli_exit_1_on_exclusion_violation(tmp_path, git_env):
    """CLI emits VIOLATION line and exits 1 when exclusion check fails."""
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    sha = _trailered_commit(repo, {"framework-check.sh": "#!/bin/bash\n"}, git_env)

    result = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--check-sha", sha],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, "CLI must exit 1 on violation"
    combined = result.stdout + result.stderr
    assert "VIOLATION" in combined, f"CLI must emit VIOLATION; got: {combined!r}"


def test_cli_exit_0_on_clean_commit(tmp_path, git_env):
    """CLI exits 0 for a clean trailered commit in the sanctioned shape.

    Sanctioned shape (item 14): trailered commit on side branch merged via
    --no-ff (preserves original SHA); ledger entry present on master;
    explicit GIT_COMMITTER_DATE far in the future — never time-bombs.
    Probed with now_iso in 2027 to confirm no false positive then either.
    """
    repo = _make_repo(tmp_path, git_env)

    # Explicit future date for the trailered commit
    commit_date = "2027-07-15T10:00:00Z"
    side_env = dict(git_env)
    side_env["GIT_COMMITTER_DATE"] = commit_date
    side_env["GIT_AUTHOR_DATE"] = commit_date

    # Step 1: side branch with trailered commit
    subprocess.run(["git", "checkout", "-b", "hot-patch/clean-test"],
                   cwd=str(repo), check=True, capture_output=True, env=git_env)
    content = "\n".join(f"line{i}" for i in range(10)) + "\n"
    fix_path = repo / "skills" / "tp-guide" / "SKILL.md"
    fix_path.parent.mkdir(parents=True, exist_ok=True)
    fix_path.write_text(content)
    subprocess.run(["git", "add", "skills/tp-guide/SKILL.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: clean test fixture",
         "-m", "Hotfix: clean fixture"],
        cwd=str(repo), check=True, capture_output=True, env=side_env,
    )
    # The trailered commit SHA is preserved through --no-ff merge
    trailered_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Step 2: merge into master via merge commit (SHA preserved on second-parent)
    subprocess.run(["git", "checkout", "master"],
                   cwd=str(repo), check=True, capture_output=True, env=git_env)
    subprocess.run(
        ["git", "merge", "--no-ff", "hot-patch/clean-test",
         "-m", "Merge hot-patch/clean-test"],
        cwd=str(repo), check=True, capture_output=True, env=side_env,
    )

    # Step 3: ledger entry in a separate master commit (normal practice)
    ledger_dir = repo / "three-pillars-docs" / "tp-designs" / "orchestration"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / "hot-patches.md"
    ledger_path.write_text(
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"- {trailered_sha} | 2027-07-15 | trigger: clean test fixture | "
        "broke: x | fix: y | touched: skills/tp-guide/SKILL.md\n"
    )
    subprocess.run(
        ["git", "add",
         "three-pillars-docs/tp-designs/orchestration/hot-patches.md"],
        cwd=str(repo), check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "docs: update ledger for clean fixture"],
        cwd=str(repo), check=True, capture_output=True, env=side_env,
    )

    # Within same UTC day → exit 0
    result = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--now", "2027-07-15T22:00:00Z"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"CLI must exit 0 on clean merged commit (same-day probe); "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Post-deadline probe (entry present) → still exit 0
    result2 = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--now", "2027-07-16T00:30:00Z"],
        capture_output=True, text=True,
    )
    assert result2.returncode == 0, (
        f"CLI must exit 0 when ledger entry present (2027 post-deadline probe); "
        f"stdout={result2.stdout!r} stderr={result2.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Task 1.5: framework-check.sh wiring
# ---------------------------------------------------------------------------

def test_framework_check_wiring():
    """framework-check.sh contains a #37 stanza delegating to hot_patch_check.py."""
    here = Path(__file__).resolve().parent
    fcs_path = here.parent.parent / "framework-check.sh"
    content = fcs_path.read_text(encoding="utf-8")

    # Banner is now DERIVED from active_count (inv #38), not a hardcoded literal.
    assert "framework-check: all ${_INV_N} invariants passed" in content, (
        "footer must read the derived 'all ${_INV_N} invariants passed' banner"
    )

    # The #37 stanza is present
    assert "# 37." in content, "framework-check.sh must contain a '# 37.' stanza"

    # Stanza delegates to hot_patch_check.py with "$SCRIPT_DIR" form
    assert 'hot_patch_check.py' in content, (
        "#37 stanza must reference hot_patch_check.py"
    )
    assert '"$SCRIPT_DIR"' in content or "'$SCRIPT_DIR'" in content, (
        "Stanza must use $SCRIPT_DIR path form"
    )

    # No --no-verify anywhere
    assert "--no-verify" not in content, (
        "framework-check.sh must never contain --no-verify"
    )

    # #37 stanza is positioned after the #36 stanza
    idx_36 = content.find("# 36.")
    idx_37 = content.find("# 37.")
    assert idx_36 != -1, "#36 stanza must still be present"
    assert idx_37 != -1, "#37 stanza must be present"
    assert idx_37 > idx_36, "#37 must appear after #36"


# ---------------------------------------------------------------------------
# Task 1.6: protocol prose anchors
# ---------------------------------------------------------------------------

def test_protocol_prose_anchors():
    """commit-after-work.md and weight-class.md contain required anchors (inv #36 form)."""
    here = Path(__file__).resolve().parent

    caw = here / "commit-after-work.md"
    wc = here / "weight-class.md"

    assert caw.exists(), "commit-after-work.md must exist"
    assert wc.exists(), "weight-class.md must exist"

    caw_text = caw.read_text(encoding="utf-8")
    wc_text = wc.read_text(encoding="utf-8")

    # commit-after-work.md anchors
    assert "hot-patch: <trigger>" in caw_text, (
        "commit-after-work.md must contain the trailer grammar 'hot-patch: <trigger>'"
    )
    assert "hot-patches.md" in caw_text, (
        "commit-after-work.md must reference hot-patches.md"
    )
    assert any(phrase in caw_text for phrase in ("same-day", "fail-closed")), (
        "commit-after-work.md must contain a same-day/fail-closed phrase"
    )

    # weight-class.md cross-note
    assert "below" in wc_text and "just-do-it" in wc_text, (
        "weight-class.md must contain a 'below' + 'just-do-it' cross-note line"
    )

    # No bare python3 skills/ or bash skills/ in either file (inv #36)
    import re  # noqa: PLC0415
    bare_pattern = re.compile(r'(python3|bash)\s+skills/')
    for path, text in [(caw, caw_text), (wc, wc_text)]:
        matches = bare_pattern.findall(text)
        assert not matches, (
            f"{path.name} must not contain bare 'python3 skills/' or 'bash skills/' "
            f"— use \"$TP_ROOT\"/ form (inv #36); found: {matches}"
        )


# ---------------------------------------------------------------------------
# Item 18: #37 stanza wiring pins
# ---------------------------------------------------------------------------

def test_stanza_37_no_dev_null():
    """framework-check.sh #37 stanza must NOT suppress stderr with 2>/dev/null."""
    fcs = REPO_ROOT / "framework-check.sh"
    content = fcs.read_text(encoding="utf-8")
    # Find the #37 stanza block (use 800 chars to cover the full hot_patch_check invocation)
    idx37 = content.find("# 37.")
    assert idx37 != -1, "#37 stanza must be present"
    snippet = content[idx37:idx37 + 800]
    # The hot_patch_check.py invocation line must not have 2>/dev/null
    assert "2>/dev/null" not in snippet, (
        "#37 stanza must not redirect stderr to /dev/null (crash diagnostics require it)"
    )


def test_stanza_37_crash_branch_text():
    """framework-check.sh #37 stanza contains the fail-closed crash branch.

    Scoped to the #37 stanza slice to verify the literal fail-closed elif text
    (not just its presence anywhere in the file).
    Verifies against a whole-elif-deletion mutant.
    """
    fcs = REPO_ROOT / "framework-check.sh"
    content = fcs.read_text(encoding="utf-8")
    idx37 = content.find("# 37.")
    assert idx37 != -1, "#37 stanza must be present"
    # Slice from #37 to the next major stanza boundary or end-of-file (~800 chars)
    idx_next = content.find("\n\n", idx37 + 100)
    stanza_slice = content[idx37:idx_next] if idx_next != -1 else content[idx37:]
    # The fail-closed elif must appear in the stanza (deleted elif → test fails)
    assert "inv37_rc" in stanza_slice, (
        "#37 stanza slice must reference inv37_rc"
    )
    assert "helper crash" in stanza_slice or "helper crash" in content[idx37:idx37 + 800], (
        "#37 stanza fail-closed elif must contain 'helper crash' text"
    )


# ---------------------------------------------------------------------------
# Item 16: diff-cap edge cases
# ---------------------------------------------------------------------------

def test_diff_cap_exactly_150_lines_passes(tmp_path, git_env):
    """A diff of exactly 150 lines passes (cap is inclusive: >150 fails)."""
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    content = "\n".join(f"line{i}" for i in range(150)) + "\n"
    sha = _trailered_commit(repo, {"skills/tp-guide/SKILL.md": content}, git_env)
    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert violations == [], f"Exactly 150 lines must pass; got {violations}"


def test_diff_cap_binary_file_fails(tmp_path, git_env):
    """A binary file in a hot-patch commit fails the diff cap outright."""
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = _make_repo(tmp_path, git_env)
    binary_path = repo / "image.png"
    binary_path.write_bytes(bytes(range(256)))  # actual binary content
    subprocess.run(["git", "add", "image.png"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: binary test",
         "-m", "Hotfix: binary"],
        cwd=str(repo), check=True, capture_output=True, env=git_env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert len(violations) >= 1, "Binary file must fail diff cap"
    assert "binary" in violations[0].lower(), f"Must mention 'binary'; got {violations}"


# ---------------------------------------------------------------------------
# Item 16: CLI exit 2 on internal error
# ---------------------------------------------------------------------------

def test_cli_exits_2_on_internal_error(tmp_path, monkeypatch):
    """main() returns 2 when an internal exception propagates (fail-closed)."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    def _raise(*_a, **_kw):
        raise RuntimeError("injected git failure")

    monkeypatch.setattr(hot_patch_check, "_trailered_commits_on_head", _raise)
    rc = hot_patch_check.main(["--repo-root", str(tmp_path)])
    assert rc == 2, f"Internal error must exit 2; got {rc}"
