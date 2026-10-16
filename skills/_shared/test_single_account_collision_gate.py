"""Tests for gate-regression (Task 3.3) and advisory (Task 2.1) —
solo-operator-identity-split.

Covers:
  - Task 3.3: no-gate-behavior-change regression (predicate roster + automation set)
  - Task 2.1: collision_advisory.py unit tests (framework-check.sh advisory helper)

Detection tests (Tasks 1.1/1.2/3.1) live in test_single_account_collision.py.

Run with: python -m pytest skills/_shared/test_single_account_collision_gate.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_collision_advisory = pytest.mark.skipif(
    not (_DEV_ROOT / "skills/_shared/collision_advisory.py").exists(),
    reason="imports the dev-only collision_advisory.py (dev-repo only)")
# The plugin ships its own, different CLAUDE.md; framework-check.sh marks the dev repo.
_needs_claude_md = pytest.mark.skipif(
    not (_DEV_ROOT / "framework-check.sh").exists(),
    reason="reads the dev repo's CLAUDE.md, not the plugin's (dev-repo only)")
_needs_known_issues = pytest.mark.skipif(
    not (_DEV_ROOT / "three-pillars-docs/known_issues.md").exists(),
    reason="reads the dev repo's known_issues.md (dev-repo only)")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# gate_roster lives beside deterministic_gate in _shared
SHARED_DIR = HERE


# ---------------------------------------------------------------------------
# Task 3.3 — no-gate-behavior-change regression
# ---------------------------------------------------------------------------

class TestNoGateBehaviorChange:
    """Regression: the gate predicate roster matches an explicit allowlist and
    automation_identities is unchanged. New predicates must be admitted to
    EXPECTED_PRED_NAMES deliberately (so the negative 'no unexpected pred_*'
    check stays meaningful) — the single-account-collision design itself added
    none; later designs (e.g. enforce-review-proof's review_proof_on_head) extend
    the allowlist as they land."""

    EXPECTED_PRED_NAMES = [
        "threads_resolved",
        "mergeable",
        "checks_success",
        "copilot_on_head",
        "human_approved",
        # Sub-predicates called within gate_roster's build logic:
        "diff_not_ballooned",  # conditional inside checks_success path
        "ci_local_stamp",      # p6: ci-local stamp predicate
        # p7: review-proof-on-head (added by the enforce-review-proof design — this
        # cross-design baseline allowlist is updated to admit it so the negative
        # "no unexpected pred_*" check stays meaningful for future designs).
        "review_proof_on_head",
        # review-log-survives-teardown (operator-approved): the p6 adapter
        # round_log_carry.pred_ci_local_stamp_carried wraps pred_ci_local_stamp at
        # both gate_roster stamp sites and reports under the existing
        # `ci_local_stamp` roster name.
        "ci_local_stamp_carried",
    ]

    def test_predicate_roster_ordered_name_list_unchanged(self):
        """Gate predicate roster (ordered name list) must match the pre-design baseline."""
        import inspect
        import re
        import gate_roster

        src = inspect.getsource(gate_roster)

        for name in self.EXPECTED_PRED_NAMES:
            assert name in src, (
                f"predicate name '{name}' disappeared from gate_roster source — "
                "an expected gate predicate went missing"
            )

        # Negative check: no pred_* exists that isn't in the allowlist above.
        # A new predicate must be added to EXPECTED_PRED_NAMES deliberately.
        found = re.findall(r"\bpred_(\w+)\b", src)
        found_unique = list(dict.fromkeys(found))  # preserve order, dedupe
        for name in found_unique:
            assert name in self.EXPECTED_PRED_NAMES, (
                f"unexpected pred_{name} found in gate_roster — "
                "admit it to EXPECTED_PRED_NAMES if it is an intended new predicate"
            )

    def test_automation_identities_membership_baseline(self):
        """automation_identities set for a fixed input must match the pre-design baseline."""
        from human_approval import automation_identities

        self_login = "testbot"
        cfg = {"review": {}}
        ids = automation_identities(self_login=self_login, config=cfg)

        # Must always include the self_login (lowercased)
        assert self_login.lower() in ids, "self_login must be in automation set"

        # Must include known GitHub-native bots
        assert "github-actions[bot]" in ids
        assert "dependabot[bot]" in ids

        # Must include Copilot bots (from review_readiness._REST_COPILOT_LOGINS)
        assert "copilot[bot]" in ids or any("copilot" in x for x in ids), (
            "Copilot bots must be in automation set"
        )

        # The new detection helpers must NOT add any entries here
        new_helper_logins = {"single_account_collision", "approval_collision_signature"}
        for nhl in new_helper_logins:
            assert nhl not in ids, f"'{nhl}' must not appear in automation set"

    def test_single_account_collision_live_is_not_gate_predicate(self):
        """single_account_collision_live is NOT importable from deterministic_gate."""
        import deterministic_gate
        assert not hasattr(deterministic_gate, "single_account_collision_live"), (
            "detection helper must not be added to the gate module"
        )

    def test_approval_collision_signature_live_is_not_gate_predicate(self):
        """approval_collision_signature_live is NOT importable from deterministic_gate."""
        import deterministic_gate
        assert not hasattr(deterministic_gate, "approval_collision_signature_live"), (
            "signature helper must not be added to the gate module"
        )


# ---------------------------------------------------------------------------
# Task 2.1 — framework-check advisory (collision_advisory.py unit tests)
# ---------------------------------------------------------------------------

class TestCollisionAdvisory:
    """Tests for collision_advisory.py — the helper invoked by framework-check.sh.

    The advisory must:
      - Print 'COLLISION self_login=<login>' when single_account_collision_live() is True
      - Print nothing when single_account_collision_live() is False
      - Always exit 0 (warn-only, never blocks)
      - Swallow ALL exceptions (fail-open)
    """

    REPO_ROOT = str(HERE.parent.parent)

    def _run_advisory(self, stub_collision: bool, fake_login: str = "testbot"):
        """Run collision_advisory.main() with a monkeypatched single_account_collision_live."""
        import io
        import unittest.mock as mock
        collision_advisory = pytest.importorskip("collision_advisory")

        with mock.patch("single_account_detect.single_account_collision_live",
                        return_value=stub_collision):
            fake_proc = mock.MagicMock()
            fake_proc.returncode = 0
            fake_proc.stdout = fake_login + "\n"
            with mock.patch("subprocess.run", return_value=fake_proc):
                buf = io.StringIO()
                with mock.patch("sys.stdout", buf):
                    rc = collision_advisory.main([self.REPO_ROOT])
        return rc, buf.getvalue()

    @_needs_collision_advisory
    def test_collision_true_prints_collision_line(self):
        """When collision is detected, COLLISION line is printed, exit 0."""
        rc, out = self._run_advisory(stub_collision=True, fake_login="mybot")
        assert rc == 0, "advisory must always exit 0"
        assert out.startswith("COLLISION self_login="), (
            f"expected COLLISION line, got: {out!r}"
        )
        assert "mybot" in out

    @_needs_collision_advisory
    def test_collision_false_prints_nothing(self):
        """When no collision, nothing is printed, exit 0."""
        rc, out = self._run_advisory(stub_collision=False)
        assert rc == 0
        assert out == "", f"expected empty output, got: {out!r}"

    @_needs_collision_advisory
    def test_advisory_swallows_exception(self):
        """Any exception from single_account_collision_live is swallowed (fail-open)."""
        import io
        import unittest.mock as mock
        collision_advisory = pytest.importorskip("collision_advisory")

        with mock.patch("single_account_detect.single_account_collision_live",
                        side_effect=RuntimeError("boom")):
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                rc = collision_advisory.main([self.REPO_ROOT])
        assert rc == 0
        assert buf.getvalue() == ""


# ---------------------------------------------------------------------------
# Task 4.1 — doc-coherence assertions (grep tests)
# ---------------------------------------------------------------------------

class TestDocCoherence:
    """Grep assertions that getting-started names the machine-account flip as the
    recommended default with M18 trade explicit, and cross-refs are coherent.

    These are the 'Red before edit' tests: before the edit, these greps fail.
    After the doc update, they pass.
    """

    REPO_ROOT = Path(SHARED_DIR).parent.parent
    CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
    HOWTO_MD = SHARED_DIR / "human-approval-howto.md"
    KNOWN_ISSUES_MD = REPO_ROOT / "three-pillars-docs" / "known_issues.md"

    def _read(self, path):
        return Path(path).read_text(encoding="utf-8")

    def _issue_text(self):
        """Every live issue doc concatenated (certify_issues.LIVE_ISSUE_DOCS).

        skill-context-diet D5b moved the Lows out of `known_issues.md` into the
        cold `known_issues_low.md`, so an issue pin reads the tuple, never one doc.
        """
        import certify_issues

        return "\n".join(
            self._read(self.REPO_ROOT / rel)
            for rel in certify_issues.LIVE_ISSUE_DOCS
            if (self.REPO_ROOT / rel).exists())

    @_needs_claude_md
    def test_getting_started_names_machine_account_flip_as_default(self):
        """CLAUDE.md getting-started must name the machine-account flip as recommended default."""
        text = self._read(self.CLAUDE_MD)
        # Must contain 'Solo operator setup' or similar section
        assert "Solo operator setup" in text or "machine account" in text, (
            "CLAUDE.md must name the machine-account flip in the getting-started path"
        )

    @_needs_claude_md
    def test_getting_started_references_m18_trade(self):
        """CLAUDE.md must make the M18 UI-bypass trade explicit."""
        text = self._read(self.CLAUDE_MD)
        assert "M18" in text, (
            "CLAUDE.md must cross-link M18 to make the UI-bypass trade explicit"
        )

    def test_howto_remedy_section_retained_and_re_pointed(self):
        """human-approval-howto.md §Single-account operator section must be present."""
        text = self._read(self.HOWTO_MD)
        assert "Single-account operator" in text, (
            "human-approval-howto.md must retain the Single-account operator section"
        )
        # Must mention the flip as recommended
        assert "recommended" in text.lower() and (
            "machine" in text or "flip" in text or "distinct" in text.lower()
        ), "howto must name the flip as recommended"

    @_needs_known_issues
    def test_known_issues_l37_cross_refs_design(self):
        """The live issue docs must carry L37 referencing solo-operator-identity-split.

        L37 is a Low, so since skill-context-diet it lives in `known_issues_low.md`;
        the pin reads the live issue-doc tuple so it stays true wherever the entry is.
        """
        text = self._issue_text()
        # L37 section must mention this design
        l37_start = text.find("### L37")
        assert l37_start != -1, "L37 entry not found in the live issue docs"
        l37_text = text[l37_start:l37_start + 2000]
        assert "solo-operator-identity-split" in l37_text, (
            "L37 must reference solo-operator-identity-split as the ergonomics resolution"
        )

    @_needs_known_issues
    def test_known_issues_m18_cross_refs_l37(self):
        """known_issues.md M18 must cross-reference L37."""
        text = self._read(self.KNOWN_ISSUES_MD)
        m18_start = text.find("### M18")
        assert m18_start != -1, "M18 entry not found in known_issues.md"
        m18_text = text[m18_start:m18_start + 2000]
        assert "L37" in m18_text, "M18 must cross-reference L37"

    @_needs_known_issues
    def test_known_issues_m18_names_solo_design(self):
        """known_issues.md M18 must reference solo-operator-identity-split."""
        text = self._read(self.KNOWN_ISSUES_MD)
        m18_start = text.find("### M18")
        assert m18_start != -1
        m18_text = text[m18_start:m18_start + 2000]
        assert "solo-operator-identity-split" in m18_text
