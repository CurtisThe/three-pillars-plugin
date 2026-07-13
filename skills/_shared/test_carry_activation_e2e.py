"""End-to-end ACTIVATION test [SHIP GATE] -- task 8.5, Phase 8.

Design-audit MANDATE (torvalds HIGH): the base-sync approval carry must demonstrably
FIRE in the documented invocation topology (SKILL.md step 6.7 / step 2's dispatch-
from-seat recipe), not just fail closed against a fixture that never reaches it. This
is a hermetic, offline, real-subprocess test -- it invokes the ACTUAL
`gate_cli.py --repo <path> <pr_url>` CLI (no injected runners, no monkeypatched
`evaluate_gate`) against a real embedded-framework fixture (see
`fixtures/embedded_framework.py`): a seat + `*-wt/{name}` design worktree topology,
an origin remote redirected offline, a `gh` PATH shim, and carry config committed at
the fixture's HEAD.

Positive activation (this file) + attack 8's two-topology tampered-worktree extension
(task 8.6) live together here; split `test_base_sync_cert_attack8.py` if this file
nears the 300L soft-warn.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES_DIR = HERE / "fixtures"
for _p in (HERE, FIXTURES_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import embedded_framework as ef  # noqa: E402


def _invoke(fixture: ef.EmbeddedFixture, *, code_root, repo_root, cwd, head_oid=None):
    argv = fixture.gate_cli_argv(code_root=code_root, repo_root=repo_root)
    return subprocess.run(
        argv, cwd=str(cwd), env=fixture.env(head_oid=head_oid),
        capture_output=True, text=True,
    )


def _human_approved_line(stdout: str) -> str:
    """Extract the ROSTER line (not the BLOCKING line -- both name human_approved) for
    detail assertions. ROSTER format: '  [STATUS] human_approved -- detail' (the status
    code is inside the brackets); BLOCKING format: '  [human_approved] detail' (the
    predicate NAME is inside the brackets) -- distinguish on '] human_approved'."""
    for line in stdout.splitlines():
        if "] human_approved" in line:
            return line
    return ""


# ============================================================
# Task 8.5: positive activation -- the documented invocation FIRES the carry
# ============================================================


def test_carry_fires_via_documented_dispatch_from_seat_invocation(tmp_path, monkeypatch):
    """THE SHIP-GATE ASSERTION: the ACTUAL step-6.7 invocation --
    `python3 <seat>/skills/tp-merge-from-main/scripts/gate_cli.py --repo <worktree>
    <pr_url>` run as a real subprocess with cwd=<design worktree> -- turns the carry
    ON in its primary documented topology. No runners injected, no evaluate_gate
    monkeypatch: this is the CLI exactly as an operator would invoke it."""
    fixture = ef.build_embedded_fixture(tmp_path, monkeypatch)

    result = _invoke(
        fixture, code_root=fixture.seat, repo_root=fixture.design_wt, cwd=fixture.design_wt,
    )

    assert result.returncode == 0, (
        f"expected PASS (0); got {result.returncode}\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert "VERDICT: PASS" in result.stdout
    line = _human_approved_line(result.stdout)
    assert "PASS" in line, f"human_approved must be PASS; roster line: {line!r}"
    assert "approval carried across 1 certified base-sync merge" in line, (
        f"the carry detail must name the certified-merge count; roster line: {line!r}"
    )


def test_carry_negative_control_wrong_code_location_refuses(tmp_path, monkeypatch):
    """Negative control: the SAME invocation shape, but the code is resolved from the
    design worktree's OWN copy instead of the seat (the naive $TP_ROOT mis-resolution
    SKILL.md's dispatch-from-seat note warns against). Proves the doc note is
    LOAD-BEARING, not decorative -- the carry is refused with the oracle's reason,
    fail-closed (never an unsound PASS)."""
    fixture = ef.build_embedded_fixture(tmp_path, monkeypatch)

    result = _invoke(
        fixture, code_root=fixture.design_wt, repo_root=fixture.design_wt, cwd=fixture.design_wt,
    )

    assert result.returncode == 2, (
        f"expected INDETERMINATE (2); got {result.returncode}\nSTDOUT:\n{result.stdout}"
    )
    line = _human_approved_line(result.stdout)
    assert "INDET" in line
    assert "oracle code provenance indeterminate" in line, (
        f"the refusal must name the oracle's DISJOINT-CODE reason; roster line: {line!r}"
    )
    assert "approval carried" not in result.stdout


# ============================================================
# Task 8.6: Attack 8 [case 8, SHIP GATE] -- two-topology tampered-worktree subprocess test
# ============================================================
#
# Stated limit (no test can prove a TAMPERED guard fires): a deliberately tampered
# oracle/gate copy could, in principle, skip its own check and fabricate a PASS --
# no in-process test can rule that out (design.md's Trust-anchor bound). What CAN be
# proven, and is proven here: (8a) the HONEST guard, physically misplaced in the
# tampered worktree, refuses on DISJOINT-CODE; (8b) the HONEST guard, invoked from its
# correct seat location against a --repo pointed at the tampered worktree, refuses on
# condition 5 (byte-inequality) because the tampered content is never reproduced by
# the honest resolver; and a sibling honestly-built merge, invoked the identical way,
# still certifies. The residual -- an attacker who deliberately invokes a TAMPERED
# gate copy from the seat-equivalent position -- is the documented M18-class
# discipline gap (design.md, GitHub-UI-bypass precedent), outside any in-process
# check's reach.


def test_attack8a_tampered_worktree_own_code_refuses_disjoint_code(tmp_path, monkeypatch):
    """8a: code resolved from the TAMPERED worktree itself (its own gate_cli.py) -- the
    oracle guard refuses on DISJOINT-CODE, regardless of the tampered content, because
    the classification happens before any content is ever inspected (the
    honest-guard-in-wrong-place misconfiguration becomes a refusal)."""
    fixture = ef.build_embedded_fixture(tmp_path, monkeypatch)
    tampered_wt, h1_bad = ef.build_tampered_sibling(fixture)

    result = _invoke(
        fixture, code_root=tampered_wt, repo_root=tampered_wt, cwd=tampered_wt, head_oid=h1_bad,
    )

    line = _human_approved_line(result.stdout)
    assert "oracle code provenance indeterminate" in line, (
        f"8a must refuse on the oracle's DISJOINT-CODE reason; roster line: {line!r}"
    )
    assert "approval carried" not in result.stdout


def test_attack8b_honest_seat_code_refuses_tampered_content_cond5(tmp_path, monkeypatch):
    """8b: code resolved from the fixture SEAT's honest copy (--repo pointed at the
    tampered worktree) -- DISJOINT-CODE passes (the seat IS the honest location), but
    the tampered resolution is never byte-reproduced by the honest resolver -> the
    chain walk's condition-5 check refuses. This is the primitive attack 2 pin
    (`test_attack2_hand_resolution_byte_inequality_yet_verify_clean`) exercised through
    the real CLI + subprocess boundary instead of the in-process primitive."""
    fixture = ef.build_embedded_fixture(tmp_path, monkeypatch)
    tampered_wt, h1_bad = ef.build_tampered_sibling(fixture)

    result = _invoke(
        fixture, code_root=fixture.seat, repo_root=tampered_wt, cwd=tampered_wt, head_oid=h1_bad,
    )

    line = _human_approved_line(result.stdout)
    assert "resolved bytes do not match h1's committed blob" in line, (
        f"8b must refuse on condition 5 (byte-inequality); roster line: {line!r}"
    )
    assert "approval carried" not in result.stdout


def test_attack8_honest_sibling_merge_still_certifies(tmp_path, monkeypatch):
    """The honest-code path is not collaterally broken by attack 8's tampered sibling:
    invoked the IDENTICAL way (seat's code, --repo pointed at the design worktree), the
    ORIGINAL honestly-certified merge (task 8.5's fixture, untouched by
    build_tampered_sibling) still certifies and PASSes -- proving 8a/8b's refusals are
    specific to the tampered content, not a side effect of the tampered sibling's mere
    existence in the same fixture."""
    fixture = ef.build_embedded_fixture(tmp_path, monkeypatch)
    ef.build_tampered_sibling(fixture)   # tampered sibling exists alongside; must not interfere

    result = _invoke(
        fixture, code_root=fixture.seat, repo_root=fixture.design_wt, cwd=fixture.design_wt,
    )

    assert result.returncode == 0, (
        f"the honest sibling merge must still certify; got {result.returncode}\n"
        f"STDOUT:\n{result.stdout}"
    )
    line = _human_approved_line(result.stdout)
    assert "approval carried across 1 certified base-sync merge" in line
