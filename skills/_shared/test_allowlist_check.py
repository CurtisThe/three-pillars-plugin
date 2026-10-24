"""Tests for allowlist_mine --check: the stale-list advisory (classifier-allowlist, Task 1.7).

Spec-derived: the advisory warns when the recommended list holds entries the active
settings lack and when classifyAllShell is set; it is silent with no settings file and
exits 0 on every read path. Every test is hermetic (HOME and CLAUDE_CONFIG_DIR under tmp_path).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import allowlist_settings  # noqa: E402
from allowlist_mine import main  # noqa: E402
from allowlist_settings import entries_for, expand, load, root_forms  # noqa: E402

TP_ROOT = Path(allowlist_settings.__file__).resolve().parents[2]
LOCATION_LINE = "advisory: no exact-path rules for"


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True)
    (tmp_path / "home").mkdir()
    (tmp_path / "cfg").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path, repo


def _entries():
    return entries_for(load(), "github", TP_ROOT)


def _full_allow(repo):
    """The complete allow list for this checkout's root."""
    return expand(_entries(), root_forms(TP_ROOT, repo))


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")


def _check(repo, capsys):
    rc = main(["--check", "--repo", str(repo)])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    return rc, lines


def test_absent_settings_silent(env, capsys):
    _tmp, repo = env
    assert main(["--check", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out == ""


def test_missing_entries_advisory(env, capsys):
    tmp_path, repo = env
    _write(tmp_path / "cfg" / "settings.json", {"permissions": {"allow": []}})
    rc, lines = _check(repo, capsys)
    assert rc == 0
    missing = [ln for ln in lines if "recommended allow entries missing" in ln]
    assert len(missing) == 1
    assert missing[0].startswith("advisory: ")
    assert "--print-settings" in missing[0]
    others = [ln for ln in lines if ln not in missing]
    assert all(ln.startswith(LOCATION_LINE) for ln in others)


def test_text_root_counts_but_locations_hinted(env, capsys):
    tmp_path, repo = env
    elsewhere = expand(_entries(), root_forms(Path("/elsewhere/tp"), repo))
    _write(tmp_path / "cfg" / "settings.json", {"permissions": {"allow": elsewhere}})
    rc, lines = _check(repo, capsys)
    assert rc == 0
    assert not any("entries missing" in ln for ln in lines)
    location = [ln for ln in lines if ln.startswith(LOCATION_LINE)]
    assert len(location) == 1
    assert str(repo) not in location[0]
    assert str(TP_ROOT) in location[0]


def test_repo_settings_merge(env, capsys):
    tmp_path, repo = env
    allow = _full_allow(repo)
    half = len(allow) // 2
    _write(tmp_path / "cfg" / "settings.json", {"permissions": {"allow": allow[:half]}})
    _write(repo / ".claude" / "settings.local.json", {"permissions": {"allow": allow[half:]}})
    rc, lines = _check(repo, capsys)
    assert rc == 0
    assert lines == []


def test_classify_all_shell_advisory(env, capsys):
    tmp_path, repo = env
    _write(tmp_path / "cfg" / "settings.json",
           {"autoMode": {"classifyAllShell": True},
            "permissions": {"allow": _full_allow(repo)}})
    rc, lines = _check(repo, capsys)
    assert rc == 0
    assert len(lines) == 1
    assert lines[0].startswith("advisory: ")
    assert "classifyAllShell" in lines[0]


def test_unreadable_settings_advisory(env, capsys):
    tmp_path, repo = env
    _write(tmp_path / "cfg" / "settings.json", "{not json")
    rc, lines = _check(repo, capsys)
    assert rc == 0
    assert len(lines) == 1
    assert lines[0].startswith("advisory: cannot read")
