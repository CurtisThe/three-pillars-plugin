"""test_docs_compile_publish.py — Task 1.14: the rolling `tp/docs-compile` publish (branch + PR).

design: living-doc-fragments, Task 1.14 (§Interfaces docs_compile_publish, §Forge behaviour). Real temp git
repos with a local bare ``origin``; the forge is a stub runner and every git argv is recorded.
Oracle: example. Assertions read refs, trees, recorded argv and printed ``docs-compile:`` lines, never
message wording (test-fragility.md §2). The landed-or-open content test lives in
test_docs_compile_publish_landing.py, which reuses this module's helpers.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

import docs_compile_publish as pub  # noqa: E402
from test_docs_compile import CH, KI, ROADMAP, TWO, frag, git, make_repo  # noqa: E402

BRANCH = "tp/docs-compile"
GAMMA = frag("gamma", "2020-01-04", "\n## Architecture\n\n### Dist\n+ - gamma bullet\n")


class Git:
    """A git runner that records every argv it is given."""

    def __init__(self):
        self.argvs: list = []

    def __call__(self, argv, cwd):
        self.argvs.append(list(argv))
        return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True)


class Forge:
    """A scripted ``forge.py`` runner: ``resolve`` names the kind, ``pr-create`` is recorded."""

    def __init__(self, kind="github", create=(0, "https://forge.test/pull/1\n", ""), compare="https://forge.test/compare\n"):
        self.kind, self.create, self.compare = kind, create, compare
        self.calls: list = []

    def __call__(self, argv, cwd):
        if argv[0] == "resolve":
            return 0, json.dumps({"kind": self.kind}), ""
        self.calls.append(list(argv))
        if argv[0] == "pr-create":
            return self.create
        return 0, self.compare, ""


def with_origin(tmp_path, fragments, docs=None):
    """(work clone, bare origin path, base sha): ``main`` pushed to a bare origin."""
    root = make_repo(tmp_path, fragments, docs=docs)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "-u", "origin", "main")
    return root, bare, git(root, "rev-parse", "HEAD")


def tip(bare):
    out = subprocess.run(["git", "-C", str(bare), "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}"],
                         capture_output=True, text=True)
    return out.stdout.strip()


def add_to_main(root, files):
    """Commit ``files`` ({rel: text or None to delete}) on main and push it."""
    git(root, "checkout", "-q", "main")
    for rel, text in files.items():
        if text is None:
            git(root, "rm", "-q", "--", rel)
        else:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
            git(root, "add", "--", rel)
    git(root, "commit", "-q", "-m", "main moves")
    git(root, "push", "-q", "origin", "main")


def publish(root, forge=None, runner=None, **kw):
    return pub.run(root, base="main", runner=runner or Git(), forge_runner=forge or Forge(), **kw)


def test_new_branch_from_base_opens_pr(tmp_path):
    root, bare, base = with_origin(tmp_path, TWO)
    forge = Forge()
    lines = publish(root, forge)
    assert git(bare, "rev-parse", f"{BRANCH}~1") == base
    assert git(bare, "ls-tree", "-r", "--name-only", BRANCH, "--", CH) == ""
    (call,) = [c for c in forge.calls if c[0] == "pr-create"]
    assert call[call.index("--head") + 1] == BRANCH and call[call.index("--base") + 1] == "main"
    assert any(ln.startswith("docs-compile:") for ln in lines)
    assert git(root, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_open_branch_is_updated_without_new_pr(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    forge = Forge()
    publish(root, forge)
    first = tip(bare)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    publish(root, forge)
    assert tip(bare) != first
    assert subprocess.run(["git", "-C", str(bare), "merge-base", "--is-ancestor", first, BRANCH]).returncode == 0
    assert len([c for c in forge.calls if c[0] == "pr-create"]) == 1


def test_base_merge_conflict_aborts_with_line(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    publish(root, Forge())
    first = tip(bare)
    road = (root / ROADMAP).read_text(encoding="utf-8").replace("- focus one", "- focus ONE edited")
    add_to_main(root, {ROADMAP: road, f"{CH}/gamma.md": GAMMA})
    forge = Forge()
    lines = publish(root, forge)
    assert any(ln.startswith("docs-compile: base merge conflicts on") and ROADMAP in ln for ln in lines)
    assert tip(bare) == first and forge.calls == []
    assert git(root, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_no_origin_commits_locally_and_prints_merge(tmp_path):
    root = make_repo(tmp_path, TWO)
    forge = Forge()
    lines = publish(root, forge)
    assert git(root, "rev-parse", "--verify", BRANCH)
    assert git(root, "rev-list", "--count", f"main..{BRANCH}") == "1"
    assert git(root, "ls-tree", "-r", "--name-only", BRANCH, "--", CH) == ""
    assert f"git merge {BRANCH}" in "\n".join(lines)
    assert forge.calls == []


def test_gitea_reruns_pr_create_every_push(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    forge = Forge(kind="gitea")
    publish(root, forge)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    publish(root, forge)
    assert len([c for c in forge.calls if c[0] == "pr-create"]) == 2


def test_forge_exit_4_prints_compare_url(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    lines = publish(root, Forge(create=(4, "", "forge-degraded")))
    assert any("https://forge.test/compare" in ln for ln in lines)
    assert tip(bare)


def test_forge_exit_3_surfaces_bot_auth_and_other_failure_names_pr(tmp_path):
    root, _, _ = with_origin(tmp_path, TWO)
    assert any("bot-auth-unavailable" in ln for ln in publish(root, Forge(create=(3, "", "bot-auth-unavailable: x"))))
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    lines = publish(root, Forge(kind="gitea", create=(1, "", "boom")))
    assert any("open a PR from tp/docs-compile" in ln for ln in lines)


def test_never_force_pushes(tmp_path):
    root, bare, _ = with_origin(tmp_path, TWO)
    git_runner = Git()
    publish(root, Forge(), runner=git_runner)
    add_to_main(root, {f"{CH}/gamma.md": GAMMA})
    publish(root, Forge(), runner=git_runner)
    pushes = [a for a in git_runner.argvs if a[:2] == ["git", "push"]]
    assert pushes and all(a == ["git", "push", "origin", BRANCH] for a in pushes)
    assert not [a for a in git_runner.argvs if any(t in ("-f", "--force") or t.startswith("--force-") for t in a)]


def test_cli_always_exits_zero_even_off_a_repo(tmp_path, capsys):
    assert pub.main(["run", "--base", "main", "--repo-root", str(tmp_path)]) == 0
    assert "docs-compile:" in capsys.readouterr().out
