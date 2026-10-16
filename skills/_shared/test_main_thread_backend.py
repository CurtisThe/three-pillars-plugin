"""Tests for main_thread_backend.py — the warn-only main-thread backend preflight.

design: main-thread-direct-backend (S2)

`check(env)` returns one `W:` line when the calling main thread's env is routed
(`ANTHROPIC_BASE_URL` on a non-Anthropic host, or `ANTHROPIC_DEFAULT_HAIKU_MODEL`
naming a local model) and `None` in a direct env. The CLI never blocks: it prints
at most that one line and always exits 0. Fakes/env dicts only; nothing is spawned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main_thread_backend  # noqa: E402

ROUTED_URL = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3457"}
ROUTED_MODEL = {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "strata"}


def test_routed_url_gives_one_warn_line_naming_the_seat_launch():
    line = main_thread_backend.check(ROUTED_URL)
    assert line is not None
    assert line.startswith("W:")
    assert "\n" not in line
    assert "CLAUDE_LAUNCHER_ROLE=seat" in line
    assert "claude --seat" in line


def test_local_haiku_model_gives_one_warn_line():
    line = main_thread_backend.check(ROUTED_MODEL)
    assert line is not None
    assert line.startswith("W:")
    assert "\n" not in line


def test_both_keys_set_give_exactly_one_line():
    line = main_thread_backend.check({**ROUTED_URL, **ROUTED_MODEL})
    assert line is not None
    assert line.startswith("W:")
    assert "\n" not in line
    assert line.count("W:") == 1


@pytest.mark.parametrize("env", [
    {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"},
    {"ANTHROPIC_BASE_URL": "https://api.anthropic.com:443/v1"},
    {"ANTHROPIC_BASE_URL": "https://anthropic.com"},
    {"ANTHROPIC_BASE_URL": ""},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5"},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "haiku"},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "sonnet"},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "opus"},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": "fable"},
    {"ANTHROPIC_DEFAULT_HAIKU_MODEL": ""},
    {},
])
def test_direct_env_gives_none(env):
    assert main_thread_backend.check(env) is None


def test_lookalike_host_is_routed():
    # "notanthropic.com" and "anthropic.com.evil.example" are not Anthropic hosts.
    for url in ("https://notanthropic.com", "https://anthropic.com.evil.example"):
        assert main_thread_backend.check({"ANTHROPIC_BASE_URL": url}) is not None


def test_subdomain_of_anthropic_is_direct():
    assert main_thread_backend.check(
        {"ANTHROPIC_BASE_URL": "https://eu.api.anthropic.com"}) is None


def test_unparseable_url_counts_as_routed():
    assert main_thread_backend.check({"ANTHROPIC_BASE_URL": "http://[::1"}) is not None


def test_routed_reason_is_none_when_direct_and_text_when_routed():
    assert main_thread_backend.routed_reason({}) is None
    assert main_thread_backend.routed_reason(ROUTED_URL)
    assert main_thread_backend.routed_reason(ROUTED_MODEL)


def test_seat_launch_constant_names_both_spellings():
    launch = main_thread_backend.SEAT_LAUNCH
    assert "CLAUDE_LAUNCHER_ROLE=seat claude" in launch
    assert "claude --seat" in launch


def test_main_check_prints_one_line_and_returns_zero_when_routed(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:3457")
    assert main_thread_backend.main(["check"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("W:")
    assert len(out.splitlines()) == 1


def test_main_check_prints_nothing_and_returns_zero_when_direct(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_DEFAULT_HAIKU_MODEL", raising=False)
    assert main_thread_backend.main(["check"]) == 0
    assert capsys.readouterr().out == ""


def test_main_with_no_args_or_bogus_arg_still_returns_zero(monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:3457")
    assert main_thread_backend.main([]) == 0
    assert main_thread_backend.main(["bogus"]) == 0
    assert len(capsys.readouterr().out.splitlines()) <= 1


def test_main_returns_zero_even_when_check_raises(monkeypatch):
    def boom(env):
        raise RuntimeError("boom")
    monkeypatch.setattr(main_thread_backend, "check", boom)
    assert main_thread_backend.main(["check"]) == 0
