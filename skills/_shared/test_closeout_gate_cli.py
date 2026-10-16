"""CLI tests for closeout_gate.py, run as a real subprocess."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).with_name("closeout_gate.py")
DOCS = "three-pillars-docs"


def _run(repo, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args],
        capture_output=True,
        text=True,
    )


def _unarchived(root):
    d = root / DOCS / "tp-designs" / "demo"
    d.mkdir(parents=True)
    (d / "design.md").write_text("# D\n")
    (d / "implementation-audit.md").write_text("x\n")
    return d


def test_unarchived_exits_1_with_remedy(tmp_path):
    _unarchived(tmp_path)
    r = _run(tmp_path, "--design", "demo")
    assert r.returncode == 1
    assert "/tp-design-learn demo" in r.stderr
    assert "/tp-design-complete demo" in r.stderr
    assert "REFUSED" in r.stderr


def test_archived_exits_0(tmp_path):
    d = _unarchived(tmp_path)
    dest = tmp_path / DOCS / "completed-tp-designs" / "demo"
    dest.parent.mkdir(parents=True)
    d.rename(dest)
    (dest / "design.md").write_text("---\ncompleted: 2026-10-13\n---\n# D\n")
    r = _run(tmp_path, "--design", "demo")
    assert r.returncode == 0
    assert r.stdout.startswith("closeout-gate: proceed (archived")


def test_seed_only_exits_0(tmp_path):
    d = tmp_path / DOCS / "tp-designs" / "demo"
    d.mkdir(parents=True)
    (d / "seed.md").write_text("s\n")
    r = _run(tmp_path, "--design", "demo")
    assert r.returncode == 0
    assert "exempt" in r.stdout


def test_json_prints_one_object(tmp_path):
    _unarchived(tmp_path)
    r = _run(tmp_path, "--design", "demo", "--json")
    obj = json.loads(r.stdout)
    assert obj["status"] == "unarchived"
    assert r.returncode == 1


def test_invalid_slug_exits_2(tmp_path):
    assert _run(tmp_path, "--design", "Bad Slug").returncode == 2
