"""Tests for seed_write.py text-by-file flags (lean-default-followups 1.2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_write as sw  # noqa: E402

TEXT = "see `skills/_shared/merge_gate.py` and $(id) as written"
SECTION = {"problem": "Problem", "direction": "Direction",
           "open-questions": "Open questions", "consumer": "Consumer-repo behaviour"}


def run(argv, repo):
    return sw.main([*argv, "--repo", str(repo)])


def section(path, name):
    body = Path(path).read_text(encoding="utf-8")
    return body.split(f"## {name}\n\n", 1)[1].split("\n\n## ", 1)[0].strip()


def textfile(tmp_path, text=TEXT, name="t.txt"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return str(f)


def seed(tmp_path, repo, slug="s"):
    assert run(["new", slug, "--source", "x", "--problem", "alpha beta gamma"], repo) == 0
    return sw.seed_path(repo, slug)


@pytest.mark.parametrize("key", list(SECTION))
def test_new_file_flag_keeps_text_byte_for_byte(tmp_path, key):
    repo = tmp_path / "repo"
    f = textfile(tmp_path)
    assert run(["new", "s", "--source", "x", f"--{key}-file", f], repo) == 0
    assert section(sw.seed_path(repo, "s"), SECTION[key]) == TEXT


@pytest.mark.parametrize("key", list(SECTION))
def test_new_inline_and_file_together_is_refused(tmp_path, capsys, key):
    repo = tmp_path / "repo"
    f = textfile(tmp_path)
    assert run(["new", "s", "--source", "x", f"--{key}", "a", f"--{key}-file", f], repo) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("seed_write:")
    assert not (repo / "three-pillars-docs" / "tp-designs" / "s").exists()


@pytest.mark.parametrize("key", list(SECTION))
def test_new_empty_inline_and_file_together_is_refused(tmp_path, capsys, key):
    repo = tmp_path / "repo"
    f = textfile(tmp_path)
    assert run(["new", "s", "--source", "x", f"--{key}", "", f"--{key}-file", f], repo) == 1
    assert capsys.readouterr().err.startswith("seed_write:")
    assert not (repo / "three-pillars-docs" / "tp-designs" / "s").exists()


def test_amend_text_file_appends_part_two(tmp_path):
    repo = tmp_path / "repo"
    path = seed(tmp_path, repo)
    assert run(["amend", "s", "--text-file", textfile(tmp_path)], repo) == 0
    assert section(path, "Part 2") == TEXT


def test_amend_both_or_neither_is_refused_and_leaves_seed(tmp_path, capsys):
    repo = tmp_path / "repo"
    path = seed(tmp_path, repo)
    before = path.read_bytes()
    capsys.readouterr()
    assert run(["amend", "s", "inline", "--text-file", textfile(tmp_path)], repo) == 1
    assert run(["amend", "s"], repo) == 1
    lines = capsys.readouterr().err.strip().splitlines()
    assert len(lines) == 2 and all(x.startswith("seed_write:") for x in lines)
    assert path.read_bytes() == before


def test_similar_text_file_matches_inline(tmp_path, capsys):
    repo = tmp_path / "repo"
    seed(tmp_path, repo)
    words = "alpha beta gamma"
    capsys.readouterr()
    assert run(["similar", words], repo) == 0
    inline = capsys.readouterr().out
    assert run(["similar", "--text-file", textfile(tmp_path, words)], repo) == 0
    from_file = capsys.readouterr().out
    assert inline == from_file == "s 3\n"


def test_missing_file_is_refused_and_writes_nothing(tmp_path, capsys):
    repo = tmp_path / "repo"
    missing = str(tmp_path / "nope.txt")
    assert run(["new", "s", "--source", "x", "--problem-file", missing], repo) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("seed_write:")
    assert not (repo / "three-pillars-docs" / "tp-designs" / "s").exists()
