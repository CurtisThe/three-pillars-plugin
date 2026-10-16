"""review_prep_io — the review-prep drafter's in-tree I/O dir.

design: cheap-tier-review-prep (PR #209 review r1). A `tp-drafter` is
project-scoped (Read/Edit/Write only, no Bash), while the prep work dir W sits
under the proof root, which in a linked worktree is
`<main>/.git/worktrees/<wt>/...`, outside the drafter's tree. So every path a
drafter reads or writes (its facts, the diff or CI log it quotes, its one output
file) is staged under the repo's gitignored scratch dir (cheap-dispatch.md,
Scratch): `<top>/.tp-scratch/prep-io-<pr>/<slot>/<unit>/`. The oracle
still reads W's own inputs; `settle` copies the staged draft back into W and
removes the unit dir. Ignored files never show in `git status`, so the
live-tree guard does not see the staged files. Stdlib only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import review_prep  # noqa: E402
import scratch_root  # noqa: E402 — the one scratch base

SCRATCH_DIR = scratch_root.SCRATCH_DIR  # == cheap_fix.SCRATCH_DIR (cheap-dispatch.md, Scratch)
PREFIX = "prep-io-"
DRAFT, FACTS = "draft.json", "facts.json"
_INPUT_KEYS = ("diff_path", "log_path")  # the facts keys a drafter reads


def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=60, check=False)


def _top(repo) -> Path:
    out = _git(repo, "rev-parse", "--show-toplevel")
    if out.returncode != 0:
        raise RuntimeError(f"not a git checkout: {repo}")
    return Path(out.stdout.strip())


def _pr(pr_url) -> str:
    return review_prep._pr_number(pr_url)


def ignored(repo) -> bool:
    """True iff the scratch dir is gitignored in `repo` (never staged, never in status).
    `ensure_excluded` runs first (fail-open), so a consumer repo with no `.gitignore`
    line still gets its I/O dir in-tree."""
    try:
        top = _top(repo)
    except RuntimeError:
        return False
    scratch_root.ensure_excluded(top)
    return _git(top, "check-ignore", "-q", f"{SCRATCH_DIR}/{PREFIX}probe/").returncode == 0


def root(repo, pr_url) -> Path:
    """`<top>/.tp-scratch/prep-io-<pr>` — one PR's drafter I/O."""
    return _top(repo) / SCRATCH_DIR / f"{PREFIX}{_pr(pr_url)}"


def unit_dir(repo, pr_url, slot, unit) -> Path:
    return root(repo, pr_url) / str(slot) / str(unit)


def stage(repo, pr_url, slot, unit, payload: dict) -> tuple[Path, Path]:
    """Write the unit's facts with every drafter path in-tree; → (facts, out_path)."""
    d = unit_dir(repo, pr_url, slot, unit)
    shutil.rmtree(d, ignore_errors=True)  # a stale staged draft never survives a spawn
    d.mkdir(parents=True)
    staged = dict(payload)
    for key in _INPUT_KEYS:
        if key in staged:
            src = Path(staged[key])
            dst = d / src.name
            if src.is_file():
                shutil.copyfile(src, dst)
            staged[key] = str(dst)
    out = d / DRAFT
    staged["out_path"] = str(out)
    facts = d / FACTS
    facts.write_text(json.dumps(staged, indent=2), encoding="utf-8")
    return facts, out


def harvest(repo, pr_url, slot, unit, dest) -> None:
    """Copy the staged draft (a regular file only) to `dest`, then remove the unit dir."""
    try:
        d = unit_dir(repo, pr_url, slot, unit)
    except RuntimeError:
        return
    src = d / DRAFT
    if src.is_file() and not src.is_symlink():
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    shutil.rmtree(d, ignore_errors=True)
    for parent in (d.parent, d.parent.parent):  # the slot dir, then the PR dir, when empty
        try:
            parent.rmdir()
        except OSError:
            break


def wipe(repo, pr_url) -> None:
    """Remove one PR's staged drafter I/O (a fresh `begin`); fail-open."""
    try:
        shutil.rmtree(root(repo, pr_url), ignore_errors=True)
    except RuntimeError:
        pass
