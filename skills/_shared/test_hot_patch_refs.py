"""test_hot_patch_refs.py — obligation-scan ref resolution (Task 4.7).

Covers the `prefer="local"` obligation scan and the unresolvable-default-branch
degrade under `--ledger-only`:

  - A trailered commit on local `main` that is one commit AHEAD of
    `origin/main` is reported by the obligation scan — the scan uses
    `default_ref(repo, prefer="local")` (Task 4.6), so the local ref wins over
    `origin/main` and the not-yet-pushed commit is still an obligation.
  - When no default-branch ref resolves at all (an unborn repo on a
    non-default branch name), `--ledger-only` warns "trailered-commit scan
    skipped (degraded clone)" and exits 0 — never blocks.

House rules: real tmp_path git repos, GIT_* env scrubbed (autouse fixture,
test_hot_patch_ledger_base.py's shape) plus an explicit CLEAN_ENV carrying
author/committer identity for every git subprocess. Stdlib + pytest only.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV["GIT_AUTHOR_NAME"] = "fixture"
CLEAN_ENV["GIT_AUTHOR_EMAIL"] = "fixture@test"
CLEAN_ENV["GIT_COMMITTER_NAME"] = "fixture"
CLEAN_ENV["GIT_COMMITTER_EMAIL"] = "fixture@test"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    hot_patch_ledger.py's resolver runs git via subprocess inheriting
    os.environ, so the scrub must hold here, not only in the `env=` passed to
    the fixture builds (test_hot_patch_ledger_base.py's pattern)."""
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


def _sha(repo: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                            capture_output=True, text=True, check=True, env=CLEAN_ENV)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# prefer="local" — the local ref one commit ahead of origin/main is the
# obligation target (Task 4.6 resolver, keep prefer="local").
# ---------------------------------------------------------------------------

def test_local_ahead_of_origin_obligation_scan_reports(tmp_path):
    """A trailered commit on local `main` (one ahead of `origin/main`) with no
    ledger entry is reported by the obligation scan. The scan uses
    prefer="local", so the local ref is the target and the not-yet-pushed
    commit is still an obligation."""
    from skills._shared.hot_patch_ledger import check_ledger_coverage  # noqa: PLC0415

    repo = tmp_path / "repo"
    origin = tmp_path / "origin.git"
    _init_repo(repo)
    _run(["init", "-q", "--bare", str(origin)], tmp_path)
    _run(["remote", "add", "origin", str(origin)], repo)
    _run(["push", "-q", "-u", "origin", "main"], repo)

    # One trailered commit ahead of origin/main (dated past the deadline).
    (repo / "fix.py").write_text("# fix\n", encoding="utf-8")
    _run(["add", "fix.py"], repo)
    _run(["commit", "--trailer", "hot-patch: refs test", "-m", "Hotfix: refs"], repo,
         extra_env={"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
                    "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"})
    sha = _sha(repo)

    ledger_text = "# Hot-patch ledger — append-only\n\n<!-- entries below -->\n"
    result = check_ledger_coverage(repo=str(repo), ledger_text=ledger_text,
                                   now_iso="2099-01-01T00:00:00Z")
    assert len(result) >= 1, (
        f"Local-main commit ahead of origin must be an obligation; got {result}"
    )
    assert sha[:7] in " ".join(result), (
        f"VIOLATION must name the offending SHA prefix; got {result}"
    )


# ---------------------------------------------------------------------------
# Unresolvable default branch — `--ledger-only` degrades to warn + exit 0
# ---------------------------------------------------------------------------

def test_unresolvable_default_branch_ledger_only_warns_and_exits_0(tmp_path):
    """No main/master/origin resolves (unborn repo on a non-default branch)
    → `--ledger-only` warns 'trailered-commit scan skipped (degraded clone)'
    and exits 0 — never blocks."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["init", "-q", "-b", "feature"], repo)  # unborn: no commit at all

    with pytest.warns(UserWarning, match="trailered-commit scan skipped"):
        code = hot_patch_check.main([
            "--repo-root", str(repo),
            "--ledger-only",
            "--now", "2099-01-01T00:00:00Z",
        ])
    assert code == 0, (
        f"--ledger-only must exit 0 on a degraded clone (warn, not block); got {code}"
    )


# ---------------------------------------------------------------------------
# `--ledger-only` honours `--ledger-file` (the same ledger source as full mode)
# ---------------------------------------------------------------------------

def test_ledger_only_reads_ledger_file(tmp_path):
    """An entry only in the `--ledger-file` ledger discharges the obligation
    under `--ledger-only`; without it the same commit is overdue (exit 1)."""
    from skills._shared import hot_patch_check  # noqa: PLC0415

    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "fix.py").write_text("# fix\n", encoding="utf-8")
    _run(["add", "fix.py"], repo)
    _run(["commit", "--trailer", "hot-patch: ledger-file", "-m", "Hotfix: lf"], repo,
         extra_env={"GIT_COMMITTER_DATE": "2026-06-15T00:00:00Z",
                    "GIT_AUTHOR_DATE": "2026-06-15T00:00:00Z"})
    sha = _sha(repo)
    ledger = tmp_path / "hot-patches.md"
    ledger.write_text(
        "# Hot-patch ledger — append-only\n\n<!-- entries below -->\n"
        f"- {sha[:12]} | 2026-06-15 | trigger: t | broke: b | fix: f | touched: fix.py |\n",
        encoding="utf-8")
    argv = ["--repo-root", str(repo), "--ledger-only", "--now", "2099-01-01T00:00:00Z"]

    assert hot_patch_check.main(argv) == 1
    assert hot_patch_check.main(argv + ["--ledger-file", str(ledger)]) == 0
