"""test_hot_patch_ledger.py — ledger seed + parse_ledger + coverage deadline tests.

Covers Tasks 1.1 and 1.3 (seed existence, parse_ledger, check_ledger_coverage).
Anomaly-scan tests live in test_hot_patch_anomaly.py (split by responsibility).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "three-pillars-docs" / "tp-designs" / "orchestration" / "hot-patches.md"

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}


# ---------------------------------------------------------------------------
# Task 1.1: seed existence + header
# ---------------------------------------------------------------------------

def test_ledger_seed_exists_and_parses():
    """Ledger file exists, starts with the required header, and parses cleanly.

    Note: this checks the ledger's *structure* (header, append anchor, format
    docs, parseability) — NOT that it stays empty. Real hot-patch entries
    accumulate below the anchor as patches land (that is the protocol working);
    entry-parsing fidelity is covered by test_parse_ledger_returns_entries.
    """
    from skills._shared.hot_patch_check import parse_ledger  # noqa: PLC0415

    assert LEDGER_PATH.exists(), f"Ledger not found: {LEDGER_PATH}"
    text = LEDGER_PATH.read_text(encoding="utf-8")

    assert text.startswith("# Hot-patch ledger — append-only"), (
        "Ledger must start with '# Hot-patch ledger — append-only'"
    )
    assert "<!-- entries below -->" in text, (
        "Ledger must contain the append anchor '<!-- entries below -->'"
    )
    assert "hot-patch: <trigger>" in text, (
        "Ledger must document the entry format including 'hot-patch: <trigger>'"
    )

    entries = parse_ledger(text)
    assert isinstance(entries, list), f"parse_ledger must return a list; got {type(entries)}"


# ---------------------------------------------------------------------------
# Task 1.3: parse_ledger — full SHA prefix matching
# ---------------------------------------------------------------------------

def test_parse_ledger_returns_entries():
    """parse_ledger extracts entries from ledger text."""
    from skills._shared.hot_patch_check import parse_ledger  # noqa: PLC0415

    text = (
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        "- abc1234 | 2026-06-13 | trigger: fix teardown | broke: order bug | fix: swap calls | touched: skills/tp-merge\n"
        "- def5678abcdef1234567890abcdef12345678901234 | 2026-06-14 | trigger: null ref | broke: crash | fix: guard | touched: skills/tp-guide\n"
    )
    entries = parse_ledger(text)
    assert len(entries) == 2
    assert entries[0]["sha"] == "abc1234"
    assert entries[0]["trigger"] == "fix teardown"
    assert entries[0]["date"] == "2026-06-13"
    assert entries[1]["sha"] == "def5678abcdef1234567890abcdef12345678901234"



# ---------------------------------------------------------------------------
# Task 1.3: check_ledger_coverage — deadline mechanics (fixture-repo)
# ---------------------------------------------------------------------------

@pytest.fixture
def hot_patch_repo(tmp_path):
    """Minimal git repo with one trailered commit on master.

    Returns dict: repo (Path), sha (str full SHA).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)

    # Initial commit
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )

    # Hot-patch commit with trailer
    (repo / "fix.py").write_text("# fix\n")
    subprocess.run(["git", "add", "fix.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: test trigger",
         "-m", "Hotfix: test fix"],
        cwd=str(repo), check=True, capture_output=True, text=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    return {"repo": repo, "sha": sha}


def test_coverage_pass_when_entry_present(hot_patch_repo):
    """A trailered commit whose ledger entry is present passes coverage."""
    from skills._shared.hot_patch_check import check_ledger_coverage  # noqa: PLC0415

    sha = hot_patch_repo["sha"]
    repo = hot_patch_repo["repo"]
    ledger_text = (
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"- {sha} | 2026-06-13 | trigger: test trigger | broke: x | fix: y | touched: z\n"
    )
    result = check_ledger_coverage(
        repo=str(repo),
        ledger_text=ledger_text,
        now_iso="2026-06-14T00:00:00Z",
    )
    assert result == [], f"Expected no violations; got {result}"


def test_coverage_pass_within_same_day_window(tmp_path):
    """A trailered commit missing its entry PASSES while still in the commit's UTC day.

    Uses a controlled GIT_COMMITTER_DATE in the future (2027-06-01) so the
    test never time-bombs regardless of what "today" is when it runs.
    """
    from skills._shared.hot_patch_check import check_ledger_coverage  # noqa: PLC0415

    repo = tmp_path / "repo"
    repo.mkdir()
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)

    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=str(repo),
                   check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=str(repo),
                   check=True, capture_output=True)

    # Initial commit
    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )

    # Trailered commit with explicit future committer date
    commit_date = "2027-06-01T12:00:00Z"
    commit_env = dict(env)
    commit_env["GIT_COMMITTER_DATE"] = commit_date
    commit_env["GIT_AUTHOR_DATE"] = commit_date
    (repo / "fix.py").write_text("# fix\n")
    subprocess.run(["git", "add", "fix.py"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: same-day test",
         "-m", "Hotfix: same-day"],
        cwd=str(repo), check=True, capture_output=True, env=commit_env,
    )

    ledger_text = "# Hot-patch ledger — append-only\n\n<!-- entries below -->\n"
    # now_iso is within the same UTC day as the commit
    result = check_ledger_coverage(
        repo=str(repo),
        ledger_text=ledger_text,
        now_iso="2027-06-01T18:00:00Z",
    )
    assert result == [], f"Within same-day window must pass; got {result}"


def test_coverage_fail_overdue(hot_patch_repo):
    """A trailered commit missing its entry FAILS once past the UTC calendar day."""
    from skills._shared.hot_patch_check import check_ledger_coverage  # noqa: PLC0415

    sha = hot_patch_repo["sha"]
    repo = hot_patch_repo["repo"]
    ledger_text = (
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
    )
    result = check_ledger_coverage(
        repo=str(repo),
        ledger_text=ledger_text,
        now_iso="2099-01-01T00:00:00Z",
    )
    assert len(result) >= 1, "Expected at least one violation for overdue ledger"
    combined = " ".join(result)
    assert sha[:7] in combined, f"VIOLATION must name the offending SHA prefix; got: {result}"


# ---------------------------------------------------------------------------
# _sha_covered prefix-match rules (item 15: real prefix-match assertions)
# ---------------------------------------------------------------------------

def test_sha_covered_seven_char_entry_matches_full_sha():
    """A 7-char ledger entry covers a full 40-char commit SHA (prefix match)."""
    from skills._shared.hot_patch_ledger import _sha_covered  # noqa: PLC0415

    entries = [{"sha": "abc1234"}]
    full_sha = "abc1234" + "0" * 33
    assert _sha_covered(full_sha, entries), "7-char entry must cover matching full SHA"


def test_sha_covered_nonmatching_fails():
    """A 7-char ledger entry does NOT cover a SHA that doesn't start with it."""
    from skills._shared.hot_patch_ledger import _sha_covered  # noqa: PLC0415

    entries = [{"sha": "abc1234"}]
    other_sha = "fffff1234" + "0" * 31
    assert not _sha_covered(other_sha, entries), "Non-matching SHA must not be covered"


def test_sha_covered_short_entry_never_matches():
    """A ledger entry shorter than 7 chars never counts as a match."""
    from skills._shared.hot_patch_ledger import _sha_covered  # noqa: PLC0415

    entries = [{"sha": "abc12"}]  # only 5 chars
    full_sha = "abc12" + "0" * 35
    assert not _sha_covered(full_sha, entries), "Entry < 7 chars must never match"


# ---------------------------------------------------------------------------
# Missing-ledger VIOLATION (item 16)
# ---------------------------------------------------------------------------

def test_ledger_missing_violation_when_trailered_commits_exist(hot_patch_repo):
    """CLI emits VIOLATION ledger-missing immediately when ledger absent + trailered commits.

    The ledger-missing violation is emitted NO-GRACE (before the overdue window
    expires), distinguishing it from ledger-overdue.
    """
    repo = hot_patch_repo["repo"]

    # Point ledger-file to a path that doesn't exist
    absent_ledger = str(repo / "nonexistent-hot-patches.md")

    # Use same-day now so overdue check would NOT fire (within window)
    # — ledger-missing must still fire immediately
    result = subprocess.run(
        ["python3", str(REPO_ROOT / "skills/_shared/hot_patch_check.py"),
         "--repo-root", str(repo),
         "--ledger-file", absent_ledger,
         "--now", "2026-06-12T01:00:00Z"],  # same-day, no overdue
        capture_output=True, text=True,
    )
    assert result.returncode == 1, (
        f"Must exit 1 when ledger missing + trailered commits (no-grace); "
        f"stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "ledger-missing" in combined, (
        f"Must emit ledger-missing VIOLATION (no-grace); got {combined!r}"
    )


# ---------------------------------------------------------------------------
# _SHA40_RE token-validation guard (fix #15: minor)
# ---------------------------------------------------------------------------

def test_sha40_re_filters_malformed_git_log_lines():
    """_SHA40_RE guard filters out non-40-hex tokens from git log output.

    Verifies against an if-False mutant: removing the guard would admit
    garbage tokens as SHAs, potentially causing downstream failures.
    """
    from skills._shared.hot_patch_ledger import _SHA40_RE  # noqa: PLC0415

    # Valid 40-char hex SHA — must match
    valid_sha = "a" * 40
    assert _SHA40_RE.match(valid_sha), "40-char hex SHA must match _SHA40_RE"

    # Non-40-char strings — must NOT match (malformed git-log tokens)
    for bad in ["abc1234", "not-a-sha", "G" * 40, "a" * 39, "a" * 41, ""]:
        assert not _SHA40_RE.match(bad), (
            f"Malformed token {bad!r} must NOT match _SHA40_RE"
        )


def test_trailered_commits_skips_malformed_sha_line(tmp_path):
    """_trailered_commits_on_head skips lines whose SHA token fails _SHA40_RE.

    This pins that the guard is active: a line with a non-40-char token is
    silently dropped rather than causing a crash or a false-positive match.
    """
    from unittest.mock import patch  # noqa: PLC0415
    from skills._shared import hot_patch_ledger  # noqa: PLC0415

    # Simulate git log output where the first token is garbage (not 40 hex)
    fake_log_output = (
        "not-a-sha hot-patch: something\n"          # malformed → skip
        + ("b" * 40) + "\n"                         # valid SHA but no trailer → skip
        + ("c" * 40) + " hot-patch: real\n"         # valid SHA with trailer → keep
    )

    import subprocess as sp  # noqa: PLC0415

    class FakeResult:
        returncode = 0
        stdout = fake_log_output
        stderr = ""

    with patch.object(sp, "run", return_value=FakeResult()):
        result = hot_patch_ledger._trailered_commits_on_head("/fake/repo")

    assert result == ["c" * 40], (
        f"Only the valid 40-char SHA with a trailer must be returned; got {result}"
    )


# ---------------------------------------------------------------------------
# Fix 4: near-miss diagnostic — indented entries produce a warning
# ---------------------------------------------------------------------------

def test_parse_ledger_warns_on_indented_entry():
    """parse_ledger emits a warning for an indented entry that looks valid but
    is not anchored at column 0 — so it is not parsed as a real entry.

    Probe-verify: '  - abc1234 | ...' (indented by two spaces) matches
    LEDGER_ENTRY_RE when stripped but raw_line does not start with '-',
    so parse_ledger must warn 'indented ledger entry not parsed'.
    """
    import warnings  # noqa: PLC0415
    from skills._shared.hot_patch_ledger import parse_ledger  # noqa: PLC0415

    indented_entry = (
        "  - abc1234 | 2026-06-13 | trigger: fix teardown | broke: x | fix: y | touched: z"
    )
    text = (
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"{indented_entry}\n"
    )
    import io, sys  # noqa: PLC0415
    buf = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = buf
    try:
        entries = parse_ledger(text)
    finally:
        sys.stderr = old_stderr
    stderr_out = buf.getvalue()
    assert entries == [], f"Indented entry must not be parsed; got {entries}"
    assert "indented ledger entry not parsed" in stderr_out, (
        f"Must warn about indented entry; stderr={stderr_out!r}"
    )
