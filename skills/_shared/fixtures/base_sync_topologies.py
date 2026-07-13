"""base_sync_topologies.py -- topology-zoo builders for the independent-oracle guard's
fixture suite (task 3.1).

Every builder operates on a `ScenarioRepo` from `base_sync_repo.build_scenario()` (the
task-2.1 core two-repo scenario -- a LOCAL clone/fork of the real running checkout). These
builders reshape or clone THAT scenario into the named oracle topologies the guard's
soundness suite needs (plan.md Phase 3, task 3.1): a seat + `*-wt/{name}` design worktree, a
distinct clone at a chosen ref, an unknown-worktree, a detached seat, a bare-hub + standing
base worktree, a `commit-tree`-reparented tree-identical commit, an unpushed-descendant
clone, and (via `detach_seat`/plain checkout on `scenario.repo_dir`) the seat-locally-ahead
shape.

None of these builders touch `seat_resolve.sh` -- they only construct real git topologies on
disk; the guard invokes the live, unedited script against them.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from base_sync_repo import craft_merge_with_parents  # noqa: E402 (sibling fixtures/ module)


def _run(args: list[str], cwd, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


# ============================================================
# Seat + design worktree / unknown-worktree
# ============================================================


def add_design_worktree(scenario, name: str = "feature", ref: "str | None" = None) -> Path:
    """`<scenario.root>/repo-wt/<name>` -- a canonical `*-wt/` sibling design worktree of
    `scenario.repo_dir`, on a new branch `tp/<name>` off `ref` (default: the current
    `design_branch` tip). Mirrors `topology.md`'s `<repo>-wt/<name>` layout exactly. Returns
    the worktree path."""
    dest = scenario.root / "repo-wt" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    base = ref or scenario.design_branch
    _run(["worktree", "add", "-q", "-b", f"tp/{name}", str(dest), base], scenario.repo_dir)
    return dest


def add_unknown_worktree(scenario, name: str = "odd", ref: "str | None" = None) -> Path:
    """A same-repo registered worktree at a path that is neither under `*-wt/` nor the
    primary -- mirrors `test_seat_resolve.sh` fixture 7's shape exactly (a detached worktree
    outside any `*-wt/` sibling dir, and outside the primary toplevel). Returns the worktree
    path."""
    dest = scenario.root / name
    base = ref or scenario.design_branch
    _run(["worktree", "add", "--detach", "-q", str(dest), base], scenario.repo_dir)
    return dest


# ============================================================
# Detached seat / distinct clones
# ============================================================


def detach_seat(scenario, ref: "str | None" = None) -> str:
    """Detach `scenario.repo_dir`'s HEAD at `ref` (default: its own current HEAD) -- the
    'detached seat' topology. Returns the resolved sha."""
    target = ref or scenario.head()
    _run(["checkout", "--quiet", "--detach", target], scenario.repo_dir)
    return scenario.head()


def checkout_detached(scenario, sha: str) -> str:
    """Detach `scenario.repo_dir`'s HEAD at an arbitrary (possibly free-floating) commit sha
    -- used to check out a crafted commit (e.g. `reparented_tree_identical_commit`'s result,
    or an ancestor merge inside a chain) as the oracle. Returns the resolved sha."""
    _run(["checkout", "--quiet", "--detach", sha], scenario.repo_dir)
    return scenario.head()


def distinct_clone_at_ref(scenario, ref: str, dest_dir, *, source=None) -> Path:
    """A FRESH clone (a genuinely separate `.git`), checked out DETACHED at `ref`. `source`
    defaults to `scenario.origin_dir` (the stand-in "origin"); pass `scenario.repo_dir`
    explicitly to clone a ref that only exists on the design side (e.g. a merge commit not
    yet advanced into `origin_dir`, as fixture 11 needs). Returns the clone's path."""
    dest = Path(dest_dir)
    src = source if source is not None else scenario.origin_dir
    _run(["clone", "--quiet", str(src), str(dest)], scenario.root)
    _run(["checkout", "--quiet", "--detach", ref], dest)
    return dest


def unpushed_descendant_clone(scenario, ref: str, dest_dir, *, source=None,
                              path: str = "unpushed.txt",
                              content: str = "unpushed descendant\n") -> Path:
    """`distinct_clone_at_ref` plus ONE new local commit never pushed anywhere -- the
    'unpushed-descendant' topology (fixture 16). Returns the clone's path."""
    dest = distinct_clone_at_ref(scenario, ref, dest_dir, source=source)
    (dest / path).write_text(content, encoding="utf-8")
    _run(["add", "--", path], dest)
    _run(["commit", "--quiet", "-m", "unpushed descendant"], dest)
    return dest


# ============================================================
# Commit-tree-reparented tree-identical commit
# ============================================================


def reparented_tree_identical_commit(scenario, tree_head: str, new_parent: "str | None" = None, *,
                                     message: str = "tree-identical-reparented") -> str:
    """`git commit-tree <tree_head>^{tree} [-p <new_parent>] -m <message>` inside
    `scenario.repo_dir` -- a commit whose TREE is byte-identical to `tree_head`'s but
    reparented onto `new_parent` (an orphan when `new_parent` is None/falsy). No branch
    moves; the returned sha is a free-floating commit object. Thin wrapper over
    `base_sync_repo.craft_merge_with_parents`."""
    parents = [new_parent] if new_parent else []
    return craft_merge_with_parents(scenario, f"{tree_head}^{{tree}}", parents, message=message)


# ============================================================
# Bare hub + standing base worktree (+ a design worktree off the same hub)
# ============================================================


def build_bare_hub_with_worktrees(scenario, *, design_name: str = "design"):
    """Genuine bare hub (`git clone --bare` of `scenario.origin_dir`) plus a standing
    `<base>` worktree -- mirrors `test_seat_resolve.sh` fixture 4's `hub-wt/{base}` shape
    exactly -- plus a non-base design worktree off the SAME hub. Returns `(hub_path,
    base_worktree_path, design_worktree_path)`.

    NOTE: a plain `--bare` clone omits the `remote.origin.fetch` tracking refspec entirely
    (verified live: `origin/<base>` never resolves in a bare clone), so this hub is NOT
    wired for `git fetch origin <base>` to succeed. Callers exercise the DISJOINT-CODE
    classification directly (it never fetches), not the full `oracle_independent` FRESH-DATA
    step, against this topology.
    """
    hub = scenario.root / "hub"
    _run(["clone", "--quiet", "--bare", str(scenario.origin_dir), str(hub)], scenario.root)
    wt_root = scenario.root / "hub-wt"
    wt_root.mkdir(parents=True, exist_ok=True)
    base_wt = wt_root / scenario.base_ref
    _run(["worktree", "add", "-q", str(base_wt), scenario.base_ref], hub)
    design_wt = wt_root / design_name
    _run(["worktree", "add", "-q", "-b", f"tp/{design_name}", str(design_wt), scenario.base_ref], hub)
    return hub, base_wt, design_wt
