"""Tests for design_run_command.resume_window_command."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import design_run_command as drc  # noqa: E402

SID = "0a1b2c3d-1111-2222-3333-444455556666"


def test_example_line():
    got = drc.resume_window_command("my-slug", "/w t", SID, model="opus", effort="high")
    assert got == (
        "cd '/w t' && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 "
        f"claude --resume {SID} --model opus --effort high --name my-slug; exec bash"
    )


def test_mcp_goes_before_resume():
    got = drc.resume_window_command("s", "/w", SID, model="opus", effort="high", mcp="--mcp-config x")
    assert f"claude --mcp-config x --resume {SID} --model opus" in got


@pytest.mark.parametrize("kw", [
    {}, {"config_dir": "/p/a b"}, {"backend_env": "A=1"}, {"mcp": "--mcp-config m"},
    {"extra_env": (("K", "v w"),), "unset": ("Z",)},
])
def test_differential_against_window_command(kw):
    args = dict(model="sonnet", effort="medium", **kw)
    win = drc.window_command("abc-1", "/wt", mode="x", local=True, **args)
    res = drc.resume_window_command("abc-1", "/wt", SID, **args)
    slash = shlex.quote(drc.slash_command("abc-1", mode="x", local=True))
    tail = f" {slash}; exec bash"
    assert win.endswith(tail)
    base = win[: -len(tail)]
    assert res == base.replace("--model", f"--resume {SID} --model", 1) + "; exec bash"


@pytest.mark.parametrize("sid", ["", "a b", "a;b", "a/b", "x$y", None])
def test_bad_sid(sid):
    with pytest.raises(ValueError):
        drc.resume_window_command("s", "/w", sid, model="opus", effort="high")


def test_bad_slug_and_models():
    for bad in ("Bad Slug", ""):
        with pytest.raises(ValueError):
            drc.resume_window_command(bad, "/w", SID, model="opus", effort="high")
    for model in ("inherit", "", "fable-x"):
        with pytest.raises(ValueError):
            drc.resume_window_command("s", "/w", SID, model=model, effort="high")
    assert "--model fable-x" in drc.resume_window_command(
        "s", "/w", SID, model="fable-x", configured="fable-x", effort="high")
