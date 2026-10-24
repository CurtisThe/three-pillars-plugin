"""round_log_carry: only a single-parent commit touching the round-log files of ONE existing
archived design dir is a round-log commit; the strip walks at most 3 and fails closed."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import round_log_carry  # noqa: E402
from round_log_carry import strip_round_log_commits  # noqa: E402

ARCH = "three-pillars-docs/completed-tp-designs"
IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, val in IDENT.items():
        monkeypatch.setenv(key, val)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def commit(repo, files, msg="c"):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            p.unlink()
        else:
            p.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    p = commit(tmp_path, {f"{ARCH}/demo/design.md": "d\n", f"{ARCH}/demo/decisions.md": "a\n"})
    return tmp_path, p


def test_decisions_only_commit_is_stripped(repo):
    r, p = repo
    h = commit(r, {f"{ARCH}/demo/decisions.md": "a\nb\n"})
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (p, 1)


def test_all_three_log_files_stripped(repo):
    r, p = repo
    h = commit(r, {f"{ARCH}/demo/decisions.md": "x\n",
                   f"{ARCH}/demo/dispatch-telemetry.ndjson": "{}\n",
                   f"{ARCH}/demo/escape-ledger.ndjson": "{}\n"})
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (p, 1)


def _not_stripped(repo, files):
    r, _ = repo
    h = commit(r, files)
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (h, 0)
    assert res.reason


def test_code_file_in_commit_is_not_stripped(repo):
    _not_stripped(repo, {f"{ARCH}/demo/decisions.md": "z\n", "skills/x.py": "x\n"})


def test_other_archive_file_not_stripped(repo):
    _not_stripped(repo, {f"{ARCH}/demo/design.md": "changed\n"})


def test_in_flight_design_dir_not_stripped(repo):
    _not_stripped(repo, {"three-pillars-docs/tp-designs/demo/decisions.md": "z\n"})


def test_two_slugs_not_stripped(repo):
    r, _ = repo
    commit(r, {f"{ARCH}/other/design.md": "d\n"})
    _not_stripped(repo, {f"{ARCH}/demo/decisions.md": "z\n", f"{ARCH}/other/decisions.md": "z\n"})


def test_deletion_not_stripped(repo):
    _not_stripped(repo, {f"{ARCH}/demo/decisions.md": None})


def test_mode_change_not_stripped(repo):
    r, _ = repo
    git(r, "update-index", "--chmod=+x", f"{ARCH}/demo/decisions.md")
    git(r, "commit", "-q", "-m", "mode")
    h = git(r, "rev-parse", "HEAD")
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (h, 0)


def test_archive_absent_in_parent_not_stripped(repo):
    _not_stripped(repo, {f"{ARCH}/new/decisions.md": "z\n"})


def test_merge_commit_stops_the_walk(repo):
    r, _ = repo
    git(r, "checkout", "-q", "-b", "side")
    commit(r, {"side.txt": "s\n"})
    git(r, "checkout", "-q", "main")
    commit(r, {"main.txt": "m\n"})
    git(r, "merge", "-q", "--no-ff", "-m", "merge", "side")
    h = git(r, "rev-parse", "HEAD")
    res = strip_round_log_commits(r, h)
    assert (res.anchor, res.links) == (h, 0)


def test_root_commit_stops_the_walk(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    h = commit(tmp_path, {f"{ARCH}/demo/decisions.md": "a\n"})
    res = strip_round_log_commits(tmp_path, h)
    assert (res.anchor, res.links) == (h, 0)


def test_chain_capped_at_three(repo):
    r, p = repo
    shas = [commit(r, {f"{ARCH}/demo/decisions.md": f"a{i}\n"}) for i in range(4)]
    res = strip_round_log_commits(r, shas[3])
    assert res.links == 3
    assert res.anchor == shas[0] != p
    assert "cap" in res.reason


def test_unknown_head_fails_closed(repo):
    r, _ = repo
    res = strip_round_log_commits(r, "0" * 40)
    assert res.anchor is None
    assert res.reason


def test_names_constant():
    assert round_log_carry.ROUND_LOG_NAMES == (
        "decisions.md", "dispatch-telemetry.ndjson", "escape-ledger.ndjson",
        "finalizer-ledger.json")
