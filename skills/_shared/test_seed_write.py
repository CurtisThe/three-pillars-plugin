"""Tests for seed_write.py (weight-class-lean-default 1.4): new, amend, similar, the CLI."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import seed_write as sw  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

AXES = {"risk": "low", "blast-radius": "low", "reversibility": "high", "novelty": "low"}
KEYS = ["slug", "weight-class", "risk", "blast-radius", "reversibility", "novelty",
        "status", "seeded", "source"]
HEADINGS = ["Problem", "Direction", "Open questions", "Consumer-repo behaviour"]


def new(repo, slug="lean-seed", **over):
    kw = {"repo": repo, "weight_class": "light", "source": "operator ask", "axes": AXES,
          "problem": "Seeds lean heavy.", "direction": "Add a writer.",
          "open_questions": "None yet.", "consumer": "No config.", "seeded": "2026-10-23"}
    kw.update(over)
    return sw.write_new(slug, **kw)


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def open_seed(repo, slug, problem, status="seed"):
    path = sw.seed_path(repo, slug)
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nslug: {slug}\nstatus: {status}\n---\n# {slug}\n\n## Problem\n\n"
                    f"{problem}\n\n## Direction\n\nx\n", encoding="utf-8")


def test_frontmatter_is_one_fenced_line_per_key_in_a_fixed_order():
    fm = sw.frontmatter(weight_class="full", slug="a-b", status="seed", source="x")
    assert fm.splitlines() == ["---", "slug: a-b", "weight-class: full", "status: seed",
                               "source: x", "---"]


def test_frontmatter_defaults_to_light_skips_none_and_appends_extra_in_order():
    fm = sw.frontmatter(extra={"origin": "run-retro", "type": "Bug", "skill": None})
    assert fm.splitlines() == ["---", "weight-class: light", "status: seed",
                               "origin: run-retro", "type: Bug", "---"]


def test_frontmatter_folds_a_newline_in_a_value_to_one_line():
    fm = sw.frontmatter(source="line one\nline two")
    assert "source: line one line two\n" in fm


def test_new_writes_the_frontmatter_keys_in_order(tmp_path):
    path = new(tmp_path)
    assert path == tmp_path / "three-pillars-docs" / "tp-designs" / "lean-seed" / "seed.md"
    fm = parse_frontmatter(read(path))
    assert list(fm) == KEYS
    assert fm["slug"] == "lean-seed" and fm["weight-class"] == "light"
    assert fm["status"] == "seed" and fm["seeded"] == "2026-10-23"
    assert fm["source"] == "operator ask"
    assert {k: fm[k] for k in AXES} == AXES


def test_new_writes_the_four_sections_in_order_with_their_text(tmp_path):
    text = read(new(tmp_path))
    assert re.findall(r"^## (.+)$", text, re.MULTILINE) == HEADINGS
    for body in ("Seeds lean heavy.", "Add a writer.", "None yet.", "No config."):
        assert body in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_new_without_axes_writes_no_axis_keys(tmp_path):
    fm = parse_frontmatter(read(new(tmp_path, axes=None)))
    assert list(fm) == ["slug", "weight-class", "status", "seeded", "source"]


def test_new_defaults_seeded_to_today(tmp_path):
    fm = parse_frontmatter(read(new(tmp_path, seeded=None)))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fm["seeded"])


def test_new_refuses_an_existing_slug_and_keeps_the_seed(tmp_path):
    path = new(tmp_path)
    before = read(path)
    with pytest.raises(FileExistsError):
        new(tmp_path, problem="different")
    assert read(path) == before


def test_new_refuses_a_slug_that_is_already_a_design(tmp_path):
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "lean-seed"
    design.mkdir(parents=True)
    (design / "design.md").write_text("# d\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        new(tmp_path)
    assert not (design / "seed.md").exists()


@pytest.mark.parametrize("over", [
    {"slug": "../evil"}, {"slug": "Bad_Slug"}, {"slug": ""}, {"weight_class": "heavy"},
    {"axes": {"risk": "low"}}, {"axes": {**AXES, "risk": "extreme"}}])
def test_new_refuses_bad_input_before_writing_anything(tmp_path, over):
    slug = over.pop("slug", "lean-seed")
    with pytest.raises(ValueError):
        new(tmp_path, slug, **over)
    assert not (tmp_path / "three-pillars-docs").exists()


def test_amend_appends_part_2_then_part_3_and_keeps_the_original(tmp_path):
    path = new(tmp_path)
    original = read(path)
    assert sw.amend("lean-seed", "A second thought.", repo=tmp_path) == 2
    assert sw.amend("lean-seed", "A third thought.", repo=tmp_path) == 3
    text = read(path)
    assert text.startswith(original.rstrip("\n"))
    assert re.findall(r"^## Part (\d+)$", text, re.MULTILINE) == ["2", "3"]
    assert text.index("A second thought.") < text.index("## Part 3") < text.index("A third")


def test_amend_of_a_missing_seed_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        sw.amend("no-such-seed", "text", repo=tmp_path)


def test_similar_ranks_open_seeds_by_word_overlap_and_caps_at_three(tmp_path):
    open_seed(tmp_path, "alpha-seed", "Retro friction around permission cards in tp-design.")
    open_seed(tmp_path, "beta-seed", "Permission cards block the design run.")
    open_seed(tmp_path, "gamma-seed", "Seeds about permission handling.")
    open_seed(tmp_path, "delta-seed", "Permission cards, cards and more cards.")
    got = sw.similar("permission cards design", repo=tmp_path)
    assert got[0] == ("alpha-seed", 3)
    assert [slug for slug, _ in got] == ["alpha-seed", "beta-seed", "delta-seed"]
    assert len(got) == 3


def test_similar_matches_the_slug_and_skips_closed_and_unrelated_seeds(tmp_path):
    open_seed(tmp_path, "weight-class-note", "Nothing shared here.")
    open_seed(tmp_path, "closed-one", "weight class lean default", status="promoted")
    open_seed(tmp_path, "unrelated", "Completely different subject matter.")
    assert sw.similar("weight class", repo=tmp_path) == [("weight-class-note", 2)]
    assert sw.similar("zzz qqq", repo=tmp_path) == []


def test_similar_with_no_designs_dir_is_empty(tmp_path):
    assert sw.similar("anything at all", repo=tmp_path) == []


def test_cli_new_prints_the_path_and_a_repeat_exits_1(tmp_path, capsys):
    args = ["new", "cli-seed", "--repo", str(tmp_path), "--source", "ask", "--problem", "P",
            "--risk", "low", "--blast-radius", "low", "--reversibility", "high",
            "--novelty", "low"]
    assert sw.main(args) == 0
    path = Path(capsys.readouterr().out.strip())
    assert parse_frontmatter(read(path))["weight-class"] == "light"
    assert sw.main(args) == 1
    err = capsys.readouterr().err
    assert err.startswith("seed_write:") and "cli-seed" in err


def test_cli_amend_and_similar(tmp_path, capsys):
    new(tmp_path, problem="Seeds lean heavy for consumers.")
    assert sw.main(["amend", "lean-seed", "More.", "--repo", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "amended lean-seed: Part 2"
    assert sw.main(["similar", "heavy consumers", "--repo", str(tmp_path)]) == 0
    assert capsys.readouterr().out.split() == ["lean-seed", "2"]
    assert sw.main(["amend", "gone", "x", "--repo", str(tmp_path)]) == 1
