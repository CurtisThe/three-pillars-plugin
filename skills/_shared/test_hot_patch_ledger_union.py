"""test_hot_patch_ledger_union.py — ref-union ledger read + `--grep` prefilter (Task 4.7).

Covers:
  - `--ledger-only` reads the ledger at BOTH verifying default refs unioned with
    the work tree: an entry that exists only on local `main` discharges an
    obligation when run from a stale `tp/x` worktree that has no ledger file; an
    entry only on `origin/main` likewise; neither → the overdue failure.
  - The trailered-commit scan prefilters with a case-insensitive `--grep`
    (admitting `HOT-PATCH : x`) then confirms by the trailer parse: mixed-case
    `Hot-Patch:` and `HOT-PATCH : x` trailers are found by BOTH the ledger
    coverage scan (arm a) and the full-mode scan (arm b) (#37); a non-trailer
    mid-message `hot-patch:` line followed by another paragraph is NOT counted.

House rules: real tmp_path git repos, GIT_* env scrubbed (autouse fixture,
test_hot_patch_ledger_base.py's shape) plus an explicit CLEAN_ENV carrying
author/committer identity for every git subprocess. Stdlib + pytest only.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

LEDGER_RELPATH = "three-pillars-docs/tp-designs/orchestration/hot-patches.md"

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    hot_patch_ledger.py runs git via subprocess inheriting os.environ, so the
    scrub must hold here, not only in the `env=` passed to the fixture builds
    (test_hot_patch_ledger_base.py's pattern)."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _run(args: list[str], cwd: Path, extra_env: dict | None = None) -> None:
    """`git <args>` under `cwd`, with CLEAN_ENV (+ optional overrides)."""
    env = dict(CLEAN_ENV)
    if extra_env:
        env.update(extra_env)
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=env,
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _init_repo(repo: Path, branch: str = "main") -> None:
    repo.mkdir()
    _run(["init", "-q", "-b", branch], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _run(["add", "README.md"], repo)
    _run(["commit", "-q", "-m", "init"], repo)


def _trailered(repo: Path, filename: str = "fix.py", trailer: str = "hot-patch: union test",
               date: str = "2026-06-15T00:00:00Z") -> str:
    """One trailered commit on the current branch; return its full SHA."""
    (repo / filename).write_text("# fix\n", encoding="utf-8")
    _run(["add", filename], repo)
    _run(["commit", "--trailer", trailer, "-m", "Hotfix: union test"], repo,
         extra_env={"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date})
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                            capture_output=True, text=True, check=True, env=CLEAN_ENV)
    return result.stdout.strip()


def _sha(repo: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                            capture_output=True, text=True, check=True, env=CLEAN_ENV)
    return result.stdout.strip()


def _write_ledger_entry(repo: Path, sha: str) -> None:
    """Write the canonical ledger with a single entry for `sha`, commit it."""
    ledger_dir = repo / LEDGER_RELPATH
    ledger_dir.parent.mkdir(parents=True, exist_ok=True)
    ledger_dir.write_text(
        "# Hot-patch ledger — append-only\n\n"
        "<!-- entries below -->\n"
        f"- {sha} | 2026-06-15 | trigger: union test | broke: x | fix: y | touched: {repo.name}\n",
        encoding="utf-8",
    )
    _run(["add", LEDGER_RELPATH], repo)
    _run(["commit", "-q", "-m", "ledger: entry"], repo)


# ---------------------------------------------------------------------------
# Union ledger read — an entry on a ref we are not checked out of discharges
# ---------------------------------------------------------------------------

def test_entry_on_local_main_discharges_from_stale_worktree(tmp_path):
    """Entry only on `main`; commit checked out from a stale `tp/x` worktree
    with NO ledger file → `--ledger-only` passes (the local-main ledger is
    part of the union)."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    main = tmp_path / "main"
    _init_repo(main)
    sha = _trailered(main)
    _write_ledger_entry(main, sha)

    worktree = tmp_path / "stale-wt"
    _run(["worktree", "add", "-q", "-b", "tp/x", str(worktree), "main"], main)

    # The worktree's default branch (tp/x) resolves and has NO ledger file;
    # main and origin/main are not the resolved branch. The union must still
    # find the entry on main.
    code = hot_patch_check.main([
        "--repo-root", str(worktree),
        "--ledger-only",
        "--now", "2099-01-01T00:00:00Z",
    ])
    assert code == 0, (
        f"--ledger-only must pass: entry on local main discharges the obligation "
        f"even from a stale worktree with no ledger file; got exit {code}"
    )


def test_entry_only_on_origin_main_discharges(tmp_path):
    """Entry only on `origin/main` (absent locally and in the work tree) →
    `--ledger-only` passes (the origin-main ledger is part of the union)."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    main = tmp_path / "main"
    _init_repo(main)
    sha = _trailered(main)
    origin = tmp_path / "origin.git"
    _run(["init", "-q", "--bare", str(origin)], tmp_path)
    _run(["remote", "add", "origin", str(origin)], main)
    _run(["push", "-q", "-u", "origin", "main"], main)
    _run(["symbolic-ref", "HEAD", "refs/heads/main"], origin)  # origin/HEAD -> main
    _write_ledger_entry(main, sha)
    _run(["push", "-q", "origin", "main"], main)  # origin/main now has the entry

    clone = tmp_path / "clone"
    _run(["clone", "-q", str(origin), str(clone)], tmp_path)  # checks out main (has entry)
    # Now make local main BEHIND origin/main: the work tree's ledger file is
    # from the older commit (no entry), but origin/main still holds the entry.
    _run(["reset", "-q", "--hard", "origin/main~1"], clone)
    code = hot_patch_check.main([
        "--repo-root", str(clone),
        "--ledger-only",
        "--now", "2099-01-01T00:00:00Z",
    ])
    assert code == 0, (
        f"--ledger-only must pass: entry on origin/main is part of the union "
        f"even though the local ledger file lacks it; got exit {code}"
    )


def test_entry_nowhere_fails(tmp_path):
    """Neither the work tree nor any default ref carries the entry → the
    overdue failure (exit 1)."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    repo = tmp_path / "repo"
    _init_repo(repo)
    _trailered(repo)  # no ledger entry anywhere

    code = hot_patch_check.main([
        "--repo-root", str(repo),
        "--ledger-only",
        "--now", "2099-01-01T00:00:00Z",
    ])
    assert code == 1, (
        f"--ledger-only must fail (overdue) when the entry is nowhere; got exit {code}"
    )


# ---------------------------------------------------------------------------
# `--grep` prefilter + trailer confirm: mixed-case / loose trailers are found,
# a non-trailer mid-message line is not
# ---------------------------------------------------------------------------

def _build_mixed_case_repo(tmp_path: Path) -> tuple[Path, list[str]]:
    """Repo with one trailered commit carrying a mixed-case / loose
    `HOT-PATCH :` trailer, and one non-trailer `hot-patch:` mid-message line.

    Returns (repo, [trailered_sha, non_trailer_sha])."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    dated = {"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
             "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"}

    # A real trailered commit with a loose all-caps trailer (admitted by the
    # case-insensitive --grep prefilter, confirmed by the trailer parse).
    (repo / "real.py").write_text("# real\n", encoding="utf-8")
    _run(["add", "real.py"], repo)
    _run(["commit", "--trailer", "HOT-PATCH : union loose", "-m", "Hotfix: loose"], repo,
         extra_env=dated)
    trailered_sha = _sha(repo)

    # A non-trailer commit: `hot-patch:` line mid-message, another paragraph
    # after it (the trailer parse must NOT confirm it).
    (repo / "bogus.py").write_text("# bogus\n", encoding="utf-8")
    _run(["add", "bogus.py"], repo)
    _run(["commit", "-m", "Hotfix: bogus\n\nhot-patch: not a trailer\n\nanother paragraph"], repo,
         extra_env=dated)
    return repo, [trailered_sha, _sha(repo)]


def _run_check(repo: Path, *flags: str) -> tuple[int, str]:
    """In-process hot_patch_check.main; return (exit code, captured stdout)."""
    import contextlib, io  # noqa: PLC0415
    from skills._shared import hot_patch_check  # noqa: PLC0415
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = hot_patch_check.main(["--repo-root", str(repo), *flags,
                                    "--now", "2099-01-01T00:00:00Z"])
    return code, buf.getvalue()


def test_loose_trailer_found_by_ledger_scan_arm_a(tmp_path):
    """A `HOT-PATCH : x` trailer (arm a) is discovered — the prefilter+confirm
    pipeline admits the loose casing; the overdue failure names the SHA."""
    repo, [trailered_sha, _non] = _build_mixed_case_repo(tmp_path)
    code, out = _run_check(repo, "--ledger-only")
    assert code == 1, "loose-cased trailered commit with no entry must be overdue"
    assert trailered_sha[:7] in out, (
        f"loose-cased trailered commit must be flagged; got {out!r}"
    )


def test_mixed_case_hot_patch_trailer_found(tmp_path):
    """A `Hot-Patch: x` trailer is discovered by the ledger scan (arm a)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    dated = {"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
             "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"}
    (repo / "mix.py").write_text("# mix\n", encoding="utf-8")
    _run(["add", "mix.py"], repo)
    _run(["commit", "--trailer", "Hot-Patch: mixed case", "-m", "Hotfix: mixed"], repo,
         extra_env=dated)
    sha = _sha(repo)

    code, out = _run_check(repo, "--ledger-only")
    assert code == 1, "mixed-case trailered commit with no entry must be overdue"
    assert sha[:7] in out, f"mixed-case trailered commit must be flagged; got {out!r}"


def test_mixed_case_trailers_found_by_full_mode_scan(tmp_path):
    """#37 full mode: the loose `HOT-PATCH :` and `Hot-Patch:` trailers are
    discovered by the arm (b) scan (discharges cleanly with entries present)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    dated = {"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
             "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"}
    # Two trailered commits, both mixed-case / loose casing.
    (repo / "a.py").write_text("# a\n", encoding="utf-8")
    _run(["add", "a.py"], repo)
    _run(["commit", "--trailer", "HOT-PATCH : loose", "-m", "Hotfix: a"], repo, extra_env=dated)
    sha_a = _sha(repo)
    (repo / "b.py").write_text("# b\n", encoding="utf-8")
    _run(["add", "b.py"], repo)
    _run(["commit", "--trailer", "Hot-Patch: mixed", "-m", "Hotfix: b"], repo, extra_env=dated)
    sha_b = _sha(repo)

    # Ledger entries for BOTH → arm (a) discharges; arm (b) finds both trailered
    # commits and checks them (no excluded path, small diff) → full mode exits 0.
    _write_ledger_entry(repo, sha_a)
    ledger = repo / LEDGER_RELPATH
    ledger.write_text(ledger.read_text(encoding="utf-8") +
                      f"- {sha_b} | 2026-06-15 | trigger: mixed | broke: x | fix: y | touched: b.py\n",
                      encoding="utf-8")
    _run(["add", LEDGER_RELPATH], repo)
    _run(["commit", "-q", "-m", "ledger: b"], repo)

    code, out = _run_check(repo)
    assert code == 0, (
        f"full mode must exit 0 for mixed-case trailered commits with entries; got {out!r}"
    )


def test_non_trailer_hot_patch_line_not_counted(tmp_path):
    """A mid-message `hot-patch:` line followed by another paragraph is NOT a
    trailer: it must not be counted by the ledger scan (arm a) nor the
    full-mode scan (arm b)."""
    repo, [trailered, non_trailer] = _build_mixed_case_repo(tmp_path)
    _write_ledger_entry(repo, trailered)  # cover the REAL one; non-trailer is the odd one out

    code, out = _run_check(repo, "--ledger-only")  # arm (a)
    assert code == 0, f"non-trailer line must not be overdue; got {out!r}"
    assert non_trailer[:7] not in out, f"non-trailer must not be counted (arm a); got {out!r}"

    code, out = _run_check(repo)  # arm (b) full mode
    assert code == 0, f"non-trailer line must not be scanned in full mode; got {out!r}"
    assert non_trailer[:7] not in out, f"non-trailer must not be counted (arm b); got {out!r}"
