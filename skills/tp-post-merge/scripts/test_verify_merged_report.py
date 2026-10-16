"""Tests for verify_merged gh_status / evaluate / report (review-log-survives-teardown 1.2).

Real tmp_path git repos (bare origin + clone); GIT_* scrubbed, identity set;
gh is always a stub script; no network.

Run with: pytest skills/tp-post-merge/scripts/test_verify_merged_report.py -q
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import verify_merged  # noqa: E402
from verify_merged import compute_verdict, evaluate, gh_status, main, origin_host_is_github  # noqa: E402

_CLEAN = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
_CLEAN.update({"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
               "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), check=True, env=_CLEAN,
                       capture_output=True, text=True)
    return r.stdout.strip()


def _commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)


@pytest.fixture
def repo(tmp_path) -> Path:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "-q", "--bare", "-b", "master")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "checkout", "-q", "-B", "master")
    _commit(clone, "base.txt")
    _git(clone, "push", "-q", "origin", "master")
    _git(clone, "branch", "tp/demo")
    return clone


def _stub(tmp_path: Path, body: str, name: str = "gh") -> str:
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def test_gh_skipped_when_origin_is_not_github(repo, tmp_path):
    marker = tmp_path / "ran"
    stub = _stub(tmp_path, f"touch {marker}\necho MERGED")
    assert gh_status("demo", stub, str(repo)) == "skipped-not-github"
    assert not marker.exists()


def test_gh_states(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(verify_merged, "origin_host_is_github", lambda r: True)
    merged = _stub(tmp_path, 'echo \'{"state":"MERGED"}\'', "g1")
    opened = _stub(tmp_path, 'echo \'{"state":"OPEN"}\'', "g2")
    failing = _stub(tmp_path, "exit 1", "g3")
    assert gh_status("demo", merged, str(repo)) == "merged"
    assert gh_status("demo", opened, str(repo)) == "not-merged"
    assert gh_status("demo", failing, str(repo)) == "unavailable"


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/o/r.git", True),
    ("git@github.com:o/r.git", True),
    ("https://github.example.com/o/r", True),
    ("https://gitea.lan/o/r.git", False),
    ("/some/local/path.git", False),
])
def test_origin_host_is_github(repo, url, expected):
    _git(repo, "remote", "set-url", "origin", url)
    assert origin_host_is_github(str(repo)) is expected


def test_origin_host_is_github_no_origin(repo):
    _git(repo, "remote", "remove", "origin")
    assert origin_host_is_github(str(repo)) is False


def test_custom_host_with_authenticated_gh_is_queried(repo, tmp_path):
    _git(repo, "remote", "set-url", "origin", "https://git.corp.example/o/r.git")
    body = ('if [ "$1" = auth ]; then exit {rc}; fi\n'
            'echo \'{{"state":"MERGED"}}\'')
    ok = _stub(tmp_path, body.format(rc=0), "ok")
    bad = _stub(tmp_path, body.format(rc=1), "bad")
    assert gh_status("demo", ok, str(repo)) == "merged"
    assert gh_status("demo", bad, str(repo)) == "skipped-not-github"


def test_custom_host_without_gh_installed_is_skipped_not_unavailable(repo, tmp_path):
    _git(repo, "remote", "set-url", "origin", "https://git.corp.example/o/r.git")
    missing = str(tmp_path / "no-such-gh")
    assert gh_status("demo", missing, str(repo)) == "skipped-not-github"


def test_evaluate_no_ff_merge_is_merged_via_ancestor(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(verify_merged, "check_archive_on_base", lambda *a, **k: False)
    _git(repo, "checkout", "-q", "tp/demo")
    _commit(repo, "a.txt")
    _git(repo, "checkout", "-q", "master")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "tp/demo")
    _git(repo, "push", "-q", "origin", "master")
    res = evaluate(str(repo), "demo", "master", gh_cmd=_stub(tmp_path, "exit 1"))
    assert res["merged"] is True
    assert res["via"] == "ancestor"


def test_evaluate_refusal_names_every_check_and_remedy(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(verify_merged, "check_archive_on_base", lambda *a, **k: False)
    res = evaluate(str(repo), "demo", "master", gh_cmd=_stub(tmp_path, "exit 1"))
    assert res["merged"] is False
    for key in ("archive", "gh", "ancestor"):
        assert res["checks"][key]
    assert "not GitHub" in res["checks"]["gh"]
    assert "/tp-design-complete" in res["remedy"]
    assert "merge commit" in res["remedy"]


def test_compute_verdict_back_compat():
    assert compute_verdict(archive=True, gh=False, base="m") == {
        "merged": True, "via": "archive", "base": "m"}


def test_cli_json_carries_checks(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(verify_merged, "check_archive_on_base", lambda *a, **k: False)
    stub = _stub(tmp_path, "exit 1")
    assert main(["--repo", str(repo), "--design", "demo", "--base", "master",
                 "--json", "--gh-cmd", stub]) == 0
    out = json.loads(capsys.readouterr().out)
    for key in ("merged", "via", "base", "checks", "remedy"):
        assert key in out
