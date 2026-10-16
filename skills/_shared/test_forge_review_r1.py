"""Regression tests for PR #245 review round 1 (forge-interface).

design: forge-interface. Two shipped-behaviour defects the round-1 Opus check
reproduced at 5d5a6d9b:

1. First-run's forge write (`github_auth_check.forge_skip` -> `forge_config.record_kind`)
   replaced an unparseable `.three-pillars/config.json` with a `{schema_version, forge}`
   shell. repo-config.md: an invalid config is left for the user to inspect.
2. `forge.kind: gitea` with no usable `forge.web_base` (an ssh-alias origin, or a
   scheme-less value) resolved `api_base == ""`, so REST ops raised `ValueError` and
   `compare-url` printed a relative path. It now degrades as `no web base`.

Hermetic: `tmp_path` repos, a `resolver` seam, `HOME` pointed at an empty dir (no
`tea` logins), no network.

Run with: python3 -m pytest skills/_shared/test_forge_review_r1.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge  # noqa: E402
import forge_config  # noqa: E402
import github_auth_check  # noqa: E402


def _repo(tmp_path, url, config_text):
    d = tmp_path / "r"
    (d / ".three-pillars").mkdir(parents=True)
    (d / ".three-pillars" / "config.json").write_text(config_text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "remote", "add", "origin", url], check=True)
    return d


GITEA_INFO = forge.ForgeInfo("gitea", "gitea.example.com", "acme", "widget",
                             "https://gitea.example.com",
                             "https://gitea.example.com/api/v1", "")


def test_first_run_forge_skip_never_overwrites_an_unparseable_config(tmp_path):
    broken = ('{"schema_version": 1, "review": {"require_human_approval": true}, '
              '"ci": {"gate_command": "make ci"},')  # trailing comma: mid hand-edit
    repo = _repo(tmp_path, "https://gitea.example.com/acme/widget.git", broken)
    github_auth_check.check(repo, resolver=lambda r: GITEA_INFO)
    after = (repo / ".three-pillars" / "config.json").read_text(encoding="utf-8")
    assert after == broken, f"repo-config.md: never replace a broken config file; got {after!r}"


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_record_kind_refuses_to_write_over_a_non_object_config(tmp_path, text):
    repo = _repo(tmp_path, "https://gitea.example.com/acme/widget.git", text)
    assert forge_config.record_kind(repo, GITEA_INFO) is False
    assert (repo / ".three-pillars" / "config.json").read_text(encoding="utf-8") == text


@pytest.mark.parametrize("url,config", [
    ("git@gitea-home:acme/widget.git", '{"schema_version": 1, "forge": {"kind": "gitea"}}'),
    ("git@gitea-home:acme/widget.git",
     '{"schema_version": 1, "forge": {"kind": "gitea", "web_base": "gitea.lan"}}'),
])
def test_gitea_kind_without_web_base_degrades_and_never_prints_a_relative_url(
        tmp_path, monkeypatch, capsys, url, config):
    repo = _repo(tmp_path, url, config)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GITEA_TOKEN", "tok")
    assert forge.main(["pr-read", "3", "--repo", str(repo)]) == 4
    capsys.readouterr()
    rc = forge.main(["compare-url", "--base", "main", "--head", "tp/x", "--repo", str(repo)])
    captured = capsys.readouterr()
    assert rc == 4
    assert captured.out.strip() == ""
    assert "no web base" in captured.err


def test_gitea_kind_with_a_configured_https_web_base_stays_gitea(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "git@gitea-home:acme/widget.git",
                 '{"forge": {"kind": "gitea", "web_base": "https://gitea.lan:3000"}}')
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    info = forge.resolve(repo, tea_logins=[])
    assert (info.kind, info.web_base, info.api_base) == (
        "gitea", "https://gitea.lan:3000", "https://gitea.lan:3000/api/v1")
