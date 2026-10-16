"""Tests for prose_oracle.py — the prose_shape check (plan Task 7.1).

design: cheap-tier-offload (slots doc §Phase 7).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prose_oracle as po  # noqa: E402

HANDOFF = """## Phase
Phase 7 of cheap-tier-offload, task 7.1.

## Decisions
- The oracle lives in `skills/_shared/prose_oracle.py`.

## State
Commit abc1234 landed; PR #42 is open.

## Next
Run the site tests.

## Open Questions
None.

## Carried Forward
Nothing.
"""
FACTS = {"commits": ["abc1234def"], "pr": 42}
LINE = "- 2026-09-30 — cheap-tier prose drafts land behind `skills/_shared/prose_oracle.py`."
DRAFT = ("**Before**\n- old line\n\n**After**\n- new line in `skills/_shared/prose_oracle.py`\n\n"
         "**Why**\nThe design shipped.\n")


@pytest.fixture
def root(tmp_path):
    (tmp_path / "skills" / "_shared").mkdir(parents=True)
    (tmp_path / "skills" / "_shared" / "prose_oracle.py").write_text("")
    return tmp_path


def _check(kind, text, root, **kw):
    kw.setdefault("facts", FACTS)
    return po.check(kind, text, root=root, **kw)


def test_good_drafts_pass(root):
    for kind, text in (("handoff", HANDOFF), ("history_line", LINE), ("docs_draft", DRAFT)):
        v = _check(kind, text, root)
        assert v == {"ok": True, "oracle": "prose_shape", "reason": ""}, (kind, v)


def test_kinds_are_the_three_prose_slots():
    assert set(po.KINDS) == {"handoff", "history_line", "docs_draft"}
    assert "decisions_entry" not in po.KINDS


def test_unknown_kind_raises(root):
    with pytest.raises(ValueError):
        po.check("decisions_entry", "x", root=root)


@pytest.mark.parametrize("heading", po.HANDOFF_HEADINGS)
def test_handoff_needs_every_template_heading(root, heading):
    v = _check("handoff", HANDOFF.replace(heading + "\n", "\n"), root)
    assert v["ok"] is False and heading in v["reason"]


def test_handoff_headings_are_the_session_save_template():
    skill_md = Path(__file__).resolve().parent.parent / "tp-session-save" / "SKILL.md"
    skill = skill_md.read_text(encoding="utf-8")
    for heading in po.HANDOFF_HEADINGS:
        assert f"\n{heading}\n" in skill


def test_required_adds_field_prefixes(root):
    v = _check("docs_draft", DRAFT, root, required=("**Doc**",))
    assert v["ok"] is False and "**Doc**" in v["reason"]
    assert _check("docs_draft", "**Doc**: x\n" + DRAFT, root, required=("**Doc**",))["ok"]


def test_docs_draft_needs_before_after_why(root):
    v = _check("docs_draft", DRAFT.replace("**Why**", "Because"), root)
    assert v["ok"] is False and "**Why**" in v["reason"]


def test_history_line_shape(root):
    assert not _check("history_line", "cheap-tier prose landed.", root)["ok"]
    assert not _check("history_line", "- 30 Sept — landed.", root)["ok"]
    assert not _check("history_line", LINE + "\n- 2026-09-29 — a second line.", root)["ok"]
    assert _check("history_line", "- **2026-09-30** — a bold-dated line.", root)["ok"]
    assert not _check("history_line", "- **2026-09-30 — an unclosed bold.", root)["ok"]


def test_phantom_backticked_path_fails(root):
    v = _check("history_line", LINE.replace("prose_oracle.py", "ghost.py"), root)
    assert v["ok"] is False and "skills/_shared/ghost.py" in v["reason"]


@pytest.mark.parametrize("token", ["tp/cheap-tier-offload", "origin/master", "--cheap-tier",
                                   "../seed.md", "<slug>/plan.md", "https://x.org/a.md",
                                   "skills/_shared/prose_oracle.py:12",
                                   "skills/_shared/prose_oracle.py::test_x"])
def test_non_paths_and_suffixes_are_not_phantoms(root, token):
    assert _check("history_line", f"- 2026-09-30 — see `{token}`.", root)["ok"]


def test_ref_not_in_facts_fails(root):
    v = _check("handoff", HANDOFF.replace("#42", "#43"), root)
    assert v["ok"] is False and "#43" in v["reason"]
    v = _check("handoff", HANDOFF.replace("abc1234", "fed9876"), root)
    assert v["ok"] is False and "fed9876" in v["reason"]


def test_refs_need_facts(root):
    assert not po.check("handoff", HANDOFF, root=root)["ok"]
    assert po.check("handoff", HANDOFF.replace("Commit abc1234 landed; PR #42 is open.", "Done."),
                    root=root)["ok"]


def test_headings_and_dates_are_not_refs(root):
    assert _check("history_line", "- 2026-09-30 — a decade of 2026093 facade work.", root)["ok"]
    assert "## Phase" in HANDOFF and _check("handoff", HANDOFF, root, facts={
        "c": "abc1234", "pr": "42"})["ok"]


DATED = {"date": "2026-09-30", "change": "cheap-tier drafts", "prs": [191]}


@pytest.mark.parametrize("ref", ["#30", "#2026", "#9"])
def test_pr_ref_only_inside_the_date_is_a_phantom(root, ref):
    v = _check("history_line", f"- 2026-09-30 — cheap-tier drafts landed in PR {ref}.", root,
               facts=DATED)
    assert v["ok"] is False and ref in v["reason"], v


@pytest.mark.parametrize("text", ["landed in #191/#999.", "landed in PR#999."])
def test_slash_pair_and_pr_prefix_refs_are_checked(root, text):
    v = _check("history_line", f"- 2026-09-30 — {text}", root, facts=DATED)
    assert v["ok"] is False and "#999" in v["reason"], v


@pytest.mark.parametrize("facts", [DATED, {"date": "2026-09-30", "pr": "191"},
                                   {"change": "landed in #190/#191"},
                                   {"url": "https://github.com/o/r/pull/191"}])
def test_real_pr_refs_in_facts_pass(root, facts):
    for text in ("landed in PR #191.", "landed in PR#191.", "landed in #191/#191."):
        v = _check("history_line", f"- 2026-09-30 — {text}", root, facts=facts)
        assert v["ok"] is True, (text, facts, v)


@pytest.mark.parametrize("marker", ["TBD", "TODO", "FIXME", "<fill in>", "{design-name}",
                                    "[...]", "Lorem ipsum"])
def test_placeholders_fail(root, marker):
    v = _check("handoff", HANDOFF.replace("Run the site tests.", f"Run {marker}."), root)
    assert v["ok"] is False and "placeholder" in v["reason"]


def test_template_placeholders_inside_code_spans_pass(root):
    assert _check("history_line", "- 2026-09-30 — `/tp-post-merge {name}` takes `<mode>`.",
                  root)["ok"]


@pytest.mark.parametrize("kind", po.KINDS)
def test_length_cap(root, kind):
    lines, chars = po.CAPS[kind]
    base = {"handoff": HANDOFF, "history_line": LINE, "docs_draft": DRAFT}[kind]
    v = _check(kind, base + "\nmore" * lines, root)
    assert v["ok"] is False and "cap" in v["reason"]
    v = _check(kind, base.rstrip("\n") + " " + "x" * chars, root)
    assert v["ok"] is False and "cap" in v["reason"]


def test_every_failure_is_reported(root):
    v = _check("handoff", "## Phase\nTBD in `skills/nope.py` for #9.\n", root)
    assert v["ok"] is False
    for part in ("## State", "skills/nope.py", "#9", "placeholder"):
        assert part in v["reason"]


# --- Task 7.2: the edit metric, operator-reviewed drafts only ----------------------


def test_edit_ratio():
    assert po.edit_ratio(HANDOFF, HANDOFF) == 0.0
    assert po.edit_ratio("", "") == 0.0
    assert po.edit_ratio("abc", "xyz") == 1.0
    for draft, final in ((LINE, LINE + " More."), (DRAFT, ""), ("", DRAFT), (HANDOFF, LINE)):
        assert 0.0 <= po.edit_ratio(draft, final) <= 1.0
    assert po.edit_ratio(LINE, LINE + " More.") < po.edit_ratio(LINE, DRAFT)


def _sidecar(path: Path) -> dict:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def test_save_draft_writes_draft_and_sidecar(tmp_path):
    side = po.save_draft(tmp_path, "history_line", LINE, LINE + " More.", reviewed=True)
    drafts = tmp_path / ".handoffs" / "drafts"
    assert side.parent == drafts and side.name.startswith("history_line-")
    data = _sidecar(side)
    sha = data["draft_sha256"]
    assert side.name == f"history_line-{sha[:8]}.json"
    assert (drafts / f"history_line-{sha[:8]}.md").read_text(encoding="utf-8") == LINE
    assert data["reviewed"] is True
    assert data["edit_ratio"] == po.edit_ratio(LINE, LINE + " More.")
    assert (drafts / ".gitignore").read_text(encoding="utf-8") == "*\n"


def test_unreviewed_draft_has_no_edit_ratio(tmp_path):
    data = _sidecar(po.save_draft(tmp_path, "docs_draft", DRAFT, DRAFT, reviewed=False))
    assert data["reviewed"] is False and data["edit_ratio"] is None
    data = _sidecar(po.save_draft(tmp_path, "handoff", HANDOFF, None, reviewed="yes"))
    assert data["reviewed"] is False and data["edit_ratio"] is None  # only True is reviewed


def test_save_draft_refuses_bad_slot_or_missing_final(tmp_path):
    with pytest.raises(ValueError):
        po.save_draft(tmp_path, "decisions_entry", "x", "x", reviewed=False)
    with pytest.raises(ValueError):
        po.save_draft(tmp_path, "handoff", HANDOFF, None, reviewed=True)


def test_edit_metric_reviewed_only(tmp_path):
    """An auto-landed draft (`/tp-design-learn --auto`: reviewed=False) never counts,
    even when it landed unchanged, so it is never 0-edit evidence."""
    assert po.edit_metric(tmp_path) == {"n": 0, "mean": None, "unreviewed": 0}
    design = tmp_path / "three-pillars-docs" / "tp-designs" / "d"
    po.save_draft(design, "history_line", LINE, LINE, reviewed=False)
    po.save_draft(design, "history_line", "- 2026-09-29 — b.", "- 2026-09-29 — c.",
                  reviewed=True)
    po.save_draft(tmp_path, "docs_draft", DRAFT, DRAFT + "x", reviewed=True)
    (tmp_path / ".handoffs" / "drafts" / "docs_draft-bad.json").write_text("{bad",
                                                                          encoding="utf-8")
    want_line = po.edit_ratio("- 2026-09-29 — b.", "- 2026-09-29 — c.")
    want_docs = po.edit_ratio(DRAFT, DRAFT + "x")
    got = po.edit_metric(tmp_path)
    assert got["n"] == 2 and got["unreviewed"] == 1
    assert got["mean"] == pytest.approx((want_line + want_docs) / 2)
    assert po.edit_metric(tmp_path, "history_line") == {"n": 1, "mean": want_line,
                                                        "unreviewed": 1}
    assert po.edit_metric(tmp_path, "handoff") == {"n": 0, "mean": None, "unreviewed": 0}


def test_save_draft_cli(tmp_path, capsys):
    """The stubs' save-draft call: exits 0 on every path (telemetry never gates a site)."""
    draft, final = tmp_path / "draft.md", tmp_path / "final.md"
    draft.write_text(LINE, encoding="utf-8")
    final.write_text(LINE + " More.", encoding="utf-8")
    base = ["save-draft", "--root", str(tmp_path), "--slot", "history_line",
            "--draft", str(draft)]
    assert po.main(base + ["--final", str(final), "--reviewed", "true"]) == 0
    side = Path(__import__("json").loads(capsys.readouterr().out)["sidecar"])
    assert _sidecar(side)["edit_ratio"] == po.edit_ratio(LINE, LINE + " More.")
    other = tmp_path / "other.md"  # a second draft: the same draft reuses its sha8 name
    other.write_text(LINE + " Other.", encoding="utf-8")
    assert po.main(base[:-1] + [str(other), "--reviewed", "false"]) == 0
    capsys.readouterr()
    assert po.edit_metric(tmp_path) == {"n": 1, "mean": _sidecar(side)["edit_ratio"],
                                        "unreviewed": 1}
    assert po.main(base + ["--reviewed", "true"]) == 0  # reviewed with no final
    assert "save-draft:" in capsys.readouterr().err
    assert po.main(["save-draft", "--root", str(tmp_path), "--slot", "history_line",
                    "--draft", str(tmp_path / "missing.md"), "--reviewed", "false"]) == 0
