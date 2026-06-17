"""test_hot_patch_nul_paths.py — NUL-delimited path tests (PR #82 rounds 4–5).

Pins the -z fix: git never C-quotes paths in -z mode, so double-quote and
literal-backslash filenames arrive verbatim and are correctly matched against
EXCLUDED_PREFIXES / FRAMEWORK_PREFIXES.

Mutation-verify: reverting to plain --name-only (even with quotepath=false)
produces C-quoted output like '"skills\\\\sub.py"' or '".three-pillars/a\\"b.txt"'
which does NOT match the prefix checks — so these tests FAIL without -z.

Split from test_hot_patch_anomaly.py to stay under the 500-line cap.
"""
from __future__ import annotations

import os
import subprocess

import pytest

_GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "fixture",
    "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture",
    "GIT_COMMITTER_EMAIL": "fixture@test",
}

_AFTER_ENV_DATES = {
    "GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
    "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z",
}

_BEFORE_ENV_DATES = {
    "GIT_COMMITTER_DATE": "2026-06-10T00:00:00Z",
    "GIT_AUTHOR_DATE": "2026-06-10T00:00:00Z",
}


def _make_env(**overrides: str) -> dict:
    env = dict(os.environ)
    env.update(_GIT_IDENTITY_ENV)
    env.update(overrides)
    return env


@pytest.fixture
def nul_repo(tmp_path):
    """Minimal git repo with one pre-baseline commit; used by all nul-path tests."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _make_env(**_BEFORE_ENV_DATES)

    subprocess.run(["git", "init", "-b", "master"], cwd=str(repo),
                   check=True, capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "fixture@test"],
                   cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "fixture"],
                   cwd=str(repo), check=True, capture_output=True)

    (repo / "README.md").write_text("init\n")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    return repo


# ---------------------------------------------------------------------------
# Double-quote path: check_exclusions (trailered commit on .three-pillars/)
# ---------------------------------------------------------------------------

def test_double_quote_path_caught_by_check_exclusions(nul_repo):
    """check_exclusions catches a trailered commit touching .three-pillars/a"b.txt.

    Without -z, git C-quotes the path as '.three-pillars/a\\"b.txt' (wrapped in
    double-quotes), which does NOT match the '.three-pillars/' prefix check.
    With -z the path arrives verbatim and the prefix match succeeds.

    Mutation-verify: reverting _commit_files to plain --name-only (with or without
    quotepath=false) causes this test to FAIL because the C-quoted string begins with
    a literal '"' character, not '.'.
    """
    from skills._shared.hot_patch_check import check_exclusions  # noqa: PLC0415

    repo = nul_repo
    env = _make_env()  # default (non-backdated) for trailered commit

    (repo / ".three-pillars").mkdir(exist_ok=True)
    # File whose name contains a double-quote — triggers C-quoting without -z.
    quoted_file = repo / ".three-pillars" / 'a"b.txt'
    quoted_file.write_text("trigger\n")
    subprocess.run(["git", "add", '.three-pillars/a"b.txt'], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: double-quote test",
         "-m", 'Hotfix: double-quote path'],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    violations = check_exclusions(sha=sha, repo=str(repo))
    assert len(violations) >= 1, (
        "check_exclusions must catch .three-pillars/a\"b.txt "
        "(double-quote in filename); got no violations — likely -z was reverted"
    )
    assert any(".three-pillars/" in v for v in violations), (
        f"Violation must mention the .three-pillars/ prefix; got {violations}"
    )


# ---------------------------------------------------------------------------
# Literal-backslash path: check_anomaly (post-baseline non-merge commit)
# ---------------------------------------------------------------------------

def test_backslash_path_flagged_by_check_anomaly(nul_repo):
    r"""check_anomaly flags a post-baseline commit touching skills\sub.py.

    Without -z, git C-quotes the literal-backslash filename as '"skills\\sub.py"'
    (with surrounding double-quotes), which does NOT start with 'skills/' so the
    anomaly scan misses it.  With -z the path is 'skills\\sub.py' verbatim; after
    replace('\\', '/') normalization it becomes 'skills/sub.py' and the prefix
    'skills/' matches.

    Mutation-verify: reverting _commit_files_for_anomaly to plain --name-only
    causes this test to FAIL because the C-quoted token starts with '"'.
    """
    from skills._shared.hot_patch_ledger import check_anomaly  # noqa: PLC0415

    repo = nul_repo
    env = _make_env(**_AFTER_ENV_DATES)

    (repo / "skills").mkdir(exist_ok=True)
    # Filename with a literal backslash — Linux allows it; git C-quotes without -z.
    backslash_file = repo / "skills" / "sub.py"
    # Use git update-index to stage under a backslash path in the index so git
    # records the unusual name, while we write the actual file normally.
    backslash_file.write_text("# backslash name test\n")
    # Commit via subprocess so git records the file; the backslash is in the PATH
    # within git's index — create a file literally named with backslash via shell.
    subprocess.run(["git", "add", "skills/sub.py"], cwd=str(repo), check=True)
    # Now create the actual backslash-named entry via update-index
    # Write content to a temp blob, then record it in the index under the unusual name.
    blob_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input="# backslash name\n",
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    # Remove the clean path and add the backslash path
    subprocess.run(
        ["git", "rm", "--cached", "skills/sub.py"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo",
         f"100644,{blob_hash},skills\\sub.py"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "post-baseline backslash path"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )

    violations = check_anomaly(repo=str(repo))
    assert len(violations) >= 1, (
        r"check_anomaly must flag a post-baseline commit touching skills\sub.py "
        "(literal backslash in name); got no violations — likely -z was reverted"
    )
    assert any("anomaly" in v for v in violations), (
        f"Violation must be anomaly type; got {violations}"
    )


# ---------------------------------------------------------------------------
# Mutation-verify: plain --name-only silently misses C-quoted double-quote paths
# ---------------------------------------------------------------------------

def test_mutation_verify_plain_name_only_misses_double_quote_path(nul_repo):
    """Regression guard: plain --name-only (no -z) silently misses double-quote paths.

    This test documents why -z is required.  It simulates what the OLD code did:
    calls git show --name-only without -z (even with quotepath=false) and asserts
    that the C-quoted output does NOT start with '.three-pillars/' — i.e., the
    prefix match would fail and the path would be silently missed.

    If this test ever starts failing (the C-quoted output DID match), revisit the
    approach — it would mean git changed its quoting behaviour for ASCII special chars.
    """
    repo = nul_repo
    env = _make_env()

    (repo / ".three-pillars").mkdir(exist_ok=True)
    quoted_file = repo / ".three-pillars" / 'x"y.txt'
    quoted_file.write_text("mutation guard\n")
    subprocess.run(["git", "add", '.three-pillars/x"y.txt'], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", "mutation guard commit"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Simulate old code: plain --name-only with quotepath=false (no -z).
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "core.quotepath=false",
         "show", "--name-only", "--no-renames", "--format=", sha],
        capture_output=True, text=True, check=True,
    )
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    # The C-quoted output for a double-quote path starts with '"', not '.'
    assert all(not ln.startswith(".three-pillars/") for ln in lines), (
        "Mutation-verify unexpectedly passed: git returned an unquoted path "
        "for a double-quote filename without -z.  Review the -z requirement."
    )
    # Confirm -z gives the verbatim path that DOES match the prefix
    result_z = subprocess.run(
        ["git", "-C", str(repo),
         "show", "--name-only", "--no-renames", "-z", "--format=", sha],
        capture_output=True, text=True, check=True,
    )
    paths_z = [p for p in result_z.stdout.split("\0") if p.strip()]
    assert any(p.startswith(".three-pillars/") for p in paths_z), (
        f"With -z, .three-pillars/ prefix must be found; got {paths_z}"
    )


# ---------------------------------------------------------------------------
# Round-5: whitespace-name diff-cap pin (emptiness-only filter)
# ---------------------------------------------------------------------------

def test_whitespace_only_filename_counted_by_check_diff_cap(nul_repo):
    """A 300-line file named entirely of spaces counts against the diff cap.

    _numstat splits each NUL-terminated record on TAB with maxsplit=2.  When
    the path token is whitespace-only (e.g. "   "), the record looks like
    "300\\t0\\t   ".  With the old record.strip() mutation the trailing spaces
    are consumed so the record becomes "300\\t0" — only 2 TAB-parts — and the
    row is silently dropped (len(parts) < 3 → continue), hiding the violation.
    With the emptiness-only filter (if not record) the record is untouched and
    the path "   " is kept verbatim; the file counts toward the total.

    Mutation-verify: restoring record.strip() in _numstat makes this test FAIL
    because the whitespace path disappears and no violation is raised.
    """
    from skills._shared.hot_patch_check import check_diff_cap  # noqa: PLC0415

    repo = nul_repo
    env = _make_env()

    # Produce a 300-line blob and register it under a spaces-only path via
    # update-index so the filesystem never needs to hold the unusual name.
    content = ("x\n" * 300)
    blob_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=content,
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo",
         f"100644,{blob_hash},   "],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: whitespace-name test",
         "-m", "Hotfix: whitespace-only filename"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert len(violations) >= 1, (
        "check_diff_cap must flag a 300-line file named '   ' (spaces only); "
        "got no violations — _numstat likely strips records, discarding the path"
    )
    assert any("diff-cap" in v for v in violations), (
        f"Violation must be diff-cap type; got {violations}"
    )


def test_backslash_alias_ledger_path_flagged_by_check_diff_cap(nul_repo):
    r"""A 300-line file named with backslashes is NOT exempt from the diff cap.

    LEDGER_RELPATH uses forward slashes.  A file indexed as
    "three-pillars-docs\tp-designs\orchestration\hot-patches.md" (backslashes)
    normalizes to the same string after replace('\\', '/'), so the old code
    incorrectly exempted it.  With the raw-path exemption only a byte-identical
    path (all forward slashes) is exempt; the backslash alias counts toward
    the cap total and triggers a violation for 300 lines.

    Mutation-verify: reverting check_diff_cap to compare path_norm (normalized)
    against LEDGER_RELPATH makes this test FAIL because the backslash path
    normalizes to LEDGER_RELPATH and the 300 lines are silently exempted.
    """
    from skills._shared.hot_patch_check import check_diff_cap, LEDGER_RELPATH  # noqa: PLC0415

    repo = nul_repo
    env = _make_env()

    # Build the backslash-aliased ledger path by replacing forward slashes with
    # backslashes — this is a distinct filename on Linux (backslash is a valid
    # path character) but normalizes to LEDGER_RELPATH under replace('\\', '/').
    backslash_path = LEDGER_RELPATH.replace("/", "\\")
    assert backslash_path != LEDGER_RELPATH, "sanity: backslash path must differ"

    content = ("z\n" * 300)
    blob_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=content,
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo",
         f"100644,{blob_hash},{backslash_path}"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: backslash-alias ledger test",
         "-m", "Hotfix: backslash-alias ledger path"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert len(violations) >= 1, (
        f"check_diff_cap must flag a 300-line file named {backslash_path!r} "
        "(backslash alias of ledger path); got no violations — exemption likely "
        "compares the normalized path, incorrectly matching LEDGER_RELPATH"
    )
    assert any("diff-cap" in v for v in violations), (
        f"Violation must be diff-cap type; got {violations}"
    )


def test_trailing_space_ledger_path_not_exempted(nul_repo):
    """A file named like hot-patches.md but with a trailing space is NOT exempt.

    LEDGER_RELPATH is matched by exact equality in check_diff_cap.  A file
    named 'three-pillars-docs/tp-designs/orchestration/hot-patches.md '
    (trailing space) must NOT match and must count toward the cap total.

    With the old record.strip() mutation the TAB-record
    "300\\t0\\t<LEDGER_RELPATH> " has its trailing space stripped so path
    becomes LEDGER_RELPATH exactly — the row is silently exempted and no
    violation is raised.  With the fix the trailing space is preserved, the
    exact-equality check fails, and the 300 lines count toward the total,
    triggering the cap.

    Mutation-verify: restoring record.strip() in _numstat makes this test FAIL
    because the trailing-space path is trimmed to the real ledger path and
    the file is incorrectly exempted.
    """
    from skills._shared.hot_patch_check import check_diff_cap, LEDGER_RELPATH  # noqa: PLC0415

    repo = nul_repo
    env = _make_env()

    # Path is the real ledger path plus one trailing space.
    fake_ledger_path = LEDGER_RELPATH + " "

    content = ("y\n" * 300)
    blob_hash = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        input=content,
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "update-index", "--add", "--cacheinfo",
         f"100644,{blob_hash},{fake_ledger_path}"],
        cwd=str(repo), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "commit",
         "--trailer", "hot-patch: trailing-space ledger test",
         "-m", "Hotfix: trailing-space ledger path"],
        cwd=str(repo), check=True, capture_output=True, env=env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    ).stdout.strip()

    violations = check_diff_cap(sha=sha, repo=str(repo))
    assert len(violations) >= 1, (
        f"check_diff_cap must flag a 300-line file named {fake_ledger_path!r} "
        "(trailing space — not the real ledger path); got no violations — "
        "_numstat likely strips the record, matching LEDGER_RELPATH by accident"
    )
    assert any("diff-cap" in v for v in violations), (
        f"Violation must be diff-cap type; got {violations}"
    )
