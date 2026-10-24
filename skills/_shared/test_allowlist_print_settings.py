"""Tests for allowlist_mine --print-settings: JSON on stdout, hints on stderr, nothing written."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import allowlist_settings  # noqa: E402
from allowlist_mine import main  # noqa: E402
from allowlist_settings import (  # noqa: E402
    deny_rules, entries_for, expand, load, root_forms)

MINE = str(Path(allowlist_settings.__file__).resolve().with_name("allowlist_mine.py"))
TP_ROOT = Path(allowlist_settings.__file__).resolve().parents[2]


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / ".three-pillars").mkdir()
    (repo / ".three-pillars" / "config.json").write_text(json.dumps({"forge": {"kind": "github"}}))
    (tmp_path / "home").mkdir()
    (tmp_path / "cfg").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path, repo


def _run(tmp_path, repo):
    e = {"HOME": str(tmp_path / "home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"),
         "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, MINE, "--print-settings", "--repo", str(repo)],
                          capture_output=True, text=True, env=e)


def _settings(tmp_path, obj):
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps(obj))


def _expected(repo, forge="github"):
    return set(expand(entries_for(load(), forge, TP_ROOT), root_forms(TP_ROOT, repo)))


def test_stdout_is_valid_json(env):
    tmp_path, repo = env
    r = _run(tmp_path, repo)
    assert r.returncode == 0
    tool = subprocess.run([sys.executable, "-m", "json.tool"], input=r.stdout,
                          capture_output=True, text=True)
    assert tool.returncode == 0


def test_only_recommended_rules(env):
    tmp_path, repo = env
    obj = json.loads(_run(tmp_path, repo).stdout)
    assert set(obj) == {"permissions"}
    assert obj["permissions"]["allow"]
    assert set(obj["permissions"]["allow"]) <= _expected(repo)
    assert obj["permissions"]["deny"] == deny_rules(load())


def test_no_per_worktree_git_c_allow_rule(env):
    tmp_path, repo = env
    perms = json.loads(_run(tmp_path, repo).stdout)["permissions"]
    assert [r for r in perms["allow"] if r.startswith("Bash(git -C /")] == []
    for verb in ("fetch --upl*", "log --outp*", "diff --outp*"):
        assert f"Bash(git -C * {verb})" in perms["deny"]


def test_worktrees_do_not_change_output(env):
    tmp_path, repo = env
    before = _run(tmp_path, repo).stdout
    ident = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    empty_tree = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "tree", "/dev/null"],
                                check=True, capture_output=True, text=True).stdout.strip()
    sha = subprocess.run(["git", "-C", str(repo), "commit-tree", empty_tree, "-m", "x"], check=True,
                         capture_output=True, text=True, env=ident).stdout.strip()
    _git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "wt"), sha)
    assert _run(tmp_path, repo).stdout == before


def test_gitea_forge_switches_verbs(env):
    tmp_path, repo = env
    (repo / ".three-pillars" / "config.json").write_text(json.dumps({"forge": {"kind": "gitea"}}))
    allow = json.loads(_run(tmp_path, repo).stdout)["permissions"]["allow"]
    assert "Bash(tea pr list)" in allow
    assert not [r for r in allow if r.startswith("Bash(gh ")]


def test_stderr_target_and_verify(env):
    tmp_path, repo = env
    err = _run(tmp_path, repo).stderr
    assert str(tmp_path / "cfg" / "settings.json") in err
    assert "nothing was written" in err
    assert [ln for ln in err.splitlines() if ln.startswith("VERIFY:")]


def test_classify_all_shell_warns(env):
    tmp_path, repo = env
    _settings(tmp_path, {"autoMode": {"classifyAllShell": True}})
    assert "autoMode.classifyAllShell is true" in _run(tmp_path, repo).stderr


def test_reports_present_count(env):
    tmp_path, repo = env
    _settings(tmp_path, {"permissions": {"allow": ["Bash(git status)", "Bash(git status *)"]}})
    err = _run(tmp_path, repo).stderr
    assert "1 of " in err
    assert "recommended entries already present" in err


def test_stale_root_hinted(env):
    tmp_path, repo = env
    entries = entries_for(load(), "github", TP_ROOT)
    allow = expand(entries, ["/elsewhere/tp/"])
    _settings(tmp_path, {"permissions": {"allow": allow}})
    lines = [ln for ln in _run(tmp_path, repo).stderr.splitlines()
             if ln.startswith("no exact rules for ")]
    assert len(lines) == 1
    assert str(TP_ROOT) in lines[0]


def test_forge_hints(env):
    tmp_path, repo = env
    (repo / ".three-pillars" / "config.json").unlink()
    assert "forge: github (default" in _run(tmp_path, repo).stderr
    (repo / ".three-pillars" / "config.json").write_text(json.dumps({"forge": {"kind": "gitea"}}))
    assert "no Gitea rule: gh pr view, gh pr checks" in _run(tmp_path, repo).stderr


def test_unreadable_settings_hinted(env):
    tmp_path, repo = env
    (tmp_path / "cfg" / "settings.json").write_text("{not json")
    r = _run(tmp_path, repo)
    assert r.returncode == 0
    assert "cannot read " in r.stderr


def _snapshot(tmp_path):
    return {p: (p.read_bytes() if p.is_file() else None) for p in sorted(tmp_path.rglob("*"))
            if ".git" not in p.relative_to(tmp_path).parts}


def test_never_writes(env, capsys, monkeypatch):
    tmp_path, repo = env
    home_settings = tmp_path / "home" / ".claude" / "settings.json"
    cfg_settings = tmp_path / "cfg" / "settings.json"
    # (config dir set | HOME fallback) x (no settings.json | valid bytes | unreadable bytes)
    for use_cfg in (True, False):
        if use_cfg:
            monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        else:
            monkeypatch.delenv("CLAUDE_CONFIG_DIR")
        target = cfg_settings if use_cfg else home_settings
        target.parent.mkdir(parents=True, exist_ok=True)
        for content in (None, b'{"permissions": {"allow": []}}', b"{not json"):
            if content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
            before = _snapshot(tmp_path)
            assert main(["--print-settings", "--repo", str(repo)]) == 0
            capsys.readouterr()
            assert _snapshot(tmp_path) == before, (target, content)
            assert target.exists() == (content is not None), target
            if content is not None:
                assert target.read_bytes() == content, target
