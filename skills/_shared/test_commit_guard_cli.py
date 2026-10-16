"""test_commit_guard_cli.py — `commit_guard.py` CLI (Task 5.3).

The entry point the first-run prose calls: `apply [--file-size]
[--deny-no-verify] --repo <path>` exits 0 when it installed or the hooks were
already current, and 3 when a hook refused (the snippet text and the
`commit-guard-manual` marker are Task 5.4's); `record-tp-root <path> --repo
<path>` prints `changed` then `unchanged` on a repeat.

House rules: real tmp_path git repos, GIT_* env scrubbed, HOME isolated,
`{"schema_version": 1}` committed first. Stdlib + pytest only; shipped test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "commit_guard.py"
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
CLEAN_ENV.update({
    "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
    "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test",
})


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Scrub inherited GIT_* vars and isolate HOME: the CLI runs git through
    subprocess with the ambient os.environ."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, env=CLEAN_ENV,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-q", "-m", "init"], repo)
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8")
    _git(["add", ".three-pillars/config.json"], repo)
    _git(["commit", "-q", "-m", "seed config"], repo)
    return repo


def _hooks_dir(repo: Path) -> Path:
    return Path(_git(["rev-parse", "--path-format=absolute", "--git-path", "hooks"], repo))


def _cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, env=CLEAN_ENV)


def _deny(repo: Path) -> list[str]:
    return json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))[
        "permissions"]["deny"]


def test_apply_cli_installs_hooks_settings_and_config_keys(tmp_path):
    repo = _repo(tmp_path)
    proc = _cli(["apply", "--file-size", "--deny-no-verify", "--repo", str(repo)])
    assert proc.returncode == 0, proc.stderr
    hooks = _hooks_dir(repo)
    for name in ("pre-commit", "commit-msg"):
        hook = hooks / name
        assert hook.exists() and os.access(str(hook), os.X_OK)
        assert "commit-guard BEGIN" in hook.read_text(encoding="utf-8")
    deny = _deny(repo)
    assert "Bash(git commit --no-verify:*)" in deny
    assert "Bash(git commit -n:*)" in deny
    data = json.loads((repo / ".three-pillars" / "config.json").read_text(encoding="utf-8"))
    assert data["commit_guard"]["applied_at"]
    assert data["commit_guard"]["file_size"] is True
    assert data["commit_guard"]["deny_no_verify"] is True
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    assert (Path(common) / "three-pillars" / "tp-root").exists()


def test_apply_cli_refused_install_exits_3_hook_untouched(tmp_path):
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    text = "#!/usr/bin/env python3\nprint('not a shell hook')\n"
    (hooks / "pre-commit").write_text(text, encoding="utf-8")
    (hooks / "pre-commit").chmod(0o755)
    proc = _cli(["apply", "--repo", str(repo)])
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert (hooks / "pre-commit").read_text(encoding="utf-8") == text
    assert not (hooks / "commit-msg").exists()


def test_record_tp_root_cli_prints_changed_then_unchanged(tmp_path):
    repo = _repo(tmp_path)
    first = _cli(["record-tp-root", "/srv/three-pillars", "--repo", str(repo)])
    assert first.returncode == 0, first.stderr
    assert "changed" in first.stdout
    second = _cli(["record-tp-root", "/srv/three-pillars", "--repo", str(repo)])
    assert second.returncode == 0, second.stderr
    assert "unchanged" in second.stdout
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    assert (Path(common) / "three-pillars" / "tp-root").read_text(encoding="utf-8") == \
        "/srv/three-pillars"


def test_refresh_and_decline_cli(tmp_path):
    from skills._shared import commit_guard

    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    old = ("#!/bin/sh\n"
           "# three-pillars: commit-guard BEGIN v0\n"
           "# stale guard body\n"
           "_tp_commit_guard pre-commit \"$@\" || exit $?\n"
           "# three-pillars: commit-guard END\n"
           "echo foreign\n")
    for name in ("pre-commit", "commit-msg"):
        hook = hooks / name
        hook.write_text(old.replace("pre-commit", name), encoding="utf-8")
        hook.chmod(0o755)
    # a v<N-1> install is stale: refresh exits 0 and then status is no longer stale
    before_cfg = (repo / ".three-pillars" / "config.json").read_bytes()
    proc = _cli(["refresh", "--repo", str(repo)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (repo / ".three-pillars" / "config.json").read_bytes() == before_cfg
    for name in ("pre-commit", "commit-msg"):
        text = (hooks / name).read_text(encoding="utf-8")
        assert f"BEGIN v{commit_guard.BODY_VERSION}" in text
        assert "stale guard body" not in text and "echo foreign" in text
    status_proc = _cli(["status", "--brief", "--repo", str(repo)])
    assert status_proc.returncode == 0, status_proc.stdout + status_proc.stderr
    st = commit_guard.status(str(repo))
    assert st["stale"] is False and st["effective"] is True

    # decline writes only the per-clone marker, leaving the committed config byte-identical
    cfg_bytes = (repo / ".three-pillars" / "config.json").read_bytes()
    decl = _cli(["decline", "--repo", str(repo)])
    assert decl.returncode == 0, decl.stdout + decl.stderr
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    marker = Path(common) / "three-pillars" / "commit-guard-declined"
    assert marker.exists()
    assert (repo / ".three-pillars" / "config.json").read_bytes() == cfg_bytes
    assert commit_guard.status(str(repo))["local_decline"] is True


def test_failed_apply_still_records_the_tp_root_pointer(tmp_path):
    """PR #170 r1: an unrelated schema-invalid key makes apply's config write fail after
    the hooks are in; the tp-root pointer they read must already be recorded, or every
    commit prints "commit NOT checked" while `status` reports the guard effective."""
    repo = _repo(tmp_path)
    (repo / ".three-pillars" / "config.json").write_text(
        '{"schema_version": 1, "review": {"expects_copilot": "no"}}\n', encoding="utf-8")
    assert _cli(["apply", "--repo", str(repo)]).returncode == 2
    assert (_hooks_dir(repo) / "pre-commit").exists()
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    assert (Path(common) / "three-pillars" / "tp-root").exists()


_TEAM_HOOK = "#!/bin/sh\necho team hook\n"
_GENERATED = ('#!/bin/sh\n# File generated by pre-commit\n'
              'exec python3 -mpre_commit.hook_impl --hook-dir "/srv/pc" "$@"\n')


@pytest.mark.parametrize("link,shared", [
    ("pre-commit", False), ("commit-msg", True), ("pre-commit.legacy", True)])
def test_apply_refuses_a_hook_symlinked_out_of_the_hooks_dir(tmp_path, link, shared):
    """PR #170 r1: `_hooks_dir_ok` realpaths only the directory, so apply wrote through a
    per-file link (the hook, or the `.legacy` behind a pre-commit script) into a tracked
    in-tree script or a hook other repos share. Part E: it refuses and writes nothing."""
    repo = _repo(tmp_path)
    hooks = _hooks_dir(repo)
    target = (tmp_path / "dotfiles" if shared else repo / "scripts") / link
    target.parent.mkdir()
    target.write_text(_TEAM_HOOK, encoding="utf-8")
    target.chmod(0o755)
    if link.endswith(".legacy"):
        (hooks / "pre-commit").write_text(_GENERATED, encoding="utf-8")
        (hooks / "pre-commit").chmod(0o755)
    (hooks / link).symlink_to(target)
    assert _cli(["apply", "--repo", str(repo)]).returncode == 3
    assert target.read_text(encoding="utf-8") == _TEAM_HOOK
    others = {h: (hooks / h).read_text(encoding="utf-8")
              for h in ("pre-commit", "commit-msg") if h != link and (hooks / h).is_file()}
    assert others == ({"pre-commit": _GENERATED} if link.endswith(".legacy") else {})
    config = repo / ".three-pillars" / "config.json"
    assert config.read_text(encoding="utf-8") == '{"schema_version": 1}\n'
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)
    assert not (Path(common) / "three-pillars" / "tp-root").exists()
