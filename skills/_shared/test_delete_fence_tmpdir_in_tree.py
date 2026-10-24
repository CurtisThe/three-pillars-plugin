"""A TMPDIR at the run's in-tree scratch dir keeps the fence roots (design
run-scratch-in-fence 1.3). `compute_roots` is pure over an injected `git`; the
repos here are bare directories with a `.git` entry under `tmp_path`."""
import os

from delete_fence_roots import compute_roots

UID = 1000


def _git(args, cwd):
    return ""


def _repo(base, name="repo"):
    top = os.path.realpath(os.path.join(str(base), name))
    os.makedirs(os.path.join(top, ".git"))
    run = os.path.join(top, ".tp-scratch", "run")
    os.makedirs(run)
    return top, run


def _roots(kind, top, env, cwd=None):
    info = {"top": top, "git_dir": top + "/.git", "common_dir": top + "/.git",
            "branch": "tp/a"}
    return compute_roots(kind, info, cwd or top, env, _git, None, None, UID)


def test_run_dir_tmpdir_keeps_top_and_adds_run_dir(tmp_path):
    top, run = _repo(tmp_path)
    roots = _roots("design-run", top, {"TMPDIR": run})
    assert top in roots, roots
    assert run in roots, roots


def test_nested_worker_gets_the_run_dir_as_a_root(tmp_path):
    top, run = _repo(tmp_path)
    worker = os.path.join(top, ".tp-scratch", "tp-attempt-x")
    os.makedirs(worker)
    with open(os.path.join(worker, ".git"), "w") as fh:
        fh.write("gitdir: elsewhere\n")
    roots = _roots("design-run", worker, {"TMPDIR": run})
    assert worker in roots, roots
    assert run in roots, roots


def test_shared_tmpdir_stays_never_and_drops_its_parent(tmp_path):
    shared = os.path.join(str(tmp_path), "t")
    os.makedirs(os.path.join(shared, "repo", ".git"))
    top = os.path.realpath(shared)
    assert _roots("design-run", top, {"TMPDIR": top}) == []
    inner = os.path.realpath(os.path.join(shared, "sub"))
    os.makedirs(inner)
    roots = _roots("design-run", top, {"TMPDIR": inner})
    assert top not in roots and inner not in roots


def test_fake_run_dir_under_non_repo_is_shared(tmp_path):
    top = os.path.realpath(os.path.join(str(tmp_path), "norepo"))
    run = os.path.join(top, ".tp-scratch", "run")
    os.makedirs(run)
    roots = _roots("design-run", top, {"TMPDIR": run})
    assert top not in roots and run not in roots


def test_seat_kind_unchanged(tmp_path):
    top, run = _repo(tmp_path)
    roots = _roots("seat", top, {"TMPDIR": run})
    assert run not in roots and top not in roots


def test_no_tmpdir_root_set_is_today_s(tmp_path):
    top, run = _repo(tmp_path)
    assert _roots("design-run", top, {}) == [top]
