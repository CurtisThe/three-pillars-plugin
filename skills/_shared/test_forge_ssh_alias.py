"""Tests for GitHub origins that are not the literal host `github.com`.

design: forge-interface (impl-audit retry; known issue L113). An ssh-config alias
(`git@github-work:o/r`, `git@github.com-work:o/r`) is resolved offline with
`ssh -G <host>` through the module's `runner` seam; a GitHub Enterprise https host
(which fails the Gitea probe) is reached with config `forge.kind: github`. The
`other` degrades name that fix. Hermetic: fake `runner` / `urlopen`, one throwaway
local git repo for the CLI path. No network, no real ssh.
Run with: python3 -m pytest skills/_shared/test_forge_ssh_alias.py -q -n0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge  # noqa: E402
import forge_ssh  # noqa: E402
import github_pr_author  # noqa: E402

GITHUB_FIX = "set forge.kind: github"


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def ssh_g(hostname: str) -> str:
    return f"user git\nhostname {hostname}\nport 22\nidentityfile ~/.ssh/id\n"


class Runner:
    """Fake runner: `git remote get-url` -> origin; `ssh -G <host>` -> `ssh_out`."""

    def __init__(self, origin, ssh_out=None, ssh_exc=None):
        self.origin, self.ssh_out, self.ssh_exc = origin, ssh_out, ssh_exc
        self.ssh_calls: list = []

    def __call__(self, argv, **kwargs):
        if argv[0] == "ssh":
            self.ssh_calls.append(list(argv))
            if self.ssh_exc:
                raise self.ssh_exc
            return Proc(0, self.ssh_out) if self.ssh_out is not None else Proc(255)
        return Proc(0, self.origin + "\n") if "get-url" in argv else Proc(1)


class Probe:
    def __init__(self):
        self.urls: list = []

    def __call__(self, request, timeout=None, context=None):
        self.urls.append(request.url)
        raise URLError("refused")


def resolve(origin, *, config=None, **runner_kw):
    runner = Runner(origin, **runner_kw)
    probe = Probe()
    info = forge.resolve("/fixture/repo", config=config or {}, runner=runner,
                         urlopen=probe, tea_logins=[])
    return info, runner, probe


# --- ssh -G resolves a GitHub alias -------------------------------------------

@pytest.mark.parametrize("origin,alias", [
    ("git@github-work:Acme/widget.git", "github-work"),
    ("git@github.com-work:Acme/widget.git", "github.com-work"),
    ("ssh://git@github-work/Acme/widget.git", "github-work"),
])
def test_ssh_alias_for_github_resolves_to_github(origin, alias):
    info, runner, probe = resolve(origin, ssh_out=ssh_g("github.com"))
    assert runner.ssh_calls == [["ssh", "-G", alias]]
    assert info.kind == "github"
    assert (info.owner, info.repo) == ("Acme", "widget")
    assert info.web_base == "https://github.com"
    assert info.api_base == "https://api.github.com"
    assert info.reason == ""
    assert probe.urls == []


def test_ssh_alias_for_another_host_is_unchanged():
    info, runner, _ = resolve("git@gitea:scurtis/Homelab.git",
                              ssh_out=ssh_g("truenas.home.arpa"))
    assert runner.ssh_calls == [["ssh", "-G", "gitea"]]
    assert info.kind == "other"
    assert "no web base" in info.reason


@pytest.mark.parametrize("kw", [{"ssh_out": None}, {"ssh_exc": FileNotFoundError("ssh")},
                                {"ssh_exc": subprocess.TimeoutExpired("ssh", 5)},
                                {"ssh_out": "garbage without a host line\n"}])
def test_ssh_g_failure_falls_through_to_other(kw):
    info, runner, _ = resolve("git@github-work:Acme/widget.git", **kw)
    assert len(runner.ssh_calls) == 1
    assert info.kind == "other"
    assert "no web base" in info.reason


def test_ssh_g_never_runs_for_github_com():
    info, runner, _ = resolve("git@github.com:Acme/widget.git", ssh_out=ssh_g("x"))
    assert info.kind == "github"
    assert runner.ssh_calls == []


@pytest.mark.parametrize("config", [{"forge": {"kind": "gitea"}},
                                    {"forge": {"kind": "github"}},
                                    {"forge": {"web_base": "https://t.lan:3000"}}])
def test_ssh_g_never_runs_when_config_decides(config):
    _, runner, _ = resolve("git@github-work:Acme/widget.git", config=config,
                           ssh_out=ssh_g("github.com"))
    assert runner.ssh_calls == []


def test_ssh_g_is_not_run_for_an_https_remote():
    _, runner, _ = resolve("https://ghe.example.com/Acme/widget.git",
                           ssh_out=ssh_g("github.com"))
    assert runner.ssh_calls == []


def test_ssh_g_has_a_short_timeout_on_the_default_runner(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=list(argv))
        return Proc(0, ssh_g("github.com"))

    monkeypatch.setattr(forge_ssh.subprocess, "run", fake_run)
    assert forge_ssh.alias_hostname("github-work") == "github.com"
    assert seen["argv"] == ["ssh", "-G", "github-work"]
    assert 0 < seen["timeout"] <= 10


def test_ssh_g_timeout_on_the_default_runner_is_not_a_crash(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(forge_ssh.subprocess, "run", fake_run)
    assert forge_ssh.alias_hostname("github-work") == ""


# --- GitHub Enterprise / forge.kind: github -----------------------------------

def test_enterprise_https_without_config_is_other_and_names_the_github_fix():
    info, _, probe = resolve("https://ghe.example.com/Acme/widget.git")
    assert info.kind == "other"
    assert probe.urls == ["https://ghe.example.com/api/v1/version"]
    assert GITHUB_FIX in info.reason
    assert info.reason.count("unsupported forge") == 1
    line = forge._unsupported(info).line
    assert line.count("unsupported forge") == 1 and GITHUB_FIX in line


def test_recorded_other_on_an_enterprise_origin_still_names_the_github_fix():
    """First-run records `forge.kind: other` for a GHE host; the later `pr-create`
    resolve takes the config-kind branch (empty reason) and must still name the fix."""
    info, _, _ = resolve("https://ghe.example.com/Acme/widget.git",
                         config={"forge": {"kind": "other"}})
    assert info.kind == "other" and info.reason == ""
    line = forge._unsupported(info).line
    assert "()" not in line
    assert "ghe.example.com" in line
    assert "forge.kind: other" in line and ".three-pillars/config.json" in line
    assert forge.GITHUB_HINT in line
    assert line.count("unsupported forge") == 1


def test_config_kind_github_makes_an_enterprise_origin_github():
    info, _, probe = resolve("https://ghe.example.com/Acme/widget.git",
                             config={"forge": {"kind": "github"}})
    assert info.kind == "github"
    assert info.web_base == "https://ghe.example.com"
    assert probe.urls == []


def test_config_kind_github_on_an_unresolvable_alias_still_has_a_web_base():
    info, _, _ = resolve("git@github-work:Acme/widget.git",
                         config={"forge": {"kind": "github"}})
    assert info.kind == "github"
    assert info.web_base == "https://github.com"


def test_setup_line_names_both_fixes():
    line = forge.NO_WEB_BASE_LINE
    assert "set forge.web_base in .three-pillars/config.json" in line
    assert GITHUB_FIX in line and "GitHub Enterprise" in line
    assert "(or set forge.kind: other to silence this)" in line
    assert "\n" not in line


def test_pr_create_with_config_kind_github_takes_the_github_path(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".three-pillars").mkdir(parents=True)
    (repo / ".three-pillars" / "config.json").write_text(
        '{"forge": {"kind": "github"}}', encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://ghe.example.com/Acme/widget.git"], check=True)
    import forge_gitea
    monkeypatch.setattr(forge_gitea, "read_tea_logins", lambda *a, **k: [])
    calls: list = []
    monkeypatch.setattr(github_pr_author, "main",
                        lambda argv: calls.append(list(argv)) or 0)
    assert forge.main(["pr-create", "--repo", str(repo), "--", "--base", "main",
                       "--head", "feat", "--title", "T", "--body", "B"]) == 0
    assert calls == [["create", "--context", "manual", "--repo", str(repo), "--",
                      "--base", "main", "--head", "feat", "--title", "T",
                      "--body", "B"]]
