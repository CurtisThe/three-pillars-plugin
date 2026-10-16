"""Tests for review_prep.move_work / render (design cheap-tier-review-prep, Task 3.3).

`move_work` moves the prep work dir W to `R/prep/work`; `render` turns the
accepted drafts under `R/prep/work/accepted/` into one labelled prep file per
non-skipped angle. Hunk text and CI quotes are real repo content, so every
fence must outrun the backtick runs inside it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import review_prep  # noqa: E402

LABEL = ("# Cheap-tier prep for {} (labelled; may be incomplete; the full diff "
         "is authoritative)")
HUNK_A = "@@ -1,2 +1,2 @@\n-old\n+new\n ctx\n"
HUNK_B = "@@ -9,1 +9,1 @@\n-x\n+y\n"
ANGLES = [{"name": "correctness"}, {"name": "security-review"},
          {"name": "perf", "skipped": True}]


def _accept(rd: Path, slot: str, unit: str, artifact) -> Path:
    adir = rd / "prep" / "work" / "accepted"
    adir.mkdir(parents=True, exist_ok=True)
    path = adir / f"{slot}--{unit}.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def _slice(rd, angle, *hunks, file="a.py"):
    _accept(rd, "review_slice", angle,
            {"hunks": [{"file": file, "hunk": h} for h in hunks]})


def _refs(rd, *refs):
    _accept(rd, "review_refs", "_",
            {"refs": [{"path": p, "line": n, "note": t} for p, n, t in refs]})


def _ci(rd, check, quote, step="Run tests"):
    _accept(rd, "ci_log_triage", check, {"quote": quote, "step": step})


def _fences(text: str):
    """(info, body) for each fenced block, closing only on an identical fence."""
    out, lines, i = [], text.splitlines(), 0
    while i < len(lines):
        m = re.match(r"^(`{3,})(\S*)$", lines[i])
        if not m:
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j] != m.group(1):
            j += 1
        assert j < len(lines), "unterminated fence"
        out.append((m.group(2), "\n".join(lines[i + 1:j]) + "\n"))
        i = j + 1
    return out


def _text(rd, angle="correctness", angles=ANGLES) -> str:
    return review_prep.render(rd, angles)[angle].read_text(encoding="utf-8")


# --- move_work ---------------------------------------------------------------------

def test_move_work_moves_with_replace(tmp_path):
    w = tmp_path / "prep-work" / "next"
    (w / "accepted").mkdir(parents=True)
    (w / "meta.json").write_text("{}", encoding="utf-8")
    (w / "accepted" / "x.json").write_text("{}", encoding="utf-8")
    rd = tmp_path / "rounds" / "r1"
    rd.mkdir(parents=True)
    dest = review_prep.move_work(w, rd)
    assert dest == rd / "prep" / "work"
    assert not w.exists()
    assert (dest / "meta.json").read_text(encoding="utf-8") == "{}"
    assert (dest / "accepted" / "x.json").is_file()


def test_move_work_missing_source_raises_oserror(tmp_path):
    rd = tmp_path / "r1"
    rd.mkdir()
    with pytest.raises(OSError):
        review_prep.move_work(tmp_path / "nope", rd)


# --- render: content ---------------------------------------------------------------

def test_render_slice_refs_ci(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", HUNK_A, HUNK_B)
    _refs(rd, ("pkg/a.py", 12, "caller of the changed fn"), ("b.py", 3, "docs"))
    _ci(rd, "build-and-test", "FAILED test_x - assert 1 == 2", step="Run pytest")
    out = review_prep.render(rd, ANGLES)
    assert set(out) == {"correctness", "security-review"}
    assert out["correctness"] == rd / "prep" / "correctness.md"
    text = out["correctness"].read_text(encoding="utf-8")
    assert text.splitlines()[0] == LABEL.format("correctness")
    fences = _fences(text)
    assert [i for i, _ in fences] == ["diff", "diff", ""]
    assert fences[0][1] == HUNK_A and fences[1][1] == HUNK_B
    assert fences[2][1] == "FAILED test_x - assert 1 == 2\n"
    assert "pkg/a.py:12 — caller of the changed fn" in text
    assert "b.py:3 — docs" in text
    assert "build-and-test" in text and "Run pytest" in text
    assert text.index("@@ -1,2") < text.index("pkg/a.py:12") < text.index("build-and-test")


def test_refs_and_ci_go_to_every_nonskipped_angle_slice_only_to_its_own(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", HUNK_A)
    _refs(rd, ("a.py", 1, "n"))
    _ci(rd, "lint", "E501 line too long")
    other = _text(rd, "security-review")
    assert other.splitlines()[0] == LABEL.format("security-review")
    assert "a.py:1 — n" in other and "E501 line too long" in other
    assert "@@ -1,2" not in other
    assert "diff" not in [info for info, _ in _fences(other)]
    assert "@@ -1,2" in _text(rd, "correctness")


def test_refs_only_file_has_no_hunk_or_ci_section(tmp_path):
    rd = tmp_path / "r1"
    _refs(rd, ("a.py", 1, "n"))
    text = _text(rd)
    assert _fences(text) == []
    assert "a.py:1 — n" in text and "CI" not in text and "@@" not in text


# --- render: which angles get a file -----------------------------------------------

def test_skipped_angle_gets_no_file_even_with_its_own_slice(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "perf", HUNK_A)
    _refs(rd, ("a.py", 1, "n"))
    out = review_prep.render(rd, ANGLES)
    assert "perf" not in out and not (rd / "prep" / "perf.md").exists()
    assert set(out) == {"correctness", "security-review"}


def test_angle_with_nothing_accepted_gets_no_file(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", HUNK_A)
    out = review_prep.render(rd, ANGLES)
    assert set(out) == {"correctness"}
    assert not (rd / "prep" / "security-review.md").exists()


def test_empty_hunks_and_refs_count_as_nothing(tmp_path):
    rd = tmp_path / "r1"
    _accept(rd, "review_slice", "correctness", {"hunks": []})
    _accept(rd, "review_refs", "_", {"refs": []})
    assert review_prep.render(rd, ANGLES) == {}
    assert not list((rd / "prep").glob("*.md"))


def test_missing_accepted_dir_writes_nothing(tmp_path):
    rd = tmp_path / "r1"
    (rd / "prep" / "work").mkdir(parents=True)
    assert review_prep.render(rd, ANGLES) == {}
    assert list((rd / "prep").glob("*.md")) == []
    bare = tmp_path / "r2"
    bare.mkdir()
    assert review_prep.render(bare, ANGLES) == {}
    assert not (bare / "prep").exists()


def test_other_slots_and_stray_files_are_ignored(tmp_path):
    rd = tmp_path / "r1"
    _accept(rd, "repro_scaffold", "abc123", {"source": "def test_x(): ...",
                                            "test_name": "test_x"})
    adir = rd / "prep" / "work" / "accepted"
    (adir / "review_slice--correctness.json.tmp").write_text("{", encoding="utf-8")
    (adir / "notes.txt").write_text("hi", encoding="utf-8")
    (adir / "nodelimiter.json").write_text("{", encoding="utf-8")
    assert review_prep.render(rd, ANGLES) == {}


# --- render: fences ----------------------------------------------------------------

def test_fence_outruns_backticks_in_hunk_and_quote(tmp_path):
    rd = tmp_path / "r1"
    hunk = "@@ -1,3 +1,3 @@\n ```python\n-x\n+y\n ```\n ````\n"
    quote = "log start\n```\nnested\n```\n"
    _slice(rd, "correctness", hunk)
    _ci(rd, "docs", quote)
    text = _text(rd)
    assert _fences(text) == [("diff", hunk), ("", quote)]
    lines = text.splitlines()
    assert "`````diff" in lines  # five ticks: one more than the 4-run in the hunk
    assert "```" in lines  # the quote's own 3-run needs only the 4-tick fence
    assert "````" in lines


def test_hunk_without_trailing_newline_still_closes_its_fence(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", "@@ -1 +1 @@\n-a\n+b")
    assert _fences(_text(rd)) == [("diff", "@@ -1 +1 @@\n-a\n+b\n")]


# --- render: names, order, errors --------------------------------------------------

def test_unit_names_with_dashes_split_on_first_double_dash_only(tmp_path):
    rd = tmp_path / "r1"
    angles = [{"name": "correctness-leak"}]
    _slice(rd, "correctness-leak", HUNK_A)
    _ci(rd, "lint--py-3", "boom")
    out = review_prep.render(rd, angles)
    assert set(out) == {"correctness-leak"}
    text = out["correctness-leak"].read_text(encoding="utf-8")
    assert "@@ -1,2" in text and "### lint--py-3 " in text and "boom" in text


def test_output_is_deterministic_and_ordered(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", HUNK_B, HUNK_A)
    _refs(rd, ("z.py", 9, "first"), ("a.py", 1, "second"))
    _ci(rd, "zeta", "ZQ")
    _ci(rd, "alpha", "AQ")
    _ci(rd, "alpha-2", "A2Q")
    first = review_prep.render(rd, ANGLES)["correctness"].read_bytes()
    assert review_prep.render(rd, ANGLES)["correctness"].read_bytes() == first
    text = first.decode("utf-8")
    assert text.index("-x") < text.index("-old")  # hunks in artifact order
    assert text.index("z.py:9") < text.index("a.py:1")  # refs in artifact order
    pos = [text.index(f"### {c} ") for c in ("alpha", "alpha-2", "zeta")]
    assert pos == sorted(pos)  # checks in sorted unit order


def test_malformed_accepted_file_raises_valueerror(tmp_path):
    rd = tmp_path / "r1"
    _slice(rd, "correctness", HUNK_A)
    (rd / "prep" / "work" / "accepted" / "review_refs--_.json").write_text(
        "{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        review_prep.render(rd, ANGLES)


@pytest.mark.parametrize("slot,unit,artifact", [
    ("review_slice", "correctness", {"hunks": "nope"}),
    ("review_slice", "correctness", {"hunks": [{"file": "a.py"}]}),
    ("review_refs", "_", {"refs": [{"path": "a", "line": "3", "note": "n"}]}),
    ("review_refs", "_", ["not", "an", "object"]),
    ("ci_log_triage", "lint", {"quote": 5, "step": "s"}),
])
def test_wrong_shape_raises_valueerror(tmp_path, slot, unit, artifact):
    rd = tmp_path / "r1"
    _accept(rd, slot, unit, artifact)
    with pytest.raises(ValueError):
        review_prep.render(rd, ANGLES)


def test_unreadable_accepted_file_raises_oserror(tmp_path):
    rd = tmp_path / "r1"
    adir = rd / "prep" / "work" / "accepted"
    (adir / "review_refs--_.json").mkdir(parents=True)  # a dir, not a file
    with pytest.raises(OSError):
        review_prep.render(rd, ANGLES)


def test_move_work_then_render_end_to_end(tmp_path):
    w = tmp_path / "prep-work" / "next"
    adir = w / "accepted"
    adir.mkdir(parents=True)
    (adir / "review_slice--correctness.json").write_text(
        json.dumps({"hunks": [{"file": "a.py", "hunk": HUNK_A}]}), encoding="utf-8")
    rd = tmp_path / "rounds" / "r1"
    rd.mkdir(parents=True)
    review_prep.move_work(w, rd)
    out = review_prep.render(rd, ANGLES)
    assert out == {"correctness": rd / "prep" / "correctness.md"}
    assert out["correctness"].is_file()
