"""Tests for teardown.py — /tp-post-merge teardown steps c, d, e and h as code.

design: cheap-tier-offload (Task 5.1; slots doc §Phase 5, D8, D10).

A tmp seat repo with a bare origin, a `tp/<slug>` branch pushed to it, a sibling
worktree holding that branch, and an MRU file. `verify_merged` is monkeypatched for
the teardown cases; the wrapper itself is checked against a real archive on
`origin/master` with a `gh` that always fails.

Run with: pytest skills/tp-post-merge/scripts/test_teardown.py -q
"""
from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import teardown  # noqa: E402

SLUG = "demo"
BRANCH = f"tp/{SLUG}"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True)


def _commit(repo: Path, rel: str, text: str, msg: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def seat(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    repo = tmp_path / "seat"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True)
    for key, val in (("user.name", "t"), ("user.email", "t@example.com"),
                     ("commit.gpgsign", "false")):
        _git(repo, "config", key, val)
    _commit(repo, "README.md", "hi\n", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "branch", BRANCH)
    _git(repo, "push", "-q", "origin", BRANCH)
    _git(repo, "worktree", "add", "-q", str(tmp_path / "wt" / SLUG), BRANCH)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "last-design").write_text(f"other\n{SLUG}\n", encoding="utf-8")
    return repo


def _run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = teardown.main(argv)
    return rc, buf.getvalue()


def _remote_has_branch(repo: Path) -> bool:
    return bool(_git(repo, "ls-remote", "--heads", "origin", BRANCH).stdout.strip())


def _merged(value: bool, calls: list | None = None):
    def fake(root, slug, base, gh_cmd="gh"):
        if calls is not None:
            calls.append((slug, base, teardown.worktree_paths(root, slug),
                          _remote_has_branch(Path(root))))
        return value
    return fake


def _tear(seat: Path) -> tuple[int, dict]:
    rc, out = _run(["--slug", SLUG, "--base", "master", "--root", str(seat)])
    return rc, json.loads(out)


def test_refuses_and_deletes_nothing_when_not_merged(seat, monkeypatch):
    monkeypatch.setattr(teardown, "verify_merged", _merged(False))
    rc, out = _run(["--slug", SLUG, "--base", "master", "--root", str(seat)])
    assert rc == 1
    assert "refused" in json.loads(out)
    assert teardown.worktree_paths(seat, SLUG)
    assert _git(seat, "branch", "--list", BRANCH).stdout.strip()
    assert _remote_has_branch(seat)
    assert SLUG in (seat / ".claude" / "last-design").read_text(encoding="utf-8")


def test_tears_down_after_verify(seat, monkeypatch):
    calls: list = []
    monkeypatch.setattr(teardown, "verify_merged", _merged(True, calls))
    rc, payload = _tear(seat)
    assert rc == 0
    # verify ran first, while the worktree and the remote branch were still there
    assert len(calls) == 1 and calls[0][:2] == (SLUG, "master")
    assert calls[0][2] and calls[0][3]
    assert teardown.worktree_paths(seat, SLUG) == []
    assert not _git(seat, "branch", "--list", BRANCH).stdout.strip()
    assert not _remote_has_branch(seat)
    assert (seat / ".claude" / "last-design").read_text(encoding="utf-8") == "other\n"
    steps = payload["steps"]
    assert set(steps) == {"c_worktree", "d_local_branch", "e_remote_branch", "h_mru"}
    assert steps["c_worktree"].startswith("removed ")
    assert steps["d_local_branch"] == "deleted"
    assert steps["e_remote_branch"] == "deleted"
    assert steps["h_mru"] == "cleared"


def test_verify_argv_is_the_check_call_and_passes(seat, monkeypatch):
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    _, payload = _tear(seat)
    argv = payload["verify_argv"]
    assert argv[2:] == ["--check", "--slug", SLUG, "--root", str(seat.resolve())]
    assert Path(argv[1]).name == "teardown.py"
    assert subprocess.run(argv, capture_output=True).returncode == 0


def test_mru_file_is_deleted_when_it_empties(seat, monkeypatch):
    (seat / ".claude" / "last-design").write_text(f"{SLUG}\n", encoding="utf-8")
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    _tear(seat)
    assert not (seat / ".claude" / "last-design").exists()


def test_remote_delete_is_fail_open_when_already_gone(seat, monkeypatch):
    _git(seat, "push", "-q", "origin", "--delete", BRANCH)
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    rc, payload = _tear(seat)
    assert rc == 0
    assert payload["steps"]["e_remote_branch"].startswith("not deleted (fail-open)")
    assert payload["steps"]["d_local_branch"] == "deleted"
    assert payload["steps"]["h_mru"] == "cleared"


def test_dirty_worktree_is_fail_open_and_the_check_sees_residue(seat, monkeypatch, tmp_path):
    (tmp_path / "wt" / SLUG / "wip.txt").write_text("uncommitted\n", encoding="utf-8")
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    rc, payload = _tear(seat)
    assert rc == 0
    assert payload["steps"]["c_worktree"].startswith("failed ")
    assert payload["steps"]["d_local_branch"].startswith("failed")
    assert subprocess.run(payload["verify_argv"], capture_output=True).returncode == 1


def test_check_exits_1_on_each_residue(seat, monkeypatch):
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(seat)])
    assert rc == 1
    assert len(json.loads(out)["residue"]) == 3
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    _tear(seat)
    assert _run(["--check", "--slug", SLUG, "--root", str(seat)])[0] == 0
    (seat / ".claude" / "last-design").write_text(f"{SLUG}\n", encoding="utf-8")
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(seat)])
    assert rc == 1 and json.loads(out)["residue"] == [f".claude/last-design holds {SLUG}"]
    (seat / ".claude" / "last-design").unlink()
    _git(seat, "branch", BRANCH)
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(seat)])
    assert rc == 1 and json.loads(out)["residue"] == [f"branch {BRANCH} still listed"]


def test_check_sees_a_listed_worktree(seat, monkeypatch, tmp_path):
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    _tear(seat)
    _git(seat, "worktree", "add", "-q", "-b", BRANCH, str(tmp_path / "again"))
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(seat)])
    assert rc == 1
    assert any(r.startswith("worktree ") for r in json.loads(out)["residue"])


def test_never_removes_the_root_worktree(seat, monkeypatch, tmp_path):
    wt = tmp_path / "wt" / SLUG
    monkeypatch.setattr(teardown, "verify_merged", _merged(True))
    rc, payload = _tear(wt)
    assert rc == 0
    assert "is the teardown root" in payload["steps"]["c_worktree"]
    assert wt.is_dir()


def test_verify_merged_reads_the_archive_on_origin_base(seat):
    assert teardown.verify_merged(seat, SLUG, "master", gh_cmd="false") is False
    _commit(seat, f"three-pillars-docs/completed-tp-designs/{SLUG}/design.md", "# d\n",
            "archive")
    _git(seat, "push", "-q", "origin", "master")
    assert teardown.verify_merged(seat, SLUG, "master", gh_cmd="false") is True


@pytest.mark.parametrize("argv", [
    ["--slug", "../x", "--base", "master"],
    ["--slug", SLUG],
    ["--check"],
])
def test_usage_errors_exit_2(argv, tmp_path):
    with contextlib.redirect_stderr(io.StringIO()):
        assert _run(argv + ["--root", str(tmp_path)])[0] == 2


# --- PR #191 review r1: an unobservable root is an error, never clean ------------------


def test_check_on_an_unobservable_root_is_an_error_not_clean(tmp_path):
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(tmp_path / "missing")])
    got = json.loads(out)
    assert rc == 3 and "residue" not in got and got["error"], got
    plain = tmp_path / "plain"  # a dir that is not a git checkout
    plain.mkdir()
    rc, out = _run(["--check", "--slug", SLUG, "--root", str(plain)])
    assert rc == 3 and json.loads(out)["error"]


def test_teardown_steps_report_an_unobservable_listing_as_failed(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    assert teardown.remove_worktrees(root, SLUG).startswith("failed")
    assert teardown.delete_local_branch(root, SLUG).startswith("failed")
