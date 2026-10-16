"""Tests for fable_notice.fable_notice — the design-run fable warning + log entry.

design: consumer-repo-parity (Task 7.2). A design-run model that *contains*
`fable` (case-insensitive — the alias `fable` or a `claude-fable-…` id) is a
rare-exception: `fable_notice` prints exactly one warning line to stderr,
returns that line, and (when `write`) appends one `### [design-run] fable model`
entry to the design's decisions.md. Any other model — `opus`, `sonnet`,
`claude-opus-4-8`, … — is the default path: `fable_notice` returns None and
touches nothing. The per-run-once contract (one warning + one entry per run) is
the launcher's (7.5/7.6); here two calls append two entries.
Run with: python3 -m pytest skills/_shared/test_model_policy_fable.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fable_notice as mp  # noqa: E402


FABLE_MODELS = ["fable", "claude-fable-x", "FABLE", "Claude-Fable-9"]
NON_FABLE_MODELS = ["opus", "sonnet", "claude-opus-4-8", "gpt-5", "qwen-coder"]

ENTRY_HEADING = "### [design-run] fable model"
# The warning line must name both the config location and the model.
REQUIRED = ("models.design_run", "fable")


def _stderr_lines(capsys):
    return [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]


# --- returns + prints for a fable model --------------------------------------

@pytest.mark.parametrize("model", FABLE_MODELS)
def test_fable_model_returns_a_single_warning_line(tmp_path, capsys, model):
    p = tmp_path / "decisions.md"
    line = mp.fable_notice(model, p, launcher="pytest")
    assert line is not None
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    # Exactly one line, printed once, naming the config location and the model.
    assert len(lines) == 1
    for token in REQUIRED:
        assert token in line
    assert "fable" in lines[0]


# --- writes one decisions.md entry for a fable model -------------------------

@pytest.mark.parametrize("model", FABLE_MODELS)
def test_fable_model_appends_one_entry(tmp_path, capsys, model):
    p = tmp_path / "decisions.md"
    mp.fable_notice(model, p, launcher="tp-run-full-design")
    text = p.read_text(encoding="utf-8")
    assert text.count(ENTRY_HEADING) == 1
    assert text.count("**Model**") == 1
    assert model in text
    assert "tp-run-full-design" in text


def test_fable_notice_creates_missing_file_and_parent_dir(tmp_path):
    p = tmp_path / "designs" / "consumer-repo-parity" / "decisions.md"
    assert not p.exists()
    line = mp.fable_notice("fable", p, launcher="tp-phase-implement")
    assert line is not None
    assert p.exists()
    assert p.read_text(encoding="utf-8").count(ENTRY_HEADING) == 1


def test_fable_notice_appends_below_existing_content(tmp_path):
    p = tmp_path / "decisions.md"
    p.write_text(
        "# decisions\n\n### [design] prior decision\n**Note**: earlier\n",
        encoding="utf-8",
    )
    mp.fable_notice("fable", p, launcher="pytest")
    text = p.read_text(encoding="utf-8")
    # Existing entry survives; the new fable entry is appended after it.
    assert "### [design] prior decision" in text
    assert text.count(ENTRY_HEADING) == 1
    assert text.index(ENTRY_HEADING) > text.index("### [design] prior decision")
    assert text.index("**Model**: fable") > text.index(ENTRY_HEADING)


# --- write=False still prints, never touches the file -------------------------

def test_write_false_prints_but_does_not_write(tmp_path, capsys):
    p = tmp_path / "decisions.md"
    line = mp.fable_notice("fable", p, write=False, launcher="pytest")
    assert line is not None
    assert len(_stderr_lines(capsys)) == 1
    assert not p.exists()


def test_write_false_leaves_existing_file_untouched(tmp_path, capsys):
    p = tmp_path / "decisions.md"
    p.write_text("seed\n", encoding="utf-8")
    assert mp.fable_notice("fable", p, write=False, launcher="pytest") is not None
    assert p.read_text(encoding="utf-8") == "seed\n"


# --- any other model: None, nothing printed, nothing written -----------------

@pytest.mark.parametrize("model", NON_FABLE_MODELS)
def test_non_fable_model_does_nothing(tmp_path, capsys, model):
    p = tmp_path / "decisions.md"
    assert mp.fable_notice(model, p, launcher="pytest") is None
    assert _stderr_lines(capsys) == []
    assert not p.exists()


@pytest.mark.parametrize("model", NON_FABLE_MODELS)
def test_non_fable_model_leaves_existing_file_untouched(tmp_path, capsys, model):
    p = tmp_path / "decisions.md"
    p.write_text("seed\n", encoding="utf-8")
    assert mp.fable_notice(model, p, launcher="pytest") is None
    assert p.read_text(encoding="utf-8") == "seed\n"
    assert _stderr_lines(capsys) == []


# --- two calls append two entries (per-run-once is the launcher's) -----------

def test_two_calls_append_two_entries(tmp_path, capsys):
    p = tmp_path / "decisions.md"
    mp.fable_notice("fable", p, launcher="run-a")
    mp.fable_notice("claude-fable-x", p, launcher="run-b")
    text = p.read_text(encoding="utf-8")
    assert text.count(ENTRY_HEADING) == 2
    assert text.count("**Model**") == 2
    assert "run-a" in text and "run-b" in text
