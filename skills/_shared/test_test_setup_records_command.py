"""test_test_setup_records_command.py — Task 6.2: /tp-test-setup records test.command.

Pins `skills/tp-test-setup/SKILL.md` (consumer-repo-parity, part C §M2) to the
tokens the record path needs — never the surrounding prose:

  * step 6b names the shell entry point `repo_config_load.py set` (the Task 1.2
    CLI) with the keys `test.command` and `test.runner`;
  * step 10 stages `.three-pillars/config.json`;
  * the `runner: "other"` path names `unverified (non-pytest runner)` as a
    status token.

Plus one behaviour check: in a scratch git repo that first commits
`{"schema_version": 1}`, `update_config(tmp, "test.command", ...)` then
`update_config(tmp, "test.runner", "other")` must yield a schema-valid config
(no prune warnings from `load_repo_config`) that
`iteration_lane.discover_test_command` returns.

Stdlib only; reads only shipped files under `skills/`.
Run with: python3 -m pytest skills/_shared/test_test_setup_records_command.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import iteration_lane  # noqa: E402
import repo_config_load  # noqa: E402

# Inherited GIT_* env vars are scrubbed from every git subprocess copy so the
# fixture repo's own local identity wins (same pattern as
# test_repo_config_load.py and fixtures/foreign_repo.py).
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _skill_md_text() -> str:
    root = Path(__file__).parent.parent.parent  # repo root
    skill_path = root / "skills" / "tp-test-setup" / "SKILL.md"
    return skill_path.read_text(encoding="utf-8")


def _step_text(text: str, step: str) -> str:
    """The body of one numbered step: from `NN. **` to the next numbered
    step marker (`NN. **`) or the end of the section — nested bullets included,
    the following step's heading excluded."""
    start = re.compile(rf"^{re.escape(step)}\.\s+\*\*")
    next_step = re.compile(r"^\d+\.\s+\*\*")
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if capturing and next_step.match(line) and not start.match(line):
            break
        if start.match(line):
            capturing = True
        if capturing:
            out.append(line)
    return "\n".join(out)


# --- prose pins: step 6b names the writer CLI + both keys ---------------------

def test_step_6b_names_the_repo_config_writer_cli():
    step = _step_text(_skill_md_text(), "6b")
    assert "repo_config_load.py set" in step, (
        "skills/tp-test-setup/SKILL.md step 6b must name the shell entry "
        "point 'repo_config_load.py set' (the Task 1.2 writer CLI)."
    )


def test_step_6b_records_test_command():
    step = _step_text(_skill_md_text(), "6b")
    assert "test.command" in step, (
        "skills/tp-test-setup/SKILL.md step 6b must set the 'test.command' "
        "key through the writer CLI."
    )


def test_step_6b_records_test_runner():
    step = _step_text(_skill_md_text(), "6b")
    assert "test.runner" in step, (
        "skills/tp-test-setup/SKILL.md step 6b must set the 'test.runner' "
        "key ('pytest' or 'other') through the writer CLI."
    )


# --- prose pin: step 10 stages the config file --------------------------------

def test_step_10_stages_the_repo_config():
    step = _step_text(_skill_md_text(), "10")
    assert ".three-pillars/config.json" in step, (
        "skills/tp-test-setup/SKILL.md step 10 must stage "
        "'.three-pillars/config.json' among the committed artifacts."
    )


# --- prose pin: the non-pytest status token ------------------------------------

def test_non_pytest_runner_status_token_named():
    text = _skill_md_text()
    assert "unverified (non-pytest runner)" in text, (
        "skills/tp-test-setup/SKILL.md must name 'unverified (non-pytest "
        "runner)' as the status token a runner: \"other\" repo reports "
        "downstream, instead of the verification crashing."
    )


# --- behaviour: the recorded keys validate and are readable -------------------

def _git(root: Path, *args: str) -> None:
    env = dict(CLEAN_ENV)
    env["HOME"] = str(root)  # the fixture repo's local config, never the user's
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, env=env,
    )


def test_update_config_test_block_valid_and_discoverable(tmp_path):
    """A repo that commits `{"schema_version": 1}` first: recording
    `test.command` then `test.runner: "other"` yields a schema-valid config
    (no prune warnings) that `discover_test_command` returns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# fixture\n", encoding="utf-8")
    cfg_dir = repo / ".three-pillars"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"schema_version": 1}) + "\n",
                                         encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t62@test.local")
    _git(repo, "config", "user.name", "T62 Fixture")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    repo_config_load.update_config(repo, "test.command", "npm test")
    repo_config_load.update_config(repo, "test.runner", "other")

    loaded = repo_config_load.load_repo_config(repo)
    assert loaded.warnings == [], (
        "recording test.command + test.runner must be schema-valid: "
        f"got prune warnings {loaded.warnings!r}"
    )
    assert loaded.config["test"]["command"] == "npm test"
    assert loaded.config["test"]["runner"] == "other"
    assert iteration_lane.discover_test_command(repo) == "npm test"
