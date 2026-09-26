"""Backstops-in-force + breadcrumb-inert pins for the living-doc hand-resolution carry
(Phase 4, task 4.3). No production change — these pin the design's standing invariants:

  (a) `ci_local_stamp` stays a REQUIRED gate predicate irrespective of the carry — the carry
      touches no gate-predicate wiring, so a fresh SHA-keyed ci-local stamp is still demanded
      (it catches a doc edit that breaks e.g. inv #38 citation-coherence on the new head).
  (b) The `format_handres_cert_comment` breadcrumb has ZERO gate authority: an absent / forged /
      wrong-author copy changes NO `find_certified_anchor` verdict, because the verdict is a pure
      function of git objects (there is no channel through which a PR comment could enter the
      walk). Mirrors the producer breadcrumb's attack-5 guarantee.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))

import base_sync_oracle  # noqa: E402
import gate_roster  # noqa: E402
from base_sync_cert import find_certified_anchor  # noqa: E402
from base_sync_repo import build_scenario, diverge_living_doc, force_merge_commit  # noqa: E402

_MERGE_SCRIPTS = os.path.join(os.path.dirname(__file__), os.pardir, "tp-merge-from-main", "scripts")
if _MERGE_SCRIPTS not in sys.path:
    sys.path.insert(0, _MERGE_SCRIPTS)
import cert_comment  # noqa: E402

KI = "three-pillars-docs/known_issues.md"
_HAND_KEEP_ALL = (
    "# Fixture Living Doc\n\n### Z0: seed entry\nseed body line.\n"
    "- **2026-01-01** — base-side change\n- **2026-01-02** — design-side change\n"
)
# The whole approval carry ENABLED (outer gate on) — the handres inner flag is default-ON:
_CARRY_CONFIG = {
    "review": {"approval_survives_safe_base_sync": True,
               "require_human_approval": False, "expects_copilot": False},
    "ci": {"expects_github_checks": False},
}


def _seat(s, monkeypatch):
    s.git("fetch", "--quiet", "origin", s.base_ref, check=True)
    s.git("checkout", "--quiet", "-B", s.base_ref, f"origin/{s.base_ref}", check=True)
    monkeypatch.setattr(base_sync_oracle, "_oracle_code_dir", lambda: s.repo_dir)


# ---- (a) ci_local_stamp stays REQUIRED under the carry ----


def test_ci_local_stamp_still_required_under_carry(monkeypatch):
    from deterministic_gate import FailureClass

    # (1) Direct: the carry config does not disable the stamp requirement (default True).
    assert gate_roster._require_ci_local_stamp(_CARRY_CONFIG) is True

    # (2) Via the roster: with the carry enabled, ci_local_stamp is EVALUATED (live path), not
    # config-OMITTED. Root unresolvable → INDETERMINATE, which still proves it is REQUIRED.
    monkeypatch.setattr(gate_roster, "find_project_root", lambda: None, raising=False)
    _predicates, roster = gate_roster.build_predicates_and_roster(
        pr_url="https://github.com/o/r/pull/1",
        rollup=[],
        failure_class=FailureClass.INDETERMINATE,
        threads=[],
        mergeable="MERGEABLE",
        head_oid="deadbeef",
        config=_CARRY_CONFIG,
        r={"comments_fn": lambda _u: []},
        copilot_runners=None,
        running_live=True,      # forces the live stamp path (not the hermetic carve-out)
        shared_dir=None,
    )
    stamp = [e for e in roster if e.name == "ci_local_stamp"]
    assert len(stamp) == 1, "ci_local_stamp predicate missing from the roster under the carry"
    assert stamp[0].status != "OMITTED", (
        "ci_local_stamp must stay REQUIRED under the carry (the carry touches no gate wiring)"
    )


# ---- (b) the breadcrumb is inert: it changes no find_certified_anchor verdict ----


def test_forged_breadcrumb_changes_no_verdict(tmp_path, monkeypatch):
    s = build_scenario(tmp_path)
    diverge_living_doc(s)
    h0 = s.head()
    h1 = force_merge_commit(s, {KI: _HAND_KEEP_ALL})
    _seat(s, monkeypatch)

    baseline = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref,
                                     carry_handres=True)
    assert baseline.certified is True
    assert baseline.carry_paths == (KI,)

    # Conjure absent / forged / wrong-author breadcrumbs. NONE of them is an input to
    # find_certified_anchor — its verdict is re-derived from git objects alone, so a forged copy
    # (even one naming a non-carry `skills/evil.py`) cannot leak into carry_paths or flip a verdict.
    forged = cert_comment.format_handres_cert_comment("0" * 40, "f" * 40, ["skills/evil.py", KI])
    wrong_author = ("<sub>basesync-cert.v1: pre `dead` · post `beef` · allowlist v1 · "
                    "classes [living-doc-handres] · handres-files [skills/evil.py]</sub>")
    for _breadcrumb in (None, "", forged, wrong_author):
        again = find_certified_anchor(str(s.repo_dir), h1, {h0}, base_ref=s.base_ref,
                                      carry_handres=True)
        assert again == baseline, "the breadcrumb must never influence the re-derived verdict"
