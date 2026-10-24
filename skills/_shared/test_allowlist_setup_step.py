"""Tests for the /tp-setup allow-list step (classifier-allowlist, Task 1.8).

Spec-derived (B5): the step names the print command, SKILL.md never pairs a settings file
with a write, and the named command writes nothing. Hermetic: HOME, CLAUDE_CONFIG_DIR and
the repo live under tmp_path.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from allowlist_mine import main  # noqa: E402

SETUP = Path(__file__).resolve().parents[1] / "tp-setup" / "SKILL.md"
PRINT_CMD = 'python3 "$TP_ROOT"/skills/_shared/allowlist_mine.py --print-settings'


def _snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_setup_names_print_settings():
    assert PRINT_CMD in SETUP.read_text(encoding="utf-8")


def test_setup_never_pairs_settings_with_a_write():
    for line in SETUP.read_text(encoding="utf-8").splitlines():
        if "settings.json" in line:
            assert "Write" not in line and "Edit" not in line and ">" not in line, line


def test_setup_command_writes_nothing(tmp_path, monkeypatch, capsys):
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "cfg").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    before = _snapshot(tmp_path)
    rc = main(["--print-settings", "--repo", str(repo)])
    capsys.readouterr()
    assert rc == 0
    assert _snapshot(tmp_path) == before
