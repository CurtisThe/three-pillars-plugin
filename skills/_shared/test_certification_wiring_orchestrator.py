"""Certification wiring pins: the orchestrator SKILL.md (Slot 4, Tier 5 Step 2b, escalation).

design: audit-pass-does-not-bind (Tasks 7.1, 7.2). The agent, protocol and
audit-skill pins live in `test_certification_wiring_skills.py`, the ledger and
self-claim pins in `test_certification_wiring_ledger.py`. Each pin is scoped to
the section that must carry the wiring, so a stray mention elsewhere in the
orchestrator cannot satisfy it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import skill_text

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_MD = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"
PROTOCOL = "skills/_shared/certification-protocol.md"
DISPATCH = 'Agent(subagent_type=agent_ref("tp-certifier"), model="opus")'
RS_LINE = ('if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then '
           'RS="$TOP"/skills/_shared/resolve_script.py; else '
           'RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi')
CERT_LINE = 'CERT="$(python3 "$RS" certify.py)" || exit 1'


def _text() -> str:
    return skill_text.read_skill_text("tp-run-full-design")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(start: str, end: str) -> str:
    """Flattened text from `start` to `end`; a `#` heading is matched only at a line start."""
    text = _text()
    i = text.index("\n" + start) + 1 if start.startswith("#") else text.index(start)
    return _flat(text[i:text.index(end, i)])


def _slot4() -> str:
    return _between("### Slot 4 — `design-audit`", "### Slot 5 — `plan`")


def _step2() -> str:
    return _between("### Step 2 — `impl-audit` slot", "### Step 3 — `design-learn` slot")


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def test_orchestrator_slot4_runs_the_slot4_form_of_step2b():
    slot4 = _slot4()
    assert not _missing(slot4, PROTOCOL, "§Step 2b", "`tp-certifier`",
                        '"$CERT" run', '"$CERT" fold --slot 4', "the `tp/{slug}` HEAD")


def test_tier2_table_and_bullet_route_slot4_through_the_fan_out():
    """F9: Slot 4 is the fan-out + Step 2b, never a `/tp-design-audit --auto` subagent (whose 6b
    would BLOCK every claim with no Agent tool)."""
    text = _text()
    tier2 = text[text.index("## Tier 2 — Design pipeline chain"):
                 text.index("### Audit rejection — self-heal, then escalate")]
    lines = tier2.splitlines()
    row = next(ln for ln in lines if ln.startswith("| 4 — `design-audit`"))
    assert "/tp-design-audit" not in row
    assert not _missing(row, "## Audit fan-out", "Step 2b")
    assert "/tp-design-audit --auto" not in tier2  # tp-allow-fragile: the command + flag name is the interface Slot 4 must never invoke
    bullet = next(ln for ln in lines if ln.startswith("- **Slot 4 (`design-audit`)**"))
    assert not _missing(bullet, "## Audit fan-out", "Step 2b", "never a `/tp-design-audit` subagent")


def test_orchestrator_step2b_dispatches_the_certifier_verdict_files_first():
    step2 = _step2()
    assert "Step 2b" in step2
    assert not _missing(step2, DISPATCH, "verdict files first")


def test_orchestrator_step2b_fences_claims_bytes_as_untrusted_data():
    assert "claims bytes fenced as untrusted data" in _step2()


def test_orchestrator_step2b_passes_the_resolved_cert_path_to_the_certifier():
    """F7: the certifier has no TP_ROOT in a consumer install; the prompt carries `$CERT`."""
    step2 = _step2()
    assert "the resolved absolute `$CERT` path" in step2
    assert step2.index(CERT_LINE) < step2.index(DISPATCH)


def test_orchestrator_step2b_copies_records_only_after_the_sha256_check():
    step2 = _step2()
    handoff = 'python3 "$CERT" handoff --certifier-return'
    assert not _missing(step2, "`records_file`", "`certifications/records/`", handoff,
                        "--unverified records-handoff")
    assert step2.index("sha256") < step2.index("`certifications/records/`")


def test_certify_cli_ships_handoff_as_the_caller_check():
    """F6: the caller's records check is the CLI `certify.py handoff`, never a bare
    `check_handoff` callable. The parsed CLI is the contract the prose cites (the
    reference itself is covered by `skill_refs`, invariant 46)."""
    certify_cli = pytest.importorskip("certify_cli")
    parser = certify_cli.build_parser()
    args = parser.parse_args(["handoff", "--certifier-return", "R", "--records", "F"])
    assert args.command == "handoff" and args.certifier_return == "R"
    with pytest.raises(SystemExit):
        parser.parse_args(["check_handoff", "--certifier-return", "R", "--records", "F"])


def test_orchestrator_step2b_starts_with_the_claimant_check():
    step2 = _step2()
    check = 'python3 "$CERT" claimant-check --base tp/{slug} --ref S'
    assert check in step2 and "`claimant-records`" in step2
    assert "`{design}` = the repo-relative design dir" in step2  # G2
    assert step2.index(check) < step2.index("tp-certifier")


def test_orchestrator_step2b_resolves_rs_once_then_runs_and_folds_once():
    step2 = _step2()
    assert not _missing(step2, _flat(RS_LINE), CERT_LINE, '"$CERT" run', "--watch-ref",
                        'one `python3 "$CERT" fold --slot 8`')
    assert step2.count(_flat(RS_LINE)) == 1
    assert step2.index('"$CERT" run') < step2.index('"$CERT" fold --slot 8')
    assert "python3 skills/" not in step2


def test_orchestrator_step2b_renders_issues_and_applies_them_after_the_tier56_fold():
    """F4: an apply on tp/{slug} before the fold reuses an id the candidate added."""
    step2 = _step2()
    assert "only renders the pending issues file" in step2 and "before Slot 9" not in step2
    assert "issues apply" not in step2.replace("`issues apply` runs after the Tier 5.6 fold", "")
    fold = _between("### Step 1 — Fold the candidate", "### Step 2 — Learn-verification")
    apply = 'python3 "$CL" issues apply --pending'
    assert apply in fold and "on the folded tree" in fold
    assert fold.index("git merge --no-ff") < fold.index(apply)


def test_orchestrator_step2b_cites_the_protocol_section_instead_of_restating_it():
    step2 = _step2()
    assert f"`{PROTOCOL}` §Step 2b" in step2
    # the claimant-record diff and the ledger render are the protocol's, not restated here
    assert "candidate_paths_ok" not in step2 and "ledger render" not in step2


def test_orchestrator_step2b_names_results_by_path_and_folds_every_result():
    """F5: `--name` is the path under certifications/ (fold rejects a repeated (file, id)).
    F12: every result folds, sweep ones included, with the diff as `--verdict-guards`."""
    step2 = _step2()
    assert "`--name` = the file's path under `certifications/`" in step2
    assert "`--out <scratch>/r<N>.result.json`" in step2  # J1: an injective scratch name
    assert "`guard_claims[]` id no `records/` result certified folds `unverified`" in step2
    fold = step2[step2.index('one `python3 "$CERT" fold --slot 8`'):]
    assert not _missing(fold, "a `--result` for every result (sweep ones included)",
                        "`--verdict-guards <scratch>/diff.txt`",
                        "`git -c core.quotePath=false diff --no-renames --name-only "
                        "tp/{slug}...S > "
                        "<scratch>/diff.txt`")  # J3: a non-ASCII guard path is not C-quoted


def test_orchestrator_step2b_commits_once_at_protocol_step7():
    """F13: one commit point, after the HEAD assert; the records step only copies."""
    step2 = _step2()
    assert "only then commit" not in step2
    assert "One commit, at protocol step 7 (after the HEAD assert)." in step2


def test_orchestrator_light_path_returns_guard_claims():
    light = _between("### Light slot mapping", "## Audit fan-out (Slots 4/6/8)")
    assert not _missing(light, "`guard_claims[]`")


def _escalation() -> str:
    return _between("## Retry-with-advice escalation\n", "\n## Lock ownership\n")


def _log_tokens(section: str, prefix: str) -> set[str]:
    """The `<prefix> <token>` decision-log entries a section appends (one per trigger)."""
    return set(re.findall(re.escape(prefix) + r" ([a-z][a-z-]*)", section))


def test_escalation_names_three_triggers_including_certification_unverified():
    esc = _escalation()
    # a closed set of three triggers, read as the decision-log tokens (prose wording free)
    assert _log_tokens(esc, "[orchestrator/<audit-slot>]") == {
        "retry-exhausted", "certification-unverified", "map-check-escalated"}
    assert not _missing(esc, "`certification-unverified`", "`tree_mutated`",
                        "`claimant-records`", "`records-handoff`", "certify.py exit ≠ 0", "incomplete `--out`",
                        "`tp:needs-human-attention`", "[orchestrator/<audit-slot>] certification-unverified")


def test_escalation_certification_unverified_is_never_respawn_advice():
    esc = _escalation()
    trigger = esc[esc.index("**`certification-unverified`** —"):]
    assert "**never** re-spawn advice" in trigger


def test_escalation_branching_order_is_map_check_then_certification_then_status():
    order = "map-check → `certification-unverified` → `status`"
    assert order in _escalation()


def test_escalation_audit_rejection_lists_four_terminal_causes():
    rejection = _between("### Audit rejection — self-heal, then escalate", "### Token-cap boundary check")
    # four causes: the three Tier 2 decision-log tokens plus certification-unverified,
    # which logs per ## Retry-with-advice escalation (the count is derived, never prose)
    assert _log_tokens(rejection, "[tp-run-full-design/tier-2]") == {
        "audit-retry-exhausted", "design-floor-blocked", "map-check-escalated"}
    assert "certification-unverified" in rejection


def test_escalation_budget_table_has_a_per_dispatch_certifier_row():
    table = _between("## Per-slot budget table", "### Audit-tier dispatch accounting")
    row = next(ln for ln in _text().splitlines() if ln.startswith("| `certifier`"))
    assert _flat(row) in table and "/ dispatch" in row


def test_legacy_fallback_pr_body_tells_the_human_to_apply_pending_issues():
    """T3: after a fold conflict the Tier 5.6 apply never ran; the human runs it post-resolve."""
    fallback = _between("#### Tier 6 — legacy fallback", "### Step 2 — `gh pr create`")
    assert "after resolving the conflict" in fallback
    # K3: the full pending path, so a wrong or elided file cannot pass
    assert ('python3 "$CL" issues apply --pending {design}/certifications/records/'
            'known-issues.pending.md --known-issues three-pillars-docs/known_issues.md') in fallback
