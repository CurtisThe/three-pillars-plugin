"""Tests for forge.py: parse_remote, the resolve() precedence chain, Result.

design: forge-interface (Task 1.1). Hermetic: the origin URL comes from a fake
`runner`, the probe from a fake `urlopen`, tea logins from a fake `tea_logins`.
No network, no real git, no real tea. Every probe request must carry a
system-CA SSL context (`verify_mode == ssl.CERT_REQUIRED`) — never `-k`.
Run with: python3 -m pytest skills/_shared/test_forge_resolve.py -q -n0
"""
from __future__ import annotations

import ssl
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge  # noqa: E402

SETUP_SUBSTR = "set forge.web_base in .three-pillars/config.json"


class FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class Probe:
    """Fake urlopen: records every request, answers per the scripted mode."""

    def __init__(self, mode: str = "ok", payload: str = '{"version": "1.22.1"}') -> None:
        self.mode = mode
        self.payload = payload
        self.urls: list[str] = []
        self.contexts: list = []

    def __call__(self, request, timeout=None, context=None):
        self.urls.append(request.url)
        self.contexts.append(context)
        if self.mode == "error":
            raise URLError("connection refused")
        if self.mode in ("404", "nonjson"):
            raise OSError("HTTP Error 404: Not Found")
        return FakeResponse(self.payload)


def resolve(origin, *, config=None, probe=None, tea_logins=None):
    """Run resolve() against a fake `git remote get-url origin` and probe."""
    def runner(argv, **kwargs):
        if "get-url" in argv:
            return FakeCompleted(0, origin + "\n" if origin else "")
        return FakeCompleted(1, "")

    return forge.resolve(
        "/fixture/repo",
        config=config,
        runner=runner,
        urlopen=probe if probe is not None else Probe(),
        tea_logins=tea_logins if tea_logins is not None else [],
    )


# --- parse_remote -----------------------------------------------------------

@pytest.mark.parametrize(
    "url,host,port,owner,repo",
    [
        ("git@github.com:Acme/widget.git", "github.com", None, "Acme", "widget"),
        ("https://github.com/Acme/widget", "github.com", None, "Acme", "widget"),
        ("ssh://git@gitea.lan:2222/home/lab.git", "gitea.lan", 2222, "home", "lab"),
        ("https://gitea.lan/home/lab.git", "gitea.lan", None, "home", "lab"),
        ("https://user:tok@gitea.lan/home/lab.git", "gitea.lan", None, "home", "lab"),
        ("gitea:scurtis/Homelab.git", "gitea", None, "scurtis", "Homelab"),
    ],
)
def test_parse_remote(url, host, port, owner, repo):
    assert forge.parse_remote(url) == (host, port, owner, repo)


def test_parse_remote_strips_credentials():
    for url in ("https://user:tok@gitea.lan/home/lab.git",
                "ssh://git:pw@gitea.lan:2222/home/lab.git"):
        for field in forge.parse_remote(url):
            assert "tok" not in str(field)
            assert "pw" not in str(field)


# --- config wins, and github.com never probes -------------------------------

def test_config_kind_wins_over_the_url():
    probe = Probe()
    info = resolve("https://github.com/Acme/widget.git",
                   config={"forge": {"kind": "gitea"}}, probe=probe)
    assert info.kind == "gitea"
    assert probe.urls == []
    assert info.web_base == "https://github.com"
    assert info.api_base == "https://github.com/api/v1"


def test_github_com_is_github_without_probing():
    probe = Probe()
    info = resolve("git@github.com:Acme/widget.git", probe=probe)
    assert info.kind == "github"
    assert (info.host, info.owner, info.repo) == ("github.com", "Acme", "widget")
    assert info.web_base == "https://github.com"
    assert info.api_base == "https://api.github.com"
    assert probe.urls == []


# --- the probe --------------------------------------------------------------

def test_probe_answer_means_gitea_with_system_ca():
    probe = Probe()
    info = resolve("https://gitea.lan/home/lab.git", probe=probe)
    assert info.kind == "gitea"
    assert info.web_base == "https://gitea.lan"
    assert info.api_base == "https://gitea.lan/api/v1"
    assert probe.urls == ["https://gitea.lan/api/v1/version"]
    assert probe.contexts[0].verify_mode == ssl.CERT_REQUIRED


def test_config_web_base_beats_derivation_and_strips_trailing_slash():
    probe = Probe()
    info = resolve(
        "gitea:scurtis/Homelab.git",
        config={"forge": {"web_base": "https://truenas.home.arpa:30008/"}},
        probe=probe,
    )
    assert info.kind == "gitea"
    assert (info.owner, info.repo) == ("scurtis", "Homelab")
    assert info.web_base == "https://truenas.home.arpa:30008"
    assert info.api_base == "https://truenas.home.arpa:30008/api/v1"
    assert probe.urls == ["https://truenas.home.arpa:30008/api/v1/version"]


def test_https_origin_keeps_its_port():
    probe = Probe()
    info = resolve("https://gitea.lan:3000/home/lab.git", probe=probe)
    assert info.web_base == "https://gitea.lan:3000"
    assert probe.urls == ["https://gitea.lan:3000/api/v1/version"]


def test_tea_login_url_matched_by_hostname():
    probe = Probe()
    info = resolve("ssh://git@gitea.lan:2222/home/lab.git",
                   probe=probe, tea_logins=[{"url": "https://gitea.lan:3000"}])
    assert probe.urls == ["https://gitea.lan:3000/api/v1/version"]
    assert info.kind == "gitea"


# --- no web base ------------------------------------------------------------

def test_ssh_alias_without_web_base_is_other():
    probe = Probe()
    info = resolve("gitea:scurtis/Homelab.git", probe=probe)
    assert info.kind == "other"
    assert probe.urls == []
    assert "no web base" in info.reason
    assert SETUP_SUBSTR in info.reason


def test_recorded_other_is_not_authoritative_once_web_base_is_set():
    probe = Probe()
    info = resolve(
        "gitea:scurtis/Homelab.git",
        config={"forge": {"kind": "other", "host": "gitea",
                          "web_base": "https://truenas.home.arpa:30008"}},
        probe=probe,
    )
    assert info.kind == "gitea"
    assert probe.urls == ["https://truenas.home.arpa:30008/api/v1/version"]


def test_recorded_other_without_web_base_needs_no_probe():
    probe = Probe()
    info = resolve("https://gitea.lan/home/lab.git",
                   config={"forge": {"kind": "other"}}, probe=probe)
    assert info.kind == "other"
    assert probe.urls == []


def test_fqdn_ssh_host_auto_derives():
    probe = Probe()
    info = resolve("git@gitea.lan:home/lab.git", probe=probe)
    assert probe.urls == ["https://gitea.lan/api/v1/version"]
    assert info.kind == "gitea"
    assert info.web_base == "https://gitea.lan"


def test_failed_probe_of_ssh_derived_base_is_no_web_base():
    probe = Probe(mode="error")
    info = resolve("ssh://git@gitea.lan:2222/home/lab.git", probe=probe)
    assert info.kind == "other"
    assert "no web base" in info.reason
    assert SETUP_SUBSTR in info.reason


def test_failed_probe_of_https_origin_names_no_setup_line():
    probe = Probe(mode="404")
    info = resolve("https://gitlab.example.com/a/b.git", probe=probe)
    assert info.kind == "other"
    assert "unsupported forge" in info.reason
    assert "gitlab.example.com" in info.reason
    assert SETUP_SUBSTR not in info.reason


@pytest.mark.parametrize("mode", ["error", "404", "nonjson"])
def test_probe_failure_is_other(mode):
    assert resolve("https://gitea.lan/home/lab.git",
                   probe=Probe(mode=mode)).kind == "other"


def test_no_origin_remote_is_other():
    info = resolve(None)
    assert info.kind == "other"
    assert info.reason == "no origin"


# --- Result -----------------------------------------------------------------

def test_result_ok_carries_payload():
    res = forge.Result.ok({"url": "https://gitea.lan/home/lab/pulls/7"})
    assert res.status == "ok"
    assert res.payload == {"url": "https://gitea.lan/home/lab/pulls/7"}
    assert res.line == ""


def test_result_degraded_carries_one_line():
    res = forge.Result.degraded("unsupported forge: gitlab.example.com")
    assert res.status == "degraded"
    assert res.line == "unsupported forge: gitlab.example.com"


@pytest.mark.parametrize("line", ["", "two\nlines"])
def test_result_degraded_rejects_a_bad_line(line):
    with pytest.raises(ValueError):
        forge.Result.degraded(line)
