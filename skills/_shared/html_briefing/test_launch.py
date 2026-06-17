"""Tests for html_briefing/launch.py — display/headless branch tests.

Covers Task 1.5 of promote-html-briefing plan:
  (a) display present + xdg-open resolvable → writes file, calls opener, opened=True
  (b) headless (DISPLAY unset) → writes file, no opener, opened=False, fallback="terminal"
  (c) opener fails (raises or returns non-zero) → degrades to opened=False, fallback="terminal"
  (d) never raises — always degrades gracefully
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from launch import PresentResult, present_briefing
from renderer import SeedCard
from serializer import ConfirmModel, Question


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_model(tmp_path):
    """Minimal briefing model for testing."""
    confirm = ConfirmModel(questions=[
        Question(
            number=1, kind="single",
            options=[("a", "Option A")],
            default="a", chosen="a",
        ),
    ])
    wave = SimpleNamespace(
        seeds=["x"],
        waves=[["x"]],
        collisions=[],
        done=0,
        total=1,
    )
    seeds = [SeedCard(
        name="x", brief="test", weight_class="light",
        badges=[], branch="tp/x", sha="abc123",
        probe_banner=None, premise_refresh_banner=None,
    )]
    return SimpleNamespace(seeds=seeds, questions=confirm, wave_model=wave)


def _fake_opener_ok(path):
    """Opener that succeeds (returns 0)."""
    return 0


def _fake_opener_fail(path):
    """Opener that returns non-zero."""
    return 1


def _fake_opener_raises(path):
    """Opener that raises."""
    raise RuntimeError("browser exploded")


# ---------------------------------------------------------------------------
# (a) Display present + xdg-open resolvable
# ---------------------------------------------------------------------------

def test_display_present_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    result = present_briefing(model, out_path, env=env, opener=_fake_opener_ok)
    assert out_path.exists()


def test_display_present_returns_opened_true(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    result = present_briefing(model, out_path, env=env, opener=_fake_opener_ok)
    assert result.opened is True


def test_display_present_opener_called(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    calls = []

    def recording_opener(path):
        calls.append(path)
        return 0

    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    present_briefing(model, out_path, env=env, opener=recording_opener)
    assert len(calls) == 1
    assert calls[0] == out_path


# ---------------------------------------------------------------------------
# (b) Headless — DISPLAY unset
# ---------------------------------------------------------------------------

def test_headless_no_display_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    result = present_briefing(model, out_path, env={}, opener=_fake_opener_ok)
    assert out_path.exists()


def test_headless_no_display_returns_opened_false(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    result = present_briefing(model, out_path, env={}, opener=_fake_opener_ok)
    assert result.opened is False
    assert result.fallback == "terminal"


def test_headless_no_display_no_opener_call(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    calls = []

    def recording_opener(path):
        calls.append(path)
        return 0

    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    present_briefing(model, out_path, env={}, opener=recording_opener)
    assert len(calls) == 0


def test_headless_no_xdg_open(tmp_path, monkeypatch):
    """xdg-open not on PATH → headless fallback even with DISPLAY set."""
    monkeypatch.setattr("shutil.which", lambda x: None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    result = present_briefing(model, out_path, env=env, opener=_fake_opener_ok)
    assert result.opened is False
    assert result.fallback == "terminal"


# ---------------------------------------------------------------------------
# (c) Opener fails — non-zero return or exception
# ---------------------------------------------------------------------------

def test_opener_nonzero_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    result = present_briefing(model, out_path, env=env, opener=_fake_opener_fail)
    assert result.opened is False
    assert result.fallback == "terminal"
    assert out_path.exists()  # file was still written


def test_opener_raises_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/xdg-open" if x == "xdg-open" else None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    env = {"DISPLAY": ":0"}
    result = present_briefing(model, out_path, env=env, opener=_fake_opener_raises)
    assert result.opened is False
    assert result.fallback == "terminal"
    assert out_path.exists()


# ---------------------------------------------------------------------------
# (d) Never raises
# ---------------------------------------------------------------------------

def test_never_raises_on_bad_env(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    model = _make_model(tmp_path)
    out_path = tmp_path / "briefing.html"
    # Should not raise even with None env values
    result = present_briefing(model, out_path, env={}, opener=_fake_opener_raises)
    assert isinstance(result, PresentResult)
