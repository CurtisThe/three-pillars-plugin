"""commit_guard.run validates staged changes fragments (followups-1023 item 12)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import commit_guard  # noqa: E402

FRAG = "three-pillars-docs/changes/demo.md"
TEMPLATE = (
    "---\nslug: demo\nkind: design\ndate: 2026-10-23\n---\n\n"
    "## Roadmap\n\n### Recent completions\n\n"
    "+ - **`demo`** — {token}, x\n"
)


def _stage(monkeypatch, root: Path, staged: list, token: str) -> None:
    """Real index: the guard validates the staged blob, so `git add` each path."""
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        monkeypatch.delenv(var, raising=False)
    path = root / FRAG
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE.format(token=token), encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "add", "--", *staged], cwd=str(root), check=True)


def test_bad_staged_fragment_blocks(tmp_path, monkeypatch):
    _stage(monkeypatch, tmp_path, [FRAG], "Completion PR pending")
    assert commit_guard.run(tmp_path, "pre-commit") == 1


def test_valid_staged_fragment_passes(tmp_path, monkeypatch):
    _stage(monkeypatch, tmp_path, [FRAG], "Done — {pr}")
    assert commit_guard.run(tmp_path, "pre-commit") == 0


def test_no_fragment_staged_passes(tmp_path, monkeypatch):
    _stage(monkeypatch, tmp_path, ["README.md"], "Completion PR pending")
    assert commit_guard.run(tmp_path, "pre-commit") == 0
