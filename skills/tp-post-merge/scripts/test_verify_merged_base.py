"""Tests for verify_merged.py resolving --base when omitted (Task 4.4).

Parametrised main/master fixtures — split out of test_verify_merged.py (past
the soft cap) per the consumer-repo-parity plan. Covers `main()` with no
`--base` resolving via the shared default-branch resolver
(`skills/_shared/default_branch.py`), and the tp-post-merge SKILL.md no-arg
scan step naming default_branch.py.

House rules: real tmp_path git repos (bare origin + clone); GIT_* env scrubbed
and HOME isolated (both for the fixture builds and, via the autouse fixture,
for the in-process git calls the resolver makes); author/committer identity
set explicitly. No test pins prose wording. Stdlib + pytest only.

Run with: pytest skills/tp-post-merge/scripts/test_verify_merged_base.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from verify_merged import check_archive_on_base, main  # noqa: E402

# GIT_* scrubbed + identity set explicitly so the fixture builds (and the
# resolver's in-process git calls, via the autouse fixture below) never see
# an inherited GIT_CONFIG_* or ambient user config.
_CLEAN = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_CLEAN.update({"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
               "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME in the ambient env.

    `resolve_default_branch` (delegated to from `verify_merged._resolve_base`)
    runs git via subprocess inheriting `os.environ`, so the scrub must hold
    here, not only in the `env=` passed to the fixture builds."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, env=_CLEAN,
                   capture_output=True, text=True)


def _bare_origin_with_branch(tmp_path: Path, branch: str) -> Path:
    """A bare origin holding `branch` (one commit) with HEAD set, so a clone
    gains `<branch>`, `origin/<branch>` and `origin/HEAD -> origin/<branch>`."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _git(["init", "-q", "--bare", "-b", branch], bare)
    seed = tmp_path / "seed"
    seed.mkdir()
    seed.joinpath("README.md").write_text("# fixture\n", encoding="utf-8")
    _git(["init", "-q", "-b", branch], seed)
    _git(["add", "-A"], seed)
    _git(["commit", "-q", "-m", "seed"], seed)
    _git(["remote", "add", "origin", str(bare)], seed)
    _git(["push", "-q", "origin", branch], seed)
    _git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], bare)
    return bare


def _clone(tmp_path: Path, bare: Path) -> Path:
    work = tmp_path / "work"
    _git(["clone", "-q", str(bare), str(work)], tmp_path)
    return work


def _add_archive_and_push(repo: Path, design: str, branch: str) -> None:
    """Commit the design archive on `repo`'s current branch and push it."""
    archive_dir = repo / "three-pillars-docs" / "completed-tp-designs" / design
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.joinpath("design.md").write_text(f"# {design} design", encoding="utf-8")
    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", f"Complete design: {design}"], repo)
    _git(["push", "-q", "origin", branch], repo)


# ---------------------------------------------------------------------------
# main() with no --base resolves the fixture's default branch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("branch", ["main", "master"])
def test_main_no_base_resolves_default_branch(tmp_path: Path, branch: str) -> None:
    """main() with no --base resolves the repo's default branch (main or
    master, via origin/HEAD on a clone) and reports merged=True off the
    archive present there — the shape the post-merge no-arg scan relies on."""
    bare = _bare_origin_with_branch(tmp_path, branch)
    work = _clone(tmp_path, bare)
    _add_archive_and_push(work, "my-design", branch)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--repo", str(work), "--design", "my-design", "--json"])
    data = json.loads(buf.getvalue())

    assert rc == 0
    assert data["merged"] is True
    assert data["base"] == branch


@pytest.mark.parametrize("branch", ["main", "master"])
def test_check_archive_on_base_explicit_base_still_works(tmp_path: Path, branch: str) -> None:
    """Sanity check: check_archive_on_base itself is unaffected — it always
    takes an explicit base — regardless of which branch name the fixture uses."""
    bare = _bare_origin_with_branch(tmp_path, branch)
    work = _clone(tmp_path, bare)
    _add_archive_and_push(work, "my-design", branch)

    assert check_archive_on_base(str(work), "my-design", branch) is True


# ---------------------------------------------------------------------------
# SKILL.md pin — no-arg scan step 3 names default_branch.py
# ---------------------------------------------------------------------------

def test_skill_md_no_arg_scan_step3_names_default_branch() -> None:
    """The no-arg scan's step 3 (which invokes verify_merged.py) must name
    default_branch.py so the resolved --base is visible in the recipe."""
    skill_md = Path(__file__).resolve().parents[1] / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    start = text.index("## No-arg scan form")
    end = text.index("## Steps", start)
    section = text[start:end]
    assert "default_branch.py" in section, (  # tp-allow-fragile: default_branch.py is the resolver script the recipe must invoke; skill_refs does not resolve it inside the $(...) substitution
        "tp-post-merge/SKILL.md no-arg scan step 3 must name default_branch.py"
    )
