"""Tests for lessons paths and read (fable-escalation 2.1)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lessons  # noqa: E402

ENTRY_TEXT = (
    "### L1 — Audit bar is real usage\n"
    "- applies when: a finding's blocking status is decided\n"
    "- lesson: block only on high\n"
    "- sources: seed, demo-20261011-abcdef\n"
    "- date: 2026-10-11\n"
)


def test_repo_rel():
    assert lessons.REPO_REL == "three-pillars-docs/escalations/lessons.md"


def test_user_path_honours_config_dir():
    assert lessons.user_path({"CLAUDE_CONFIG_DIR": "/x/cfg"}) == Path(
        "/x/cfg/three-pillars/lessons.md")


def test_user_path_default():
    assert lessons.user_path({}) == Path.home() / ".claude/three-pillars/lessons.md"


def test_read_missing_is_empty(tmp_path):
    assert lessons.read(tmp_path / "lessons.md") == []


def test_read_parses_entries(tmp_path):
    path = tmp_path / "lessons.md"
    path.write_text(ENTRY_TEXT, encoding="utf-8")
    assert lessons.read(path) == [{
        "id": "L1",
        "title": "Audit bar is real usage",
        "applies_when": "a finding's blocking status is decided",
        "lesson": "block only on high",
        "sources": ["seed", "demo-20261011-abcdef"],
        "date": "2026-10-11",
    }]


PROPOSAL = {
    "action": "add",
    "layer": "repo",
    "text": "Prefer a new file over growing a pinned one.",
    "applies_when": "a task would grow a size-pinned file",
    "contradicts": [],
}


def test_add_appends_next_id(tmp_path):
    path = tmp_path / "lessons.md"
    result = lessons.add(path, PROPOSAL, "demo-20261011-abcdef", "2026-10-11")
    assert result == {"status": "added", "id": "L1"}
    assert path.read_text(encoding="utf-8").startswith("# Lessons\n\n")
    entries = lessons.read(path)
    assert len(entries) == 1
    assert entries[0]["id"] == "L1"
    assert entries[0]["title"] == PROPOSAL["text"]
    assert entries[0]["applies_when"] == PROPOSAL["applies_when"]
    assert entries[0]["lesson"] == PROPOSAL["text"]
    assert entries[0]["sources"] == ["demo-20261011-abcdef"]
    assert entries[0]["date"] == "2026-10-11"
    second = dict(PROPOSAL, text="Never bypass a hook.")
    result2 = lessons.add(path, second, "seed", "2026-10-12")
    assert result2 == {"status": "added", "id": "L2"}
    assert [e["id"] for e in lessons.read(path)] == ["L1", "L2"]


def test_add_cap_reached(tmp_path):
    path = tmp_path / "lessons.md"
    for n in range(60):
        result = lessons.add(path, dict(PROPOSAL, text=f"Lesson number {n}."),
                             "seed", "2026-10-11")
        assert result["status"] == "added"
    before = path.read_bytes()
    result = lessons.add(path, dict(PROPOSAL, text="One more lesson."),
                         "seed", "2026-10-11")
    assert result == {"status": "cap-reached"}
    assert path.read_bytes() == before


def test_add_contradiction_refused(tmp_path):
    path = tmp_path / "lessons.md"
    proposal = dict(PROPOSAL, contradicts=[{
        "doc": "vision.md",
        "section": "Non-goals",
        "quote": "The framework never edits project docs.",
    }])
    result = lessons.add(path, proposal, "seed", "2026-10-11")
    assert result["status"] == "refused-contradiction"
    docs_update = result["docs_update"]
    assert "/tp-docs-update" in docs_update
    assert "vision.md § Non-goals" in docs_update
    assert "The framework never edits project docs." in docs_update
    assert not path.exists()


def test_add_duplicate(tmp_path):
    path = tmp_path / "lessons.md"
    lessons.add(path, PROPOSAL, "a", "2026-10-11")
    before = path.read_bytes()
    dup = dict(PROPOSAL, text="Prefer  a new file over growing\na pinned  one.")
    result = lessons.add(path, dup, "b", "2026-10-12")
    assert result == {"status": "duplicate", "id": "L1"}
    assert path.read_bytes() == before


def test_remove_entry(tmp_path):
    path = tmp_path / "lessons.md"
    lessons.add(path, PROPOSAL, "a", "2026-10-11")
    lessons.add(path, dict(PROPOSAL, text="Second lesson."), "b", "2026-10-12")
    result = lessons.remove(path, "L1", "a")
    assert result == {"status": "removed", "id": "L1"}
    entries = lessons.read(path)
    assert [e["id"] for e in entries] == ["L2"]
    assert entries[0]["lesson"] == "Second lesson."


def test_remove_unknown_id(tmp_path):
    path = tmp_path / "lessons.md"
    lessons.add(path, PROPOSAL, "a", "2026-10-11")
    before = path.read_bytes()
    result = lessons.remove(path, "L9", "a")
    assert result == {"status": "not-found", "id": "L9"}
    assert path.read_bytes() == before


def test_repo_seed_parses():
    root = Path(__file__).resolve().parents[2]
    seed = root / lessons.REPO_REL
    if not seed.is_file():
        pytest.skip("repo seed is dev-repo only")
    entries = lessons.read(seed)
    assert [e["id"] for e in entries] == ["L1", "L2", "L3", "L4"]
    for entry in entries:
        assert entry["applies_when"]
        assert entry["lesson"]
        assert entry["sources"] == ["seed"]
        assert entry["date"] == "2026-10-11"


def test_repo_seed_skips_in_consumer_copy(tmp_path):
    here = Path(__file__).resolve().parent
    dest = tmp_path / "skills" / "_shared"
    dest.mkdir(parents=True)
    for name in ("lessons.py", "test_lessons.py"):
        (dest / name).write_text((here / name).read_text(encoding="utf-8"),
                                 encoding="utf-8")
    # The -k filter keeps the copy from re-running this subprocess test.
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(dest / "test_lessons.py"),
         "-q", "-p", "no:cacheprovider", "-k", "test_repo_seed_parses"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 skipped" in done.stdout


def test_add_empty_text_refused(tmp_path):
    path = tmp_path / "lessons.md"
    result = lessons.add(path, dict(PROPOSAL, text="  \n\t "), "seed",
                         "2026-10-11")
    assert result == {"status": "empty"}
    assert not path.exists()


def test_remove_keeps_trailing_section(tmp_path):
    path = tmp_path / "lessons.md"
    path.write_text("# Lessons\n\n" + ENTRY_TEXT + "\n## Notes\nkeep this\n",
                    encoding="utf-8")
    result = lessons.remove(path, "L1", "s")
    assert result == {"status": "removed", "id": "L1"}
    assert "## Notes\nkeep this\n" in path.read_text(encoding="utf-8")
    assert lessons.read(path) == []
