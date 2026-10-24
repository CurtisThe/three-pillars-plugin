"""Tests for worker_root — the tp-worker write root, kept off `.claude/`.

design: classifier-no-verdict-nested-writes (Task 1.1)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import worker_root as wr  # noqa: E402

SCRIPT = str(Path(__file__).resolve().parent / "worker_root.py")


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _init(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("x")
    _git(path, "add", "f.txt")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _cli(cwd, *args):
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, capture_output=True, text=True)


def _worktrees(root):
    return [line[len("worktree "):] for line in _git(root, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")]


def test_has_claude_component():
    assert wr.has_claude_component("/x/.claude/worktrees/agent-1")
    assert wr.has_claude_component("/a/b/.claude")
    assert not wr.has_claude_component("/x/three-pillars-wt/slug/.tp-scratch/tp-cand-s-p1-ab")
    assert not wr.has_claude_component("/x/claude/worktrees")


def test_check_refuses_a_claude_path(tmp_path):
    r = _cli(tmp_path, "check", "/x/.claude/worktrees/agent-1")
    assert r.returncode == 1
    assert "/x/.claude/worktrees/agent-1" in r.stderr
    assert "worker-root-refused" in r.stderr


def test_check_accepts_a_clean_path(tmp_path):
    assert _cli(tmp_path, "check", str(tmp_path / "wt" / "slug")).returncode == 0


def test_open_creates_a_detached_candidate_worktree(tmp_path):
    root = _init(tmp_path / "repo")
    sha = _git(root, "rev-parse", "HEAD").strip()
    r = _cli(root, "open", "--slug", "demo", "--phase", "1", "--base-ref", "HEAD", "--root", ".")
    assert r.returncode == 0, r.stderr
    path = Path(json.loads(r.stdout.strip().splitlines()[-1])["path"])
    assert path.parent == (root / ".tp-scratch").resolve()
    assert path.name.startswith("tp-cand-demo-p1-")
    assert os.path.realpath(str(path)) in [os.path.realpath(p) for p in _worktrees(root)]
    assert _git(path, "rev-parse", "HEAD").strip() == sha
    assert _git(path, "branch", "--show-current").strip() == ""


def test_open_refuses_a_claude_root_and_creates_nothing(tmp_path):
    root = _init(tmp_path / ".claude" / "worktrees" / "agent-1")
    r = _cli(root, "open", "--slug", "demo", "--phase", "1", "--base-ref", "HEAD", "--root", ".")
    assert r.returncode == 1
    assert "worker-root-refused" in r.stderr
    assert not (root / ".tp-scratch").exists()
    assert len(_worktrees(root)) == 1


def test_verify_passes_inside_and_fails_from_the_repo_root(tmp_path):
    root = _init(tmp_path / "repo")
    opened = _cli(root, "open", "--slug", "demo", "--phase", "1", "--base-ref", "HEAD", "--root", ".")
    path = json.loads(opened.stdout.strip().splitlines()[-1])["path"]
    assert _cli(path, "verify", "--path", path).returncode == 0
    stray = _cli(root, "verify", "--path", path)
    assert stray.returncode == 1
    assert "worker-root-refused" in stray.stderr


def test_reap_keeps_the_kept_path_and_other_slugs(tmp_path):
    root = _init(tmp_path / "repo")

    def _open(slug, phase):
        out = _cli(root, "open", "--slug", slug, "--phase", str(phase), "--base-ref", "HEAD", "--root", ".")
        return json.loads(out.stdout.strip().splitlines()[-1])["path"]

    old1, old2, keep, other = _open("demo", 1), _open("demo", 2), _open("demo", 3), _open("demo2", 1)
    r = _cli(root, "reap", "--slug", "demo", "--keep", keep, "--root", ".")
    assert r.returncode == 0, r.stderr
    left = [os.path.realpath(p) for p in _worktrees(root)]
    assert os.path.realpath(keep) in left and os.path.realpath(other) in left
    assert os.path.realpath(old1) not in left and os.path.realpath(old2) not in left
    assert not Path(old1).exists()


def test_reap_with_nothing_to_reap_exits_zero(tmp_path):
    root = _init(tmp_path / "repo")
    assert _cli(root, "reap", "--slug", "demo", "--root", ".").returncode == 0


def test_open_rejects_a_non_integer_phase(tmp_path):
    root = _init(tmp_path / "repo")
    r = _cli(root, "open", "--slug", "demo", "--phase", "1.1", "--base-ref", "HEAD", "--root", ".")
    assert r.returncode != 0
    assert not (root / ".tp-scratch").exists() or not list((root / ".tp-scratch").glob("tp-cand-*"))


def test_a_git_failure_is_not_reported_as_a_claude_refusal(tmp_path):
    root = _init(tmp_path / "repo")
    r = _cli(root, "open", "--slug", "demo", "--phase", "1", "--base-ref", "no-such-ref", "--root", ".")
    assert r.returncode == 1
    assert "worker-root-open-failed" in r.stderr
    assert "worker-root-refused" not in r.stderr


def _open_cli(root, *extra, slug="demo", phase="1", base="HEAD"):
    return _cli(root, "open", "--slug", slug, "--phase", phase, f"--base-ref={base}", "--root", ".", *extra)


def test_open_rejects_a_slug_that_could_escape_the_scratch_dir(tmp_path):
    root = _init(tmp_path / "repo")
    for bad in ("../../esc", "a/b", "Up", "", "x y"):
        r = _open_cli(root, slug=bad)
        assert r.returncode == 1, bad
        assert "worker-root-refused" in r.stderr, bad
    assert len(_worktrees(root)) == 1
    assert not (tmp_path / "esc").exists()


def test_reap_rejects_a_bad_slug(tmp_path):
    root = _init(tmp_path / "repo")
    r = _cli(root, "reap", "--slug", "../x", "--root", ".")
    assert r.returncode == 1
    assert "worker-root-refused" in r.stderr


def test_open_rejects_a_negative_phase(tmp_path):
    root = _init(tmp_path / "repo")
    r = _open_cli(root, phase="-1")
    assert r.returncode != 0
    assert len(_worktrees(root)) == 1


def test_open_reads_a_dash_base_ref_as_a_ref_not_an_option(tmp_path):
    root = _init(tmp_path / "repo")
    r = _open_cli(root, base="--force")
    assert r.returncode == 1
    assert "worker-root-open-failed" in r.stderr
    assert len(_worktrees(root)) == 1


def test_open_detaches_so_a_checked_out_branch_can_be_the_base(tmp_path):
    """The shipped base ref is `tp/<slug>`, checked out in the orchestrator's tree: only --detach opens it."""
    root = _init(tmp_path / "repo")
    branch = _git(root, "branch", "--show-current").strip()
    r = _open_cli(root, base=branch)
    assert r.returncode == 0, r.stderr
    path = json.loads(r.stdout.strip().splitlines()[-1])["path"]
    assert _git(path, "branch", "--show-current").strip() == ""


def test_open_ignores_the_scratch_dir(tmp_path):
    root = _init(tmp_path / "repo")
    assert _open_cli(root).returncode == 0
    probe = subprocess.run(["git", "check-ignore", "-q", ".tp-scratch/x"], cwd=root)
    assert probe.returncode == 0


def test_open_reports_a_missing_root_as_open_failed_not_a_traceback(tmp_path):
    r = _cli(tmp_path, "open", "--slug", "demo", "--phase", "1", "--base-ref", "HEAD",
             "--root", str(tmp_path / "nope"))
    assert r.returncode == 1
    assert "worker-root-open-failed" in r.stderr
    assert "Traceback" not in r.stderr


def test_a_symlink_into_a_claude_dir_is_refused(tmp_path):
    target = tmp_path / ".claude" / "agent"
    target.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(target)
    assert wr.has_claude_component(str(link))
    r = _cli(tmp_path, "check", str(link))
    assert r.returncode == 1


def test_open_refuses_when_the_scratch_dir_resolves_under_claude(tmp_path):
    """The computed-path leg: the root is clean, but `.tp-scratch` is a symlink into `.claude/`."""
    root = _init(tmp_path / "repo")
    target = tmp_path / ".claude" / "scratch"
    target.mkdir(parents=True)
    (root / ".tp-scratch").symlink_to(target)
    r = _open_cli(root)
    assert r.returncode == 1
    assert "worker-root-refused" in r.stderr
    assert len(_worktrees(root)) == 1


def test_verify_refuses_an_empty_or_relative_path(tmp_path):
    root = _init(tmp_path / "repo")
    for bad in ("", ".", "repo"):
        r = _cli(root, "verify", "--path", bad)
        assert r.returncode == 1, bad
        assert "worker-root-refused" in r.stderr, bad


def test_reap_reports_an_evaluation_failure_in_its_json(tmp_path):
    r = _cli(tmp_path, "reap", "--slug", "demo", "--root", str(tmp_path / "nope"))
    assert r.returncode == 0
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["reaped"] == [] and out.get("error")


def test_tip_and_assert_unmoved_catch_a_stray_commit(tmp_path):
    root = _init(tmp_path / "repo")
    branch = _git(root, "branch", "--show-current").strip()
    tip = json.loads(_cli(root, "tip", "--branch", branch, "--root", ".").stdout.strip().splitlines()[-1])
    assert tip["branch"] == branch and len(tip["sha"]) == 40
    ok = _cli(root, "assert-unmoved", "--branch", branch, "--sha", tip["sha"], "--root", ".")
    assert ok.returncode == 0, ok.stderr
    (root / "g.txt").write_text("y")
    _git(root, "add", "g.txt")
    _git(root, "commit", "-q", "-m", "stray")
    moved = _cli(root, "assert-unmoved", "--branch", branch, "--sha", tip["sha"], "--root", ".")
    assert moved.returncode == 1
    assert "worker-escaped-worktree" in moved.stderr


def test_open_rejects_a_non_ascii_digit_phase(tmp_path):
    root = _init(tmp_path / "repo")
    r = _open_cli(root, phase="²")
    assert r.returncode == 1
    assert "worker-root-refused" in r.stderr
    assert len(_worktrees(root)) == 1


def test_tip_of_an_unreadable_branch_is_an_orchestrator_side_failure(tmp_path):
    root = _init(tmp_path / "repo")
    r = _cli(root, "tip", "--branch", "no-such-branch", "--root", ".")
    assert r.returncode == 1
    assert "worker-root-open-failed" in r.stderr
    assert "worker-escaped-worktree" not in r.stderr
