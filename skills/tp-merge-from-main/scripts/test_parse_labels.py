"""Round 17, F1/F2/F7 — the byte path binds conflict markers to merge-file's own LABELS.

F1  A living doc that QUOTES a conflict region (a fenced example: `<<<<<<< HEAD` / a log bullet /
    `=======` / a log bullet / `>>>>>>> master`) in text none of the three sides changed was parsed
    as a real region: it classified `log-entry-insertion`, its marker lines were deleted, and the
    file was staged as auto-resolved.
F2  A CONTENT line beginning `>>>>>>>` inside theirs' side became the region's close marker, was
    never emitted, and the real close fell into clean text.
F7  `merge_driver`'s "no marker text remains" staging condition had no test.

The fix: `auto_safe_resolution` runs `git merge-file` with three nonce-bearing `-L` labels and the
parse accepts only marker lines EQUAL to `<<<<<<< {ours}` / `||||||| {base}` / `>>>>>>> {theirs}`;
the region count it finds must equal merge-file's exit status.
"""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_shared"))
import auto_safe_resolution as asr  # noqa: E402
import merge_driver  # noqa: E402
from auto_safe_resolution import (  # noqa: E402
    ConflictCountMismatch, Diff3, resolve_conflict_bytes, resolve_conflict_bytes_detail,
)
from classify import Hunk, classify_file  # noqa: E402
from resolve import DEFER, RESOLVED, resolve_file  # noqa: E402
from test_merge_driver import commit, git, make_repo, write  # noqa: E402

ARCH = "three-pillars-docs/architecture.md"
QUOTED = ("```\n<<<<<<< HEAD\n- **2026-01-01** — example entry from the design branch\n=======\n"
          "- **2026-01-02** — example entry from master\n>>>>>>> master\n```\n")
F1_BASE = "# Architecture\n\nA conflict looks like:\n\n" + QUOTED + "\n## History\n\n- **2026-01-01** — initial\n"
F1_OURS = F1_BASE.replace("## History\n\n", "## History\n\n- **2026-02-01** — design entry\n")
F1_THEIRS = F1_BASE.replace("## History\n\n", "## History\n\n- **2026-02-02** — master entry\n")

F2_PRE = "# Architecture\n\n## History\n\n"
F2_BASE = F2_PRE + "- **2026-01-01** — old entry\n"
F2_OURS = F2_PRE + "- **2026-09-01** — ours entry\n- **2026-01-01** — old entry\n"
F2_CONTENT = ">>>>>>> theirs-branch"
F2_THEIRS = (F2_PRE + "- **2026-09-02** — driver leaves a stray marker such as\n" + F2_CONTENT
             + "\n  when it defers\n- **2026-01-01** — old entry\n")


def _repo(tmp_path, path, base, ours, theirs):
    repo = make_repo(tmp_path)
    write(repo, path, base)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "design")
    write(repo, path, ours)
    commit(repo, "ours")
    git(repo, "checkout", "-q", "master")
    write(repo, path, theirs)
    commit(repo, "theirs")
    git(repo, "checkout", "-q", "design")
    return repo


def _unmerged(repo, path):
    return git(repo, "ls-files", "-u", "--", path).stdout.strip() != ""


# ---- F1 ----------------------------------------------------------------------------------------

def test_f1_a_quoted_region_is_content_under_the_labelled_parse():
    d = asr._diff3_conflict(base=F1_BASE, ours=F1_OURS, theirs=F1_THEIRS)
    hunks = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    assert len(hunks) == d.conflicts == 1, (d.conflicts, [h.ours for h in hunks])
    assert hunks[0].ours == ["- **2026-02-01** — design entry"]
    status, merged = resolve_conflict_bytes(base=F1_BASE, ours=F1_OURS, theirs=F1_THEIRS)
    assert status == RESOLVED
    assert QUOTED in merged, "the quoted example must survive verbatim"
    assert "- **2026-02-01** — design entry\n- **2026-02-02** — master entry\n" in merged


def test_f1_the_unlabelled_parse_still_misreads_it_which_is_why_the_byte_path_labels():
    """The residual, pinned: a caller with no labels (the CLI, a synthetic blob) still reads the
    quoted example as a region. If this starts failing the prefix scan was fixed too — delete it."""
    d = asr._diff3_conflict(base=F1_BASE, ours=F1_OURS, theirs=F1_THEIRS)
    assert sum(isinstance(s, Hunk) for s in classify_file(d.text).segments) == 2


def test_f1_and_f7_the_driver_writes_but_never_stages_marker_text(tmp_path):
    """End to end. The resolution is RESOLVED and lossless, but the result still contains marker
    text (the document's own quoted example), so the F7 guard must refuse to stage it. Under the
    mutation `if status == RESOLVED:` this file is `git add`ed and the test fails."""
    repo = _repo(tmp_path, ARCH, F1_BASE, F1_OURS, F1_THEIRS)
    report = merge_driver.merge_back(str(repo), "master")
    assert ARCH in report.partially_resolved and ARCH not in report.auto_resolved, report.to_json()
    outcome = next(o for o in report.outcomes if o["path"] == ARCH)
    assert "every conflict region was resolved" in outcome["reason"], outcome
    written = (repo / ARCH).read_text(encoding="utf-8")
    assert QUOTED in written and "- **2026-02-02** — master entry" in written
    assert _unmerged(repo, ARCH), "marker text remains, so the file must NOT be staged"
    assert report.needs_human


# ---- F2 ----------------------------------------------------------------------------------------

def test_f2_a_content_line_starting_like_a_close_marker_stays_on_its_side():
    d = asr._diff3_conflict(base=F2_BASE, ours=F2_OURS, theirs=F2_THEIRS)
    hunks = [s for s in classify_file(d.text, labels=d.labels).segments if isinstance(s, Hunk)]
    assert len(hunks) == d.conflicts == 1
    assert F2_CONTENT in hunks[0].theirs and hunks[0].close_marker.endswith(d.labels[2])
    status, merged = resolve_conflict_bytes(base=F2_BASE, ours=F2_OURS, theirs=F2_THEIRS)
    assert status == DEFER and ("\n" + F2_CONTENT + "\n") in merged


@pytest.mark.parametrize("swap", [False, True], ids=["in-theirs", "in-ours"])
def test_f2_end_to_end_the_content_line_survives_and_nothing_is_staged(tmp_path, swap):
    ours, theirs = (F2_THEIRS, F2_OURS) if swap else (F2_OURS, F2_THEIRS)
    repo = _repo(tmp_path, ARCH, F2_BASE, ours, theirs)
    report = merge_driver.merge_back(str(repo), "master")
    assert ARCH not in report.auto_resolved, report.to_json()
    assert ("\n" + F2_CONTENT + "\n") in (repo / ARCH).read_text(encoding="utf-8")
    assert _unmerged(repo, ARCH)


def test_a_content_separator_line_in_theirs_defers_losslessly():
    """`=======` carries no label, so it is the one marker a content line can still equal. The
    labelled scan takes the first after the base marker; any other lands in a side and defers."""
    base = "## History\n\n- **2026-01-01** — old\n"
    ours = "## History\n\n- **2026-09-01** — ours\n- **2026-01-01** — old\n"
    theirs = "## History\n\n- **2026-09-02** — theirs\n=======\n- **2026-01-01** — old\n"
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == DEFER
    assert merged.count("\n=======\n") == 2 and "- **2026-09-02** — theirs" in merged


def test_a_content_separator_line_in_ours_is_written_for_the_human_verbatim(tmp_path, monkeypatch):
    """Round 25: the separator is searched for only AFTER the base marker. Ours' inserted block
    ending in a column-0 `=======` still defers when the search starts at the open marker, but the
    region is then cut there, and the text written for the human repeats the base marker and the
    separator. The worktree must hold merge-file's own conflict text, byte for byte."""
    monkeypatch.setattr(asr.secrets, "token_hex", lambda n: "f00dfacecafebeef" * 2)  # fixed labels
    base = "# A\n\n## History\n\n- **2026-01-01** — alpha\n"
    ours, theirs = base + "- **2026-01-03** — ours\n=======\n", base + "- **2026-01-02** — theirs\n"
    expected = asr.diff3_conflict(base=base, ours=ours, theirs=theirs).text
    assert expected.count("\n=======\n") == 2, expected
    repo = _repo(tmp_path, ARCH, base, ours, theirs)
    report = merge_driver.merge_back(str(repo), "master")
    assert report.partially_resolved == [ARCH], report.to_json()
    assert (repo / ARCH).read_text(encoding="utf-8") == expected
    assert _unmerged(repo, ARCH)


def test_labelled_markers_carry_the_crlf_terminator_and_still_parse():
    base = "## History\r\n\r\n- **2026-01-01** — old\r\n"
    ours = "## History\r\n\r\n- **2026-09-01** — ours\r\n- **2026-01-01** — old\r\n"
    theirs = "## History\r\n\r\n- **2026-09-02** — theirs\r\n- **2026-01-01** — old\r\n"
    status, merged = resolve_conflict_bytes(base=base, ours=ours, theirs=theirs)
    assert status == RESOLVED, merged
    assert "- **2026-09-01** — ours\r\n- **2026-09-02** — theirs\r\n" in merged


# ---- the count check and the nonce -------------------------------------------------------------

def test_a_parse_that_disagrees_with_merge_files_count_is_refused(monkeypatch):
    """merge-file says two regions; the parse can read one. Under the mutation that deletes
    `check_conflict_count(...)` this resolves RESOLVED and the test fails."""
    text = ("x\n<<<<<<< ours\n- **2026-09-01** — a\n||||||| base\n=======\n- **2026-09-02** — b\n"
            ">>>>>>> theirs\ny\n")
    monkeypatch.setattr(asr, "_diff3_conflict", lambda **kw: Diff3(text, ("ours", "base", "theirs"), 2))
    with pytest.raises(ConflictCountMismatch, match="reported 2 conflict"):
        resolve_conflict_bytes_detail(base="b\n", ours="o\n", theirs="t\n")
    monkeypatch.setattr(asr, "_diff3_conflict", lambda **kw: Diff3(text, ("ours", "base", "theirs"), None))
    with pytest.raises(ConflictCountMismatch, match="127"):
        resolve_conflict_bytes_detail(base="b\n", ours="o\n", theirs="t\n")


def test_the_driver_defers_a_count_mismatch_untouched(tmp_path, monkeypatch):
    repo = _repo(tmp_path, ARCH, F2_BASE, F2_OURS, F2_OURS.replace("ours entry", "theirs entry"))
    real = asr._diff3_conflict

    def _short(**kw):
        d = real(**kw)
        return Diff3(d.text, d.labels, d.conflicts + 1)
    monkeypatch.setattr(asr, "_diff3_conflict", _short)
    report = merge_driver.merge_back(str(repo), "master")
    outcome = next(o for o in report.outcomes if o["path"] == ARCH)
    assert ARCH in report.deferred and "conflict reconstruction failed" in outcome["reason"], outcome
    assert _unmerged(repo, ARCH)


def test_the_nonce_is_redrawn_when_an_input_contains_it(monkeypatch):
    draws = iter(["deadbeef", "c0ffee00"])
    monkeypatch.setattr(asr.secrets, "token_hex", lambda n: next(draws))
    assert asr._fresh_labels("a doc mentioning deadbeef", "x", "y") == (
        "ours-c0ffee00", "base-c0ffee00", "theirs-c0ffee00")


def test_the_byte_path_draws_its_nonce_against_every_one_of_the_three_inputs(monkeypatch):
    """Pins the CALL SITE (round 18): `_diff3_conflict` must hand all three inputs to
    `_fresh_labels`. Calling it with none, or with two, passed the direct test above."""
    for side in ("base", "ours", "theirs"):
        draws = iter(["deadbeef", "c0ffee00"])
        monkeypatch.setattr(asr.secrets, "token_hex", lambda n: next(draws))
        texts = {"base": "x\n", "ours": "x\ny\n", "theirs": "x\nz\n"}
        texts[side] += "this line mentions deadbeef\n"
        assert asr.diff3_conflict(**texts).labels == (
            "ours-c0ffee00", "base-c0ffee00", "theirs-c0ffee00"), side


def test_the_nonce_never_reaches_resolved_output_and_resolved_bytes_are_stable():
    runs = {resolve_conflict_bytes(base=F1_BASE, ours=F1_OURS, theirs=F1_THEIRS) for _ in range(3)}
    assert len(runs) == 1, "RESOLVED bytes must not depend on the per-call nonce"
    (status, merged), = runs
    assert status == RESOLVED and "ours-" not in merged and "theirs-" not in merged


def test_fuzz_the_labelled_parse_finds_exactly_the_regions_merge_file_wrote():
    """Seeded fuzz over docs whose lines imitate every marker. For each, the labelled parse finds
    `merge-file`'s own region count (the count check never fires on real output), and a RESOLVED
    result emits no line the three inputs did not contain."""
    rng = random.Random(17)
    pool = ["<<<<<<< HEAD", "||||||| base", "=======", ">>>>>>> master", "- **2026-01-0%d** — e",
            "### L4: x", "| D1 | a |", "", "prose"]
    conflicted = misread_unlabelled = 0
    for _ in range(300):
        base = [rng.choice(pool).replace("%d", str(rng.randint(1, 9))) for _ in range(8)]
        ours, theirs = list(base), list(base)
        for side in (ours, theirs):          # edits clustered mid-file, so the sides collide
            for _ in range(rng.randint(1, 3)):
                side.insert(rng.randint(3, 5), rng.choice(pool).replace("%d", str(rng.randint(1, 9))))
            if rng.random() < 0.3:
                del side[rng.randrange(len(side))]
        b, o, t = ("\n".join(x) + "\n" for x in (base, ours, theirs))
        d = asr._diff3_conflict(base=b, ours=o, theirs=t)
        _status, lines, results = resolve_file(d.text, labels=d.labels)
        assert d.conflicts is not None and len(results) == d.conflicts, (b, o, t, d.text)
        if all(r.status == RESOLVED for r in results):
            assert not set(lines) - set(base) - set(ours) - set(theirs) - {""}
        conflicted += d.conflicts > 0
        misread_unlabelled += sum(isinstance(s, Hunk) for s in classify_file(d.text).segments) != d.conflicts
    # Non-vacuity, measured on this seed: 161 of 300 docs conflict, and the PREFIX scan miscounts
    # the regions of 45 of them — the population the labelled scan is being tested on.
    assert conflicted >= 150 and misread_unlabelled >= 40, (conflicted, misread_unlabelled)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
