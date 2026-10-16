"""test_launcher_effort.py — design_run_command effort wiring (run-throughput 6.1).

Pins the `env -u CLAUDE_CODE_EFFORT_LEVEL` prefix, the `--effort <effort>`
argument, and the ABSENCE of the `TP_STAGE_RESET=pane` stage-reset marker
(Part F ships dormant, Task 7.5 seat ruling) against the detailed-design
"Launchers and pins" section:
  * `env_prefix(config_dir)` leads with `env -u CLAUDE_CODE_EFFORT_LEVEL`;
  * `effort_args(effort=DEFAULT_EFFORT)` -> `"--effort <effort>"`, ValueError on
    a value outside `model_policy.EFFORTS`;
  * no `interactive_env()` builder and no marker in any launcher shape;
  * `window_command`'s exact string, with the model still a `model_for`
    default (never a literal) and the effort `model_policy.effort_for`.
"""
from __future__ import annotations

import shlex

import pytest

import model_policy
import design_run_command as drc

DEFAULT_MODEL = model_policy.model_for("design_run", None)
DEFAULT_EFFORT = model_policy.effort_for("design_run")


# --- env_prefix: the `env -u` un-set leads the command ----------------------


def test_env_prefix_none_unsets_effort_level():
    assert drc.env_prefix(None) == "env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 "


def test_env_prefix_quoted_config_dir():
    assert drc.env_prefix("/p/my prof") == (
        "env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 CLAUDE_CONFIG_DIR='/p/my prof' "
    )


def test_env_prefix_has_no_effort_assignment():
    # The effort is a flag, never an env assignment: the `=...` form must be gone.
    for prefix in (drc.env_prefix(None), drc.env_prefix("/p")):
        assert "CLAUDE_CODE_EFFORT_LEVEL=" not in prefix


# --- effort_args: the `--effort <effort>` builder ---------------------------


def test_default_effort_is_the_policy_effort():
    assert drc.DEFAULT_EFFORT == DEFAULT_EFFORT == "high"


def test_effort_args_default():
    assert drc.effort_args() == "--effort high"
    assert drc.effort_args() == f"--effort {DEFAULT_EFFORT}"


@pytest.mark.parametrize("effort", model_policy.EFFORTS)
def test_effort_args_accepted(effort):
    assert drc.effort_args(effort) == f"--effort {effort}"


@pytest.mark.parametrize("bad", ["", "ultra", "High", "off"])
def test_effort_args_rejects_outside_vocabulary(bad):
    with pytest.raises(ValueError):
        drc.effort_args(bad)


def test_effort_args_rejects_non_string():
    with pytest.raises(ValueError):
        drc.effort_args(None)


# --- stage reset is dormant: no launcher exports the marker ------------------


def test_interactive_env_builder_removed():
    # Re-enabling the reset must be a deliberate act (stage-reset-supervisor).
    assert not hasattr(drc, "interactive_env")
    assert "TP_STAGE_RESET" not in drc.env_prefix(None)
    assert "TP_STAGE_RESET" not in drc.env_prefix("/p")


# --- window_command: the exact emitted string --------------------------------


def test_window_command_default_exact_string():
    assert drc.window_command("foo", "/w t/foo", config_dir="/p") == (
        "cd '/w t/foo' && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 "
        "CLAUDE_CONFIG_DIR=/p claude "
        f"--model {shlex.quote(DEFAULT_MODEL)} --effort high --name foo '/tp-run-full-design foo'; exec bash"
    )


def test_window_command_default_model_is_policy_default():
    # The model default is model_policy's, never a hardcoded literal; it is
    # shlex-quoted on the command line (the `opus[1m]` default carries quotes).
    assert drc.DEFAULT_MODEL == DEFAULT_MODEL
    assert f"--model {shlex.quote(DEFAULT_MODEL)}" in drc.window_command("foo", "/w")


def test_window_command_effort_overridable():
    assert drc.window_command("foo", "/w", effort="low") == (
        "cd /w && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 "
        f"claude --model {shlex.quote(DEFAULT_MODEL)} --effort low --name foo '/tp-run-full-design foo'; exec bash"
    )


def test_window_command_explicit_model_effort():
    assert drc.window_command("foo", "/w", model="opus", effort="xhigh") == (
        "cd /w && env -u CLAUDE_CODE_EFFORT_LEVEL TP_DESIGN_RUN=1 "
        "claude --model opus --effort xhigh --name foo '/tp-run-full-design foo'; exec bash"
    )


def test_window_command_strips_effort_and_has_no_reset_marker():
    cmd = drc.window_command("foo", "/w")
    assert "env -u CLAUDE_CODE_EFFORT_LEVEL" in cmd
    assert "TP_STAGE_RESET" not in cmd
    assert "CLAUDE_CODE_EFFORT_LEVEL=" not in cmd


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
