"""``audit_dispositions.mark`` — matching a round finding to a carry entry.

design: review-convergence 6.2, detailed-design-pr-loop.md §D4.

``mark(findings, carry_path, *, cwd, head, round_no, run_git=None)`` walks round 1's
normalized findings and dispositiones the ones the impl audit already dispositioned:
same file (no parent-dir fallback), overlapping line range when both sides cite one,
claim-token Jaccard >= 0.5, and the file unchanged between ``audit_head`` and ``head``.
The unchanged check is the only git touch here, so these cases inject ``run_git`` and
never read an ambient repo; the git-backed half of Behavior 11 is
test_audit_dispositions_changed.py. Inputs are never mutated.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_dispositions  # noqa: E402

AUDIT_HEAD = "11a54b232cdd15d48acdf1d2f7a93cc41884b358"
HEAD = "1da217733fd30cf088853b4f6f81ac169a3a03ee"

# The §D4 rows: one carry entry for skills/_shared/guard.py citing lines 10-20.
CARRY_ENTRY = {
    "file": "skills/_shared/guard.py",
    "area": "skills/_shared",
    "claim": "guard rejects a path outside the design worktree",
    "disposition": "fixed",
    "severity": "medium",
    "audit_head": AUDIT_HEAD,
    "line": [10, 20],
}

# Same tokens as CARRY_ENTRY["claim"] plus one, so Jaccard is 4/5 = 0.8 >= 0.5.
SAME_CLAIM = "guard rejects a path outside the design worktree dir"
# Half of the entry's tokens: Jaccard 2/5 = 0.4 < 0.5.
WEAK_CLAIM = "guard rejects nothing here at all"


def _finding(**over) -> dict:
    """A normalized-finding.v1 round finding (required fields, blocking)."""
    f = {
        "source": "code-review",
        "file": "skills/_shared/guard.py",
        "line_range": [12, 14],
        "summary": SAME_CLAIM,
        "verdict": "structural",
        "blocking": True,
    }
    f.update(over)
    return f


def _carry(tmp_path: Path, entries) -> Path:
    path = tmp_path / audit_dispositions.CARRY
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return path


def _mark(tmp_path: Path, findings, entries=(CARRY_ENTRY,), *, unchanged=True, **over):
    """Run ``mark`` over ``findings`` against a tmp carry of ``entries``.

    ``unchanged`` drives the injected git seam: returncode 0 means the file is
    identical between the audit head and ``head``.
    """
    seen: list[tuple] = []

    def run_git(_cwd, args):
        seen.append(tuple(args))
        return (0 if unchanged else 1, "")

    kwargs = {"cwd": tmp_path, "head": HEAD, "round_no": 1, "run_git": run_git}
    kwargs.update(over)
    out = audit_dispositions.mark(findings, _carry(tmp_path, entries), **kwargs)
    return out, seen


def test_matching_finding_is_dispositioned(tmp_path):
    out, seen = _mark(tmp_path, [_finding()])
    assert out[0]["dispositioned"] is True
    assert out[0]["blocking"] is False
    assert out[0]["verdict"] == "minor"
    assert AUDIT_HEAD[:12] in out[0]["disposition_note"]
    # The only git touch is the diff of that one file between the two heads.
    assert seen == [("diff", "--quiet", AUDIT_HEAD, HEAD, "--", "skills/_shared/guard.py")]


def test_mark_returns_copies_and_never_mutates(tmp_path):
    finding = _finding()
    before = dict(finding)
    out, _ = _mark(tmp_path, [finding])
    assert out is not None and out[0] is not finding
    assert finding == before
    assert out[0] != finding


def test_disposition_note_names_the_audit_disposition(tmp_path):
    out, _ = _mark(tmp_path, [_finding()])
    assert "fixed" in out[0]["disposition_note"]


def test_weak_claim_overlap_does_not_match(tmp_path):
    out, _ = _mark(tmp_path, [_finding(summary=WEAK_CLAIM)])
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True


def test_same_dir_other_file_does_not_match(tmp_path):
    """The parent-dir idea was dropped: file equality is required."""
    other = {**CARRY_ENTRY, "file": "skills/_shared/other.py"}
    out, _ = _mark(tmp_path, [_finding()], entries=(other,))
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True


def test_disjoint_line_ranges_do_not_match(tmp_path):
    """Both sides cite lines and the claims match, yet the spans miss: no match."""
    out, seen = _mark(tmp_path, [_finding(line_range=[80, 90])])
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True
    # The file is still unchanged, so the line check (not the git check) refused.
    assert seen == [("diff", "--quiet", AUDIT_HEAD, HEAD, "--", "skills/_shared/guard.py")]


def test_overlap_when_only_one_side_cites_lines(tmp_path):
    """Claim + file + unchanged is enough when either side cites no lines."""
    no_entry_lines = {k: v for k, v in CARRY_ENTRY.items() if k != "line"}
    out, _ = _mark(tmp_path, [_finding()], entries=(no_entry_lines,))
    assert out[0]["dispositioned"] is True

    entry_line_int = {**CARRY_ENTRY, "line": 12}
    out, _ = _mark(tmp_path, [_finding()], entries=(entry_line_int,))
    assert out[0]["dispositioned"] is True

    entry_single = {**CARRY_ENTRY, "line": [12, 12]}
    out, _ = _mark(tmp_path, [_finding(line_range=[12, 12])], entries=(entry_single,))
    assert out[0]["dispositioned"] is True


def test_round_two_findings_are_returned_untouched(tmp_path):
    out, seen = _mark(tmp_path, [_finding()], round_no=2)
    assert out == [_finding()]
    assert seen == []


def test_reproduced_finding_is_never_dispositioned(tmp_path):
    """A reproduced blocker outranks the carry, whatever the diff says."""
    out, seen = _mark(tmp_path, [_finding(reproduction="reproduced")])
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True
    assert seen == []


def test_missing_carry_file_returns_findings_untouched(tmp_path):
    missing = tmp_path / "no-such-carry.json"
    finding = _finding()
    out = audit_dispositions.mark([finding], missing, cwd=tmp_path, head=HEAD, round_no=1)
    assert out == [finding]


def test_unreadable_carry_file_returns_findings_untouched(tmp_path):
    carry = tmp_path / "carry-dir"
    carry.mkdir()  # a directory where the JSON should be -> unreadable
    finding = _finding()
    out = audit_dispositions.mark([finding], carry, cwd=tmp_path, head=HEAD, round_no=1)
    assert out == [finding]


def test_malformed_carry_file_returns_findings_untouched(tmp_path):
    carry = tmp_path / audit_dispositions.CARRY
    carry.write_text("not json", encoding="utf-8")
    finding = _finding()
    out = audit_dispositions.mark([finding], carry, cwd=tmp_path, head=HEAD, round_no=1)
    assert out == [finding]
