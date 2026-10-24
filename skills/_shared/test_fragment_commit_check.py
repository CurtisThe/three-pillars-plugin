"""Tests for fragment_commit_check (design: followups-1023 item 12)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fragment_commit_check  # noqa: E402

FRAG = "three-pillars-docs/changes/demo.md"
TEMPLATE = (
    "---\nslug: demo\nkind: design\ndate: 2026-10-23\n---\n\n"
    "## Roadmap\n\n### Recent completions\n\n"
    "+ - **`demo`** — {token}, x\n"
)


def _write(root: Path, rel: str, token: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(token=token), encoding="utf-8")


def _run(root: Path, *paths: str) -> int:
    return fragment_commit_check.main(["--repo-root", str(root), *paths])


def test_bad_fragment_exits_1_and_names_path(tmp_path, capsys):
    _write(tmp_path, FRAG, "Completion PR pending")
    assert _run(tmp_path, FRAG) == 1
    err = capsys.readouterr().err
    assert FRAG in err
    assert "Done — {pr}" in err


def test_valid_fragment_exits_0(tmp_path):
    _write(tmp_path, FRAG, "Done — {pr}")
    assert _run(tmp_path, FRAG) == 0


def test_non_fragment_paths_are_ignored(tmp_path):
    _write(tmp_path, "README.md", "Completion PR pending")
    _write(tmp_path, "three-pillars-docs/changes/sub/x.md", "Completion PR pending")
    assert _run(tmp_path, "README.md", "three-pillars-docs/changes/sub/x.md") == 0


def test_missing_fragment_file_exits_0(tmp_path):
    assert _run(tmp_path, FRAG) == 0
