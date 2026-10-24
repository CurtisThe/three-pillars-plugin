"""Tests for pending_changes.py (design living-doc-fragments, Task 1.2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pending_changes  # noqa: E402


def _frag(root, slug, date, body=""):
    d = root / "three-pillars-docs" / "changes"
    d.mkdir(parents=True, exist_ok=True)
    text = f"---\nslug: {slug}\nkind: design\ndate: {date}\n---\n{body}"
    (d / f"{slug}.md").write_text(text, encoding="utf-8")


ROADMAP = "## Roadmap\n### Design inventory\n+ row one\n- old row\n+ row two\n"


def test_lists_fragments_sorted_by_date_then_slug(tmp_path):
    _frag(tmp_path, "zeta", "2026-01-01")
    _frag(tmp_path, "beta", "2026-02-01")
    _frag(tmp_path, "alpha", "2026-02-01")
    got = pending_changes.list_fragments(tmp_path)
    assert [f.slug for f in got] == ["zeta", "alpha", "beta"]
    assert pending_changes.pending_slugs(tmp_path) == ["zeta", "alpha", "beta"]


def test_invalid_fragment_is_reported_not_raised(tmp_path):
    _frag(tmp_path, "good", "2026-01-01")
    (tmp_path / "three-pillars-docs" / "changes" / "bad.md").write_text("garbage\n", encoding="utf-8")
    out = pending_changes.summary(tmp_path)
    assert "good — merged, docs pending compile" in out
    bad = [ln for ln in out.splitlines() if ln.startswith("bad")]
    assert bad and "invalid" in bad[0]


def test_summary_names_slug_as_done(tmp_path):
    _frag(tmp_path, "feat", "2026-01-01", ROADMAP)
    lines = pending_changes.summary(tmp_path).splitlines()
    assert lines[0] == "feat — merged, docs pending compile"
    plus = [ln.strip() for ln in lines[1:]]
    assert "+ row one" in plus and "+ row two" in plus
    assert not any("old row" in ln for ln in lines)


def test_no_changes_dir_is_empty_and_exit_0(tmp_path, capsys):
    assert pending_changes.summary(tmp_path) == ""
    assert pending_changes.main(["summary", "--repo-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""
    assert pending_changes.main(["summary", "--repo-root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["fragments"] == []


def test_vision_only_fragment_is_flagged(tmp_path):
    _frag(tmp_path, "vis", "2026-01-01", "## Vision\nNew principle.\n")
    assert "vision change awaiting operator" in pending_changes.summary(tmp_path)


def test_slug_on_its_own_branch_is_in_flight(tmp_path):
    _frag(tmp_path, "mine", "2026-01-01")
    _frag(tmp_path, "other", "2026-01-02")
    for cmd in (["init", "-q"], ["checkout", "-q", "-b", "tp/mine"]):
        subprocess.run(["git", "-C", str(tmp_path), *cmd], check=True)
    out = pending_changes.summary(tmp_path)
    assert "mine — in flight" in out
    assert "mine — merged" not in out
    assert "other — merged, docs pending compile" in out


def _conflict_repo(tmp_path, both=True):
    from test_docs_compile import frag, make_repo
    swap = "\n## Roadmap\n\n### Current Focus\n- - focus one\n+ - {new}\n"
    frags = {"a1": frag("a1", "2020-01-02", swap.format(new="first"))}
    if both:
        frags["b2"] = frag("b2", "2020-01-03", swap.format(new="second"))
    return make_repo(tmp_path, frags)


def test_check_exits_1_with_one_conflict_line_per_unappliable_fragment(tmp_path, capsys):
    root = _conflict_repo(tmp_path)
    assert pending_changes.main(["check", "--repo-root", str(root)]) == 1
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 1 and lines[0].startswith("conflict: b2: ")
    assert set(pending_changes.unappliable(root)) == {"b2"}


def test_check_exits_0_when_every_fragment_folds(tmp_path, capsys):
    root = _conflict_repo(tmp_path, both=False)
    assert pending_changes.main(["check", "--repo-root", str(root)]) == 0
    assert capsys.readouterr().out == ""
    assert pending_changes.unappliable(root) == {}
