"""Tests for review-convergence 11.4 — land.py prints the operator-accept line.

On a PASS gate whose roster carries an operator-accept in the `review_proof_on_head`
slot (the accept stood in for a missing review-proof digest — human approval is still
required), `land()` prints `merge rides an operator-accept: <detail>` BEFORE the
`Merged` line. Every other PASS roster prints nothing extra and merges anyway
(fail-open: a normal proof detail, an outcome with no `roster` attribute at all, a
roster that raises). A blocked gate prints nothing extra and never merges.

Hermetic: `require_fn` / `merge_fn` are injected and `config=` is explicit, so no
live `gh`, no repo-config read.

Run with: pytest skills/tp-merge/scripts/test_land_accept_line.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# merge_gate (with MergeGateBlocked) lives in the base-sync half's scripts dir.
sys.path.insert(0, str(HERE.parent.parent / "tp-merge-from-main" / "scripts"))
sys.path.insert(0, str(HERE.parent.parent / "_shared"))

import land  # noqa: E402
import gate_roster  # noqa: E402
from merge_gate import MergeGateBlocked  # noqa: E402

PR_URL = "https://github.com/example/repo/pull/7"
SKILL_MD = HERE.parent / "SKILL.md"
CONFIG = {"review": {"require_human_approval": True}}

# The detail operator_accept._accept_detail produces (11.1/11.2).
ACCEPT_DETAIL = "operator-accept by curtis on 1a2b3c4: gate lows closed, shipping"
ACCEPT_LINE = f"merge rides an operator-accept: {ACCEPT_DETAIL}"
PROOF_DETAIL = "proof digest 3f9a1c on head 1a2b3c4 by CurtisTheBot"


class _FakeOutcome:
    """Stand-in for a GateOutcome: the roster land reads + what MergeGateBlocked reads."""

    def __init__(self, roster, verdict="PASS"):
        self.roster = roster
        self.blocking = []

        class _V:
            value = verdict

        self.verdict = _V()


class _BrokenRosterOutcome:
    """A roster attribute that raises — printing must stay fail-open."""

    @property
    def roster(self):
        raise RuntimeError("roster exploded")


def _pass_gate(outcome):
    def require_fn(pr_url, *, config=None):
        return outcome

    return require_fn


def _roster(name, status, detail):
    return (gate_roster.RosterEntry(name=name, status=status, detail=detail),)


class TestAcceptLineOnPass:
    def test_accept_detail_prints_line_before_merged(self, capsys):
        """A PASS roster whose proof-slot detail is an accept -> the line, then Merged."""
        outcome = _FakeOutcome(_roster("review_proof_on_head", "PASS", ACCEPT_DETAIL))
        merge_calls = []

        rc = land.land(PR_URL, require_fn=_pass_gate(outcome),
                       merge_fn=lambda u: merge_calls.append(u), config=CONFIG)

        assert rc == 0
        assert merge_calls == [PR_URL]
        out = capsys.readouterr().out
        assert ACCEPT_LINE in out, (
            f"land must print {ACCEPT_LINE!r} when the review_proof_on_head detail "
            "starts with 'operator-accept'"
        )
        assert out.index(ACCEPT_LINE) < out.index("Merged"), (
            "the accept line must precede the Merged line"
        )

    def test_normal_proof_detail_prints_no_accept_line(self, capsys):
        """A PASS roster with a genuine proof digest -> no accept line, still merges."""
        outcome = _FakeOutcome(_roster("review_proof_on_head", "PASS", PROOF_DETAIL))
        merge_calls = []

        rc = land.land(PR_URL, require_fn=_pass_gate(outcome),
                       merge_fn=lambda u: merge_calls.append(u), config=CONFIG)

        assert rc == 0
        assert merge_calls == [PR_URL]
        out = capsys.readouterr().out
        assert "merge rides" not in out
        assert "Merged" in out

    def test_other_slot_accept_detail_is_not_reported(self, capsys):
        """Only the review_proof_on_head slot carries the accept — another name is noise."""
        outcome = _FakeOutcome(_roster("human_approved", "PASS", ACCEPT_DETAIL))

        rc = land.land(PR_URL, require_fn=_pass_gate(outcome),
                       merge_fn=lambda u: None, config=CONFIG)

        assert rc == 0
        assert "merge rides" not in capsys.readouterr().out


class TestAcceptLineFailOpen:
    def test_outcome_without_roster_attribute_still_merges(self, capsys):
        """Existing test doubles return bare objects — no accept line, no crash."""
        merge_calls = []

        rc = land.land(PR_URL, require_fn=_pass_gate(object()),
                       merge_fn=lambda u: merge_calls.append(u), config=CONFIG)

        assert rc == 0
        assert merge_calls == [PR_URL]
        out = capsys.readouterr().out
        assert "merge rides" not in out
        assert "Merged" in out

    def test_raising_roster_prints_nothing_extra(self, capsys):
        """An unreadable roster is unprovable — print nothing extra, keep the merge."""
        rc = land.land(PR_URL, require_fn=_pass_gate(_BrokenRosterOutcome()),
                       merge_fn=lambda u: None, config=CONFIG)

        assert rc == 0
        assert "merge rides" not in capsys.readouterr().out

    def test_blocked_gate_prints_no_accept_line(self, capsys):
        """A blocked gate never prints the accept line and never merges."""
        outcome = _FakeOutcome(_roster("review_proof_on_head", "PASS", ACCEPT_DETAIL),
                               verdict="INDETERMINATE")
        outcome.blocking = [gate_roster.RosterEntry(
            name="human_approved", status="INDETERMINATE",
            detail="get an APPROVED PR review on the current head")]

        def require_fn(pr_url, *, config=None):
            raise MergeGateBlocked(outcome)

        merge_calls = []
        rc = land.land(PR_URL, require_fn=require_fn,
                       merge_fn=lambda u: merge_calls.append(u), config=CONFIG)

        assert rc == 2
        assert merge_calls == []
        assert "merge rides" not in capsys.readouterr().out


class TestSkillMDDocumentsTheAccept:
    """SKILL.md names the printed line, how to give an accept, and Gitea behaviour."""

    def test_skill_md_names_the_line_the_token_and_gitea(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "merge rides an operator-accept" in text, (
            "SKILL.md must document the line land.py prints"
        )
        assert "tp-accept:" in text, "SKILL.md must document the accept token"
        assert "Gitea" in text or "gitea" in text, (
            "forge parity: SKILL.md must state Gitea behaviour for the accept"
        )
