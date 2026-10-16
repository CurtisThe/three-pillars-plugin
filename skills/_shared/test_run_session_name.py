"""Design runs launch with `--name <slug>`, so the session and its Remote Control entry carry the slug."""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import design_run_command as drc  # noqa: E402


def _name_arg(cmd: str) -> str:
    words = shlex.split(cmd.split("&&")[-1].split(";")[0])
    return words[words.index("--name") + 1]


def test_window_command_names_the_session_after_the_slug():
    cmd = drc.window_command("my-design", "/wt", skip_design=True)
    assert _name_arg(cmd) == "my-design"


def test_the_name_comes_before_the_slash_prompt():
    words = shlex.split(drc.window_command("my-design", "/wt", skip_design=True).split("&&")[-1])
    assert words.index("--name") < next(i for i, w in enumerate(words) if w.startswith("/tp-run-full-design"))

