#!/usr/bin/env python3
"""base_sync_repo.py -- hermetic fixture-repo builder for the base-sync certificate suite.

CRITICAL invariant (Phase 2 plan-audit fold-in): every scenario repo is a LOCAL CLONE/FORK of
the REAL running checkout -- never a scratch `git init`. This checkout's HEAD is therefore
always an ancestor-or-equal of the fixture's `origin/<base>` tip, which is exactly what the
independent-oracle guard (wired at task 3.4, `oracle_root` hard-derived from
`base_sync_cert.__file__`, non-injectable) requires to accept a happy-path fixture. A
scratch-init'd fixture would make every Phase-2/5 happy-path test refuse as an
unrelated-origin oracle (rc 128) the instant 3.4 lands.

Topology-zoo builders (worktrees, distinct clones, bare hubs, ...) are task 3.1's job, not
this module's -- this file only builds the CORE two-repo (origin + repo) scenario plus the
scripted AUTO-SAFE merge helper and the tamper/broken-remote/origin-rewrite/shallow-clone
hooks Phase 2 needs.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from auto_safe_resolution import RESOLVED, resolve_conflict_bytes  # noqa: E402

LIVING_DOC_PATH = "three-pillars-docs/known_issues.md"

# Seeded onto base_ref right after cloning, BEFORE design_branch forks off it: the real file
# at LIVING_DOC_PATH is a large, structurally-repetitive doc where git's diff heuristics can
# align a small single-line edit ambiguously (picking different anchor context for "ours" vs
# "theirs" and producing a spurious CLEAN merge instead of the intended conflict). Overwriting
# it with this small, unambiguous seed makes every scripted divergence deterministic.
_SEED_LIVING_DOC = "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"

# A non-AUTO-SAFE path, seeded alongside the living doc, for condition-3 (allowlist)
# fixtures -- any conflict on this path must be refused regardless of its shape.
OTHER_PATH = "docs/fixture-other.md"
_SEED_OTHER = "# Fixture Other Doc\n\nnot a living doc.\nseed tail line.\n"


def _run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


def _this_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    r = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True, check=True)
    return Path(r.stdout.strip())


def _current_branch(repo_root: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo_root), "symbolic-ref", "--short", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


@dataclass
class ScenarioRepo:
    """A hermetic scenario: `origin_dir` stands in for the GitHub remote (a plain local
    checkout we mutate directly, never pushed into); `repo_dir` is the working checkout under
    test, with a real `origin` remote pointed at `origin_dir` so `git fetch origin <base>`
    works fully offline."""
    root: Path
    origin_dir: Path
    repo_dir: Path
    base_ref: str
    design_branch: str

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run(list(args), self.repo_dir, check=check)

    def origin_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return _run(list(args), self.origin_dir, check=check)

    def head(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref).stdout.strip()

    def origin_head(self, ref: str | None = None) -> str:
        return self.origin_git("rev-parse", ref or self.base_ref).stdout.strip()


def build_scenario(tmp_path, *, base_ref: str = "main", design_branch: str = "design",
                   living_doc_path: str = LIVING_DOC_PATH) -> ScenarioRepo:
    """Clone THIS checkout -> `origin_dir` (single-branch, renamed to `base_ref`); seed
    `living_doc_path` with small, unambiguous fixture content (see `_SEED_LIVING_DOC`); clone
    `origin_dir` -> `repo_dir`; branch `design_branch` off `base_ref` in `repo_dir`."""
    root = Path(tmp_path)
    origin_dir = root / "origin"
    repo_dir = root / "repo"
    src = _this_repo_root()
    src_branch = _current_branch(src)
    _run(["clone", "--quiet", "--single-branch", "--branch", src_branch, str(src), str(origin_dir)],
         root, check=True)
    _run(["checkout", "--quiet", "-B", base_ref], origin_dir, check=True)
    if src_branch != base_ref:
        _run(["branch", "-D", src_branch], origin_dir, check=False)
    _write_and_commit(origin_dir, living_doc_path, _SEED_LIVING_DOC, "fixture: seed living doc")
    _write_and_commit(origin_dir, OTHER_PATH, _SEED_OTHER, "fixture: seed non-AUTO-SAFE doc")
    _run(["clone", "--quiet", str(origin_dir), str(repo_dir)], root, check=True)
    _run(["checkout", "--quiet", "-b", design_branch, base_ref], repo_dir, check=True)
    return ScenarioRepo(root=root, origin_dir=origin_dir, repo_dir=repo_dir,
                       base_ref=base_ref, design_branch=design_branch)


def _write_and_commit(side_dir: Path, rel_path: str, content: str, message: str) -> str:
    target = side_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _run(["add", "--", rel_path], side_dir, check=True)
    _run(["commit", "--quiet", "-m", message], side_dir, check=True)
    return _run(["rev-parse", "HEAD"], side_dir, check=True).stdout.strip()


def _replace_last_line(text: str, new_line: str) -> str:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines[-1] = new_line if new_line.endswith("\n") else new_line + "\n"
    return "".join(lines)


def diverge_last_line(scenario: ScenarioRepo, path: str, *, base_line: str, design_line: str) -> tuple[str, str]:
    """Replace the LAST line of `path` with a DISTINCT line on each side -- a genuine
    same-base-line change/change conflict (a shared same-position APPEND is not reliably
    ambiguous to git's recursive merge and often auto-resolves without conflict, which this
    avoids). Both sides mutate the identical base line differently. Returns (base_tip_sha,
    design_tip_sha)."""
    base_before = (scenario.origin_dir / path).read_text(encoding="utf-8")
    base_sha = _write_and_commit(scenario.origin_dir, path, _replace_last_line(base_before, base_line),
                                 "base: change last line")
    design_before = (scenario.repo_dir / path).read_text(encoding="utf-8")
    design_sha = _write_and_commit(scenario.repo_dir, path, _replace_last_line(design_before, design_line),
                                   "design: change last line")
    return base_sha, design_sha


def diverge_living_doc(scenario: ScenarioRepo, *, path: str = LIVING_DOC_PATH,
                       base_line: str = "### Z1: base-side change\n",
                       design_line: str = "### Z1: design-side change\n") -> tuple[str, str]:
    """`diverge_last_line` specialized for the living doc -- an id-renumber-collision on
    merge (both new lines carry the same `### Z1:` heading id)."""
    return diverge_last_line(scenario, path, base_line=base_line, design_line=design_line)


def diverge_base_only(scenario: ScenarioRepo, *, path: str = LIVING_DOC_PATH,
                      extra_line: str = "### Z1: base-only advance\n") -> str:
    """Advance ONLY `origin_dir`'s base_ref -- design_branch never touches `path`, so the
    recompute is clean (K=empty). Returns the new base tip sha."""
    before = (scenario.origin_dir / path).read_text(encoding="utf-8")
    return _write_and_commit(scenario.origin_dir, path, before + extra_line, "base: unrelated advance")


def write_bytes_and_commit(side_dir: Path, rel_path: str, data: bytes, message: str) -> str:
    """Byte-level sibling of `_write_and_commit` -- for fixtures that need genuinely
    non-UTF-8 content on one merge side (the undecodable-blob condition-5 case)."""
    target = Path(side_dir) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _run(["add", "--", rel_path], Path(side_dir), check=True)
    _run(["commit", "--quiet", "-m", message], Path(side_dir), check=True)
    return _run(["rev-parse", "HEAD"], Path(side_dir), check=True).stdout.strip()


def force_merge_commit(scenario: ScenarioRepo, resolved: dict) -> str:
    """Low-level primitive: fetch + `git merge --no-commit --no-ff origin/<base_ref>`, then
    write EACH `resolved[path]` text directly to the conflicted worktree file and stage +
    commit as a 2-parent merge -- regardless of whether it matches what the real resolver
    would produce. Unlike `make_certified_sync_merge` (which asserts a real RESOLVED
    reproduction), this lets tests construct edge/adversarial merge commits (a non-AUTO-SAFE
    conflict, a hand-typed non-reproducible resolution, ...) at the git-object level."""
    scenario.git("fetch", "--quiet", "origin", scenario.base_ref, check=True)
    scenario.git("merge", "--no-commit", "--no-ff", f"origin/{scenario.base_ref}", check=False)
    for path, content in resolved.items():
        (scenario.repo_dir / path).write_text(content, encoding="utf-8")
        scenario.git("add", "--", path, check=True)
    scenario.git("commit", "--quiet", "-m", "test: forced merge resolution", check=True)
    return scenario.head()


def _show_stage(repo_dir: Path, stage: int, path: str) -> str:
    r = subprocess.run(["git", "-C", str(repo_dir), "show", f":{stage}:{path}"], capture_output=True, check=True)
    return r.stdout.decode("utf-8")


def make_certified_sync_merge(scenario: ScenarioRepo, *, path: str = LIVING_DOC_PATH) -> str:
    """The scripted AUTO-SAFE base-sync merge helper: fetch `origin`, merge
    `origin/<base_ref>` into `design_branch` (repo_dir must be checked out there already),
    resolve any conflict on `path` via the REAL shared resolver
    (`auto_safe_resolution.resolve_conflict_bytes`), stage + commit the resulting 2-parent
    merge. Handles BOTH a clean merge (no divergence) and a conflicted one (after
    `diverge_living_doc`). Returns the new merge commit's full sha (h1)."""
    scenario.git("fetch", "--quiet", "origin", scenario.base_ref, check=True)
    r = scenario.git("merge", "--no-commit", "--no-ff", f"origin/{scenario.base_ref}", check=False)
    if r.returncode == 0:
        scenario.git("commit", "--quiet", "--no-edit", check=True)
        return scenario.head()
    base = _show_stage(scenario.repo_dir, 1, path)
    ours = _show_stage(scenario.repo_dir, 2, path)
    theirs = _show_stage(scenario.repo_dir, 3, path)
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED, f"fixture setup produced a non-mechanical conflict: {status}"
    (scenario.repo_dir / path).write_text(merged, encoding="utf-8")
    scenario.git("add", "--", path, check=True)
    scenario.git("commit", "--quiet", "-m", "base-sync: auto-resolve AUTO-SAFE conflict", check=True)
    return scenario.head()


def _parents(scenario: ScenarioRepo, commit_sha: str) -> list[str]:
    r = scenario.git("rev-list", "--parents", "-n1", commit_sha, check=True)
    return r.stdout.strip().split()[1:]


def craft_merge_with_parents(scenario: ScenarioRepo, tree_ish: str, parents: list[str],
                             message: str = "crafted") -> str:
    """Low-level primitive ('craft-merge-with-parent'): `git commit-tree <tree_ish> [-p
    <parent>]... -m <message>` inside `repo_dir`. No branch is moved -- the returned sha is a
    free-floating commit object, usable directly as an `h1`/`h0` argument. Covers every
    malformed-parent-shape fixture: a single-parent commit is just `parents=[p]`; >2-parent
    octopus is `parents=[p1, p2, p3]`; `p1 != h0` and `p2` off-base both plug arbitrary shas
    into the parent list."""
    args = ["commit-tree", tree_ish]
    for p in parents:
        args += ["-p", p]
    args += ["-m", message]
    return _run(args, scenario.repo_dir, check=True).stdout.strip()


def tamper_smuggle_edit(scenario: ScenarioRepo, commit_sha: str, path: str, extra_line: str) -> str:
    """Build a new commit with the SAME parents as `commit_sha` but `path`'s content gets
    `extra_line` appended -- a semantic edit smuggled OUTSIDE any conflicted region (attack
    1's shape). `commit_sha` itself is left untouched; the new sha is returned."""
    parents = _parents(scenario, commit_sha)
    cur = scenario.git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    scenario.git("checkout", "--quiet", "--detach", commit_sha, check=True)
    try:
        target = scenario.repo_dir / path
        target.write_text(target.read_text(encoding="utf-8") + extra_line, encoding="utf-8")
        scenario.git("add", "--", path, check=True)
        tree = scenario.git("write-tree", check=True).stdout.strip()
    finally:
        scenario.git("reset", "--quiet", "--hard", commit_sha, check=True)
        if cur:
            scenario.git("checkout", "--quiet", cur, check=True)
    return craft_merge_with_parents(scenario, tree, parents, message="tampered: smuggled edit")


def break_remote(scenario: ScenarioRepo) -> None:
    """Repoint `repo_dir`'s 'origin' remote at a nonexistent path so `git fetch origin <base>`
    fails (rc != 0) -- the FRESH-DATA precondition's failure path."""
    bogus = scenario.root / "no-such-origin"
    scenario.git("remote", "set-url", "origin", str(bogus), check=True)


def rewrite_origin_base(scenario: ScenarioRepo, *, path: str = LIVING_DOC_PATH,
                        content: str = "### Z1: rewritten\n",
                        message: str = "origin: rewrite history") -> str:
    """Force-rewrite `origin_dir`'s base_ref tip (amend) -- simulates a base history rewrite
    between two gate evaluations (attack 10's shape). `origin_dir` is a plain checkout we
    mutate directly, never pushed into. Returns the new tip sha."""
    scenario.origin_git("checkout", "--quiet", scenario.base_ref, check=True)
    (scenario.origin_dir / path).write_text(content, encoding="utf-8")
    scenario.origin_git("add", "--", path, check=True)
    scenario.origin_git("commit", "--quiet", "--amend", "-m", message, check=True)
    return scenario.origin_head()


def shallow_clone(scenario: ScenarioRepo, dest_dir) -> Path:
    """`git clone --depth 1` from `origin_dir` into `dest_dir`; remote 'origin' points at
    `origin_dir`, same as `build_scenario`'s `repo_dir` but with incomplete (shallow) history
    -- for the entry-guard shallow-probe test. Uses the `file://` transport deliberately: a
    bare local filesystem path clone silently IGNORES `--depth` (git optimizes local clones
    via hardlinks and skips shallow negotiation), so a plain-path clone here would produce a
    full, non-shallow checkout and the shallow-probe test would never see `true`."""
    dest = Path(dest_dir)
    _run(["clone", "--quiet", "--depth", "1", "--branch", scenario.base_ref,
         f"file://{scenario.origin_dir}", str(dest)], scenario.root, check=True)
    return dest
