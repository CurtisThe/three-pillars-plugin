"""Tests for seed_write.py amend slug check and estimated-lines stamp (lean-default-followups 1.1)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_write as sw  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

UNSAFE = ["../x", "A_b", "x/y", ""]
BAD_ESTIMATES = ["lots", 0, "0", -3, "1.5", True]
BAD_ESTIMATE_STRINGS = ["lots", "0", "-3", "1.5"]
DOCS = "three-pillars-docs"


def files(repo) -> list:
    return sorted(str(p) for p in Path(repo).rglob("*") if p.is_file())


def write(repo, **over):
    kw = {"repo": repo, "weight_class": "light", "source": "x", "seeded": "2026-10-23"}
    kw.update(over)
    return sw.write_new("s", **kw)


def test_amend_refuses_a_dotdot_slug_and_leaves_the_target_unchanged(tmp_path):
    target = tmp_path / DOCS / "x" / "seed.md"
    target.parent.mkdir(parents=True)
    target.write_text("original\n", encoding="utf-8")
    with pytest.raises(ValueError):
        sw.amend("../x", "t", repo=tmp_path)
    assert target.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("slug", UNSAFE)
def test_amend_refuses_an_unsafe_slug(tmp_path, slug):
    with pytest.raises(ValueError):
        sw.amend(slug, "t", repo=tmp_path)
    assert files(tmp_path) == []


@pytest.mark.parametrize("slug", UNSAFE)
def test_cli_amend_exits_1_with_one_seed_write_line(tmp_path, capsys, slug):
    assert sw.main(["amend", slug, "t", "--repo", str(tmp_path)]) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("seed_write:")
    assert files(tmp_path) == []


def test_write_new_stamps_estimated_lines(tmp_path):
    path = write(tmp_path, estimated_lines=40)
    assert parse_frontmatter(path.read_text(encoding="utf-8"))["estimated-lines"] == "40"


def test_cli_new_stamps_estimated_lines(tmp_path):
    args = ["new", "s", "--source", "x", "--estimated-lines", "40", "--repo", str(tmp_path)]
    assert sw.main(args) == 0
    text = sw.seed_path(tmp_path, "s").read_text(encoding="utf-8")
    assert parse_frontmatter(text)["estimated-lines"] == "40"


def test_estimated_lines_is_absent_when_omitted(tmp_path):
    path = write(tmp_path)
    assert "estimated-lines" not in parse_frontmatter(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("bad", BAD_ESTIMATES)
def test_write_new_refuses_a_bad_estimate_before_any_byte(tmp_path, bad):
    with pytest.raises(ValueError):
        write(tmp_path, estimated_lines=bad)
    assert not (tmp_path / DOCS / "tp-designs" / "s").exists()


@pytest.mark.parametrize("bad", BAD_ESTIMATE_STRINGS)
def test_cli_new_refuses_a_bad_estimate(tmp_path, capsys, bad):
    args = ["new", "s", "--source", "x", "--estimated-lines", bad, "--repo", str(tmp_path)]
    assert sw.main(args) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("seed_write:")
    assert files(tmp_path) == []
