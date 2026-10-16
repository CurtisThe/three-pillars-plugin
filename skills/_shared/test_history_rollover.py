"""Tests for history_rollover — the keep-newest-15 History rollover (Task 1.3).

Red cases (a)-(j) from plan Task 1.3, named by tag: the 16->15 roll with
archive-top insertion and the preamble/trailer staying live (a); a multi-line
entry moving intact (b); the known_issues preamble and the archive's own
preamble preserved (c); the no-doc / no-History / no-entries / <=keep no-ops,
moved=0 with a reason and CLI exit 0 (d); a missing archive seeded from
ARCHIVE_HEADER (e); a verifier failure leaving both files byte-identical and
the CLI exit 1 (f); `--keep` changing N (g); an archive with no History
heading gaining `## History` at EOF (h); the roadmap-shaped 16-bullet History
rolling exactly one, trailing bullet kept live (i); and the resolved-shaped
archive receiving the rolled entry after its preamble (covered by c). The
parse_history run-rule cases live in test_history_rollover_parse.py.

Run with: python -m pytest skills/_shared/test_history_rollover.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import history_rollover
from history_rollover import roll
from living_doc_archive import ARCHIVE_HEADER

MODULE = Path(__file__).resolve().parent / "history_rollover.py"

LIVE_REL = "three-pillars-docs/product_roadmap.md"
ARCHIVE_REL = "three-pillars-docs/product_roadmap_archive.md"
KI_LIVE = "three-pillars-docs/known_issues.md"
KI_ARCHIVE = "three-pillars-docs/known_issues_resolved.md"
TRAILER = "*Older history: see the archive for entries beyond the newest fifteen.*"


def make_repo(tmp_path, live_rel=LIVE_REL, live_text=""):
    root = tmp_path / "repo"
    (root / live_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / live_rel).write_text(live_text, encoding="utf-8")
    return root


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _cli(root, argv):
    return subprocess.run(
        [sys.executable, str(MODULE), *argv, "--repo-root", str(root)],
        cwd=str(root), capture_output=True, text=True,
    )


def _entries(n, prefix="e"):
    return [f"- {prefix}{i}: payload line {i}\n" for i in range(1, n + 1)]


def _live_doc(body):
    return "# Product Roadmap\n\n## Current State\n- the live state line\n\n" + body


def _lines(root, rel):
    return (root / rel).read_text(encoding="utf-8").splitlines()


def test_a_16_to_15_roll_moves_last_entry_to_top_of_archive(tmp_path):
    live = _live_doc("## History\n" + "".join(_entries(16)) + "\n" + TRAILER + "\n")
    root = make_repo(tmp_path, LIVE_REL, live)
    write(root, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n- archived prior\n")

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 1
    assert result.live_count == 15
    assert result.reason is None

    rolled = "- e16: payload line 16"
    boundary = "- e15: payload line 15"
    live_lines = _lines(root, LIVE_REL)
    live_entries = [ln for ln in live_lines if ln.startswith("- e")]
    assert len(live_entries) == 15, f"exactly 15 entries must stay live: {live_entries}"
    assert live_entries == [f"- e{i}: payload line {i}" for i in range(1, 16)]
    assert boundary in live_lines, "the newest non-rolled entry e15 must stay live"
    assert rolled not in live_lines
    assert TRAILER in live_lines

    archived = _lines(root, ARCHIVE_REL)
    archived_entries = [ln for ln in archived if ln.startswith("- ")]
    assert archived_entries == [rolled, "- archived prior"], (
        f"exactly one entry (e16) must move, to the top of the archive History: {archived_entries}"
    )
    assert boundary not in archived
    assert archived.index("## History") < archived.index(rolled)


def test_i_roadmap_16_run_bullets_plus_trailing_bullet_rolls_exactly_one(tmp_path):
    rolled_line = "- **2026-09-12** — run entry 16"
    kept_line = "- **2026-09-13** — run entry 15"
    live = _live_doc(
        "## Roadmap History\n"
        + "".join(f"- **2026-09-{28 - i:02d}** — run entry {i}\n" for i in range(1, 17))
        + "\n*Newest-first: newest at the top.*\n"
          "\n*Older history: see the archive for entries beyond the newest fifteen.*\n"
          "- 2026-07-01 — an older pointer kept live\n"
    )
    root = make_repo(tmp_path, LIVE_REL, live)
    write(root, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n- seeded entry\n")

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 1 and result.live_count == 15

    live_lines = _lines(root, LIVE_REL)
    assert rolled_line not in live_lines
    assert kept_line in live_lines
    assert "- 2026-07-01 — an older pointer kept live" in live_lines
    archived_lines = _lines(root, ARCHIVE_REL)
    assert rolled_line in archived_lines
    assert archived_lines.index("- seeded entry") > archived_lines.index(rolled_line)


def test_b_multi_line_entry_moves_intact(tmp_path):
    live = _live_doc(
        "## History\n" + "".join(_entries(15))
        + "- e16: queue update (PR #175):\n"
          "  - fragile-test-prevention is promoted;\n"
          "  - `gitea-forge-adapter` is inserted;\n"
          "  - the queue is renumbered 1-15.\n"
    )
    root = make_repo(tmp_path, LIVE_REL, live)
    write(root, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n- archived prior\n")

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 1 and result.live_count == 15

    block = [
        "- e16: queue update (PR #175):",
        "  - fragile-test-prevention is promoted;",
        "  - `gitea-forge-adapter` is inserted;",
        "  - the queue is renumbered 1-15.",
    ]
    for line in block:
        assert line in _lines(root, ARCHIVE_REL)
        assert line not in _lines(root, LIVE_REL)
    assert "- e15: payload line 15" in _lines(root, LIVE_REL)


def test_c_known_issues_preamble_stays_live_and_archive_preamble_is_preserved(tmp_path):
    live = (
        "# Known Issues\n\n"
        "> Tracking doc for live issues; resolved ones roll to `known_issues_resolved.md`.\n\n"
        "## Critical / High\n- live issue\n\n"
        "## History\n" + "".join(_entries(16, prefix="k"))
    )
    root = make_repo(tmp_path, KI_LIVE, live)
    prior = (
        "# Known Issues — RESOLVED archive\n\n"
        "> Resolved issues moved verbatim out of [`known_issues.md`](known_issues.md).\n\n"
        "## History\n\n"
        "- resolved #9\n"
    )
    write(root, KI_ARCHIVE, prior)

    result = roll(root, KI_LIVE, keep=15)
    assert result.moved == 1 and result.live_count == 15

    after = (root / KI_LIVE).read_text(encoding="utf-8")
    assert "> Tracking doc for live issues" in after
    assert "- k16: payload line 16\n" not in after
    archived = (root / KI_ARCHIVE).read_text(encoding="utf-8")
    assert "- k16: payload line 16\n" in archived
    assert "> Resolved issues moved verbatim" in archived
    assert archived.index("- k16: payload line 16") < archived.index("- resolved #9")
    assert archived.split("- k16: payload line 16")[0] == prior.split("## History")[0] + "## History\n\n"


@pytest.mark.parametrize(
    ("live_rel", "archive_rel", "live_text", "expected_reason"),
    [
        (LIVE_REL, ARCHIVE_REL, "no history heading at all\n", "History section"),
        (LIVE_REL, ARCHIVE_REL, "## History\njust prose, no entries\n", "no entries"),
        (LIVE_REL, ARCHIVE_REL, "## History\n" + "".join(_entries(15)), "only 15 entries"),
    ],
)
def test_d_noop_cases_return_moved_zero_with_reason(tmp_path, live_rel, archive_rel,
                                                    live_text, expected_reason):
    root = make_repo(tmp_path, live_rel, live_text)
    write(root, archive_rel, ARCHIVE_HEADER[archive_rel] + "## History\n\n- seeded\n")

    before_live = (root / live_rel).read_text(encoding="utf-8")
    before_archive = (root / archive_rel).read_text(encoding="utf-8")

    result = roll(root, live_rel, keep=15)
    assert result.moved == 0
    assert expected_reason in result.reason
    assert (root / live_rel).read_text(encoding="utf-8") == before_live
    assert (root / archive_rel).read_text(encoding="utf-8") == before_archive

    proc = _cli(root, ["--doc", live_rel])
    assert proc.returncode == 0
    assert expected_reason in proc.stdout
    payload = json.loads(_cli(root, ["--doc", live_rel, "--json"]).stdout)
    assert payload["moved"] == 0
    assert expected_reason in payload["reason"]


def test_d_absent_live_doc_returns_moved_zero_and_cli_exits_zero(tmp_path):
    root = tmp_path / "empty-repo"
    root.mkdir()

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 0
    assert "not found" in result.reason
    assert not (root / ARCHIVE_REL).exists()

    proc = _cli(root, ["--doc", LIVE_REL])
    assert proc.returncode == 0
    assert "not found" in proc.stdout


def test_unknown_live_doc_raises_keyerror(tmp_path):
    with pytest.raises(KeyError):
        roll(make_repo(tmp_path), "three-pillars-docs/notes.md", keep=15)


def test_e_missing_archive_is_seeded_with_header_and_history(tmp_path):
    root = make_repo(tmp_path, LIVE_REL, _live_doc("## History\n" + "".join(_entries(16))))

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 1 and result.live_count == 15

    after = (root / ARCHIVE_REL).read_text(encoding="utf-8")
    assert after.startswith(ARCHIVE_HEADER[ARCHIVE_REL])
    assert "## History" in after
    assert "- e16: payload line 16\n" in after
    assert after.index("## History") < after.index("- e16: payload line 16")


def test_f_verifier_failure_writes_nothing_and_cli_exits_1(tmp_path, monkeypatch):
    root = make_repo(tmp_path, LIVE_REL, _live_doc("## History\n" + "".join(_entries(16))))
    write(root, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n- archived prior\n")
    before_live = (root / LIVE_REL).read_text(encoding="utf-8")
    before_archive = (root / ARCHIVE_REL).read_text(encoding="utf-8")

    monkeypatch.setattr(history_rollover.verify_moves, "verify_move", lambda *a, **k: ["boom"])

    result = roll(root, LIVE_REL, keep=15)
    assert result.moved == 0
    assert "boom" in result.reason
    assert (root / LIVE_REL).read_text(encoding="utf-8") == before_live
    assert (root / ARCHIVE_REL).read_text(encoding="utf-8") == before_archive
    assert history_rollover.main(["--doc", LIVE_REL, "--repo-root", str(root)]) == 1
    assert history_rollover.main(["--doc", LIVE_REL, "--repo-root", str(root), "--json"]) == 1


def test_g_keep_two_moves_the_two_oldest_in_newest_first_order(tmp_path):
    live = _live_doc("## History\n" + "".join(_entries(4)))
    root = make_repo(tmp_path, LIVE_REL, live)
    write(root, ARCHIVE_REL, ARCHIVE_HEADER[ARCHIVE_REL] + "## History\n\n- archived prior\n")

    result = roll(root, LIVE_REL, keep=2)
    assert result.moved == 2 and result.live_count == 2

    live_lines = _lines(root, LIVE_REL)
    assert "- e1: payload line 1" in live_lines
    assert "- e2: payload line 2" in live_lines
    assert "- e3: payload line 3" not in live_lines
    assert "- e4: payload line 4" not in live_lines

    archived_lines = _lines(root, ARCHIVE_REL)
    assert archived_lines.index("- e3: payload line 3") < archived_lines.index("- e4: payload line 4")
    assert archived_lines.index("- e4: payload line 4") < archived_lines.index("- archived prior")


def test_h_archive_without_history_heading_gains_it_at_eof(tmp_path):
    live = _live_doc("## History\n" + "".join(_entries(16, prefix="k")))
    root = make_repo(tmp_path, KI_LIVE, live)
    prior = (
        "# Known Issues — RESOLVED archive\n\n"
        "> Resolved issues moved verbatim out of [`known_issues.md`](known_issues.md).\n\n"
        "- resolved #1\n- resolved #2\n"
    )
    write(root, KI_ARCHIVE, prior)

    result = roll(root, KI_LIVE, keep=15)
    assert result.moved == 1 and result.live_count == 15

    archived = (root / KI_ARCHIVE).read_text(encoding="utf-8")
    assert archived.startswith(prior)
    assert archived.endswith("- k16: payload line 16\n")
    assert "## History" in archived[len(prior):]
    assert archived.index("- k16: payload line 16") > archived.index("- resolved #2")

