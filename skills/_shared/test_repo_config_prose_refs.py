"""Prose guard: per-key degrade, not whole-config drop.

design: consumer-repo-parity, Task 1.5.

`repo-config.md` §Fail-open must name the shipped validator
(`repo_config_load.py`) and say an invalid key alone is ignored with a
warning — only a `schema_version` mismatch or an unparseable file makes
the config absent. `first-run.md` condition 1 must route the invalid-key
rule to `repo-config.md`.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_CONFIG = (HERE / "repo-config.md").read_text(encoding="utf-8")
FIRST_RUN = (HERE / "first-run.md").read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body of `heading`, up to the next top-level `## ` heading."""
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines)
                 if line.rstrip("\n") == heading)
    body = "".join(lines[start:])
    nxt = body.find("\n## ", 1)
    return body if nxt == -1 else body[:nxt]


def test_fail_open_names_the_shipped_validator():
    section = _section(REPO_CONFIG, "## Fail-open behavior")
    assert "repo_config_load.py" in section, (
        "repo-config.md §Fail-open must name the shipped validator "
        "repo_config_load.py")


def test_fail_open_degrades_per_key_not_whole_config():
    section = _section(REPO_CONFIG, "## Fail-open behavior")
    assert "warning" in section
    assert "schema_version" in section
    assert "same as parse error" not in section, (
        "§Fail-open still equates a schema error with dropping the whole "
        "config")
    assert "as though it were absent" not in section, (
        "§Fail-open still drops the whole config on an invalid key")


def test_first_run_condition_one_routes_invalid_keys_to_repo_config():
    section = _section(FIRST_RUN, "## Cheap-path early-exit")
    cond = next(line for line in section.splitlines()
                if line.startswith("1. "))
    assert "repo-config.md" in cond
    assert "invalid" in cond.lower(), (
        "first-run.md condition 1 must reference the invalid-key rule "
        "in repo-config.md")
