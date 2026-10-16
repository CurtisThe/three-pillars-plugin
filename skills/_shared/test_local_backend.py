"""Tests for local_backend.py — the `--local` preflight probe for `tp-local`.

design: consumer-repo-parity (Phase 7)

`available(which=...)` reports whether the `tp-local` binary is on `PATH`. The
`--local` preflight (skills/tp-run-full-design/SKILL.md) and the `local` rung
(skills/_shared/local-dispatch.md) both name `local_backend.py`; the local-dispatch
reference is covered by skill_refs (invariant 46).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_backend  # noqa: E402
import skill_text  # noqa: E402

REFUSAL = ("local backend (local-llm-skills / tp-local) not installed — "
           "re-run without --local")


def test_available_false_when_which_returns_none():
    assert local_backend.available(which=lambda n: None) is False


def test_available_true_when_which_returns_a_path():
    assert local_backend.available(which=lambda n: "/x/tp-local") is True


def test_available_probes_the_tp_local_name():
    seen: list[str] = []

    def which(name: str):
        seen.append(name)
        return "/x/tp-local"

    local_backend.available(which=which)
    assert seen == ["tp-local"]


def test_main_returns_zero_and_stays_silent_when_available(capsys):
    assert local_backend.main(which=lambda n: "/x/tp-local") == 0
    assert capsys.readouterr().out == ""


def test_main_returns_one_and_prints_refusal_when_unavailable(capsys):
    assert local_backend.main(which=lambda n: None) == 1
    assert capsys.readouterr().out == REFUSAL + "\n"


def test_skill_md_local_preflight_names_local_backend():
    text = skill_text.read_skill_text("tp-run-full-design")
    para = next(line for line in text.splitlines() if line.startswith("**Local preflight**"))
    assert "local_backend.py" in para

