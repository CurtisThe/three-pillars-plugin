"""Certification wiring pins: agent, protocol and audit-skill prose.

design: audit-pass-does-not-bind (Tasks 6.3, 7.4-7.6, 10.3). The orchestrator
wiring pins live in `test_certification_wiring_orchestrator.py`, the ledger and
self-claim pins in `test_certification_wiring_ledger.py`, and the `.github/`
review-doc pins in the dev-only `test_certification_wiring_review_docs.py`
(`.github/` never ships).
"""
# pin-source: skills/tp-implementation-audit/SKILL.md
from __future__ import annotations

from pathlib import Path

from cert_phrase_scan import NO_CLAIMS, SECTION_HEADING
from certify_ledger import PENDING_PHRASE

ROOT = Path(__file__).resolve().parent.parent.parent


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_worker_claims_only():
    """A worker commits claims, never records: records are the certifier's, copied by the orchestrator."""
    text = _read("agents", "tp-worker.md")
    assert "under `{design}/certifications/` commit only top-level `*.claims.json`" in text


# --------------------------------------------------------------------------- #
# Interactive audit surfaces (Tasks 7.4, 7.5): one shared certify-step shape.
# --------------------------------------------------------------------------- #
PROTOCOL = "skills/_shared/certification-protocol.md"
DISPATCH = 'Agent(subagent_type=agent_ref("tp-certifier"), model="opus")'
RS_LINE = ('if [ -n "$TOP" ] && [ -f "$TOP"/skills/_shared/resolve_script.py ]; then '
           'RS="$TOP"/skills/_shared/resolve_script.py; else '
           'RS="$TP_ROOT"/skills/_shared/resolve_script.py; fi')
CERT_LINE = 'CERT="$(python3 "$RS" certify.py)" || exit 1'
HANDOFF = 'python3 "$CERT" handoff --certifier-return'


def _skill(name: str) -> str:
    return _read("skills", name, "SKILL.md")


def _certify_step(text: str) -> str:
    """The `Certify guard claims` step: from its heading to the next `### ` / `## ` heading."""
    start = text.index("Certify guard claims")
    ends = [i for i in (text.find("\n### ", start), text.find("\n## ", start)) if i != -1]
    return text[start:min(ends)] if ends else text[start:]


def _template(text: str) -> str:
    start = text.index("```markdown")
    return text[start:text.index("\n```\n", start + 1)]


def _missing(text: str, *needles: str) -> list[str]:
    return [n for n in needles if n not in text]


def _assert_certify_step(skill: str, claims_name: str) -> str:
    text = _skill(skill)
    step = _certify_step(text)
    assert not _missing(step, PROTOCOL, f"certifications/{claims_name}.claims.json", DISPATCH,
                        "fenced as untrusted data", "`records_file`", HANDOFF, "records-handoff",
                        "`certifications/records/", RS_LINE, CERT_LINE, '"$CERT" run', "--artifact")
    assert step.index(HANDOFF) < step.index("`certifications/records/")
    assert "check_handoff" not in text, "no shipped caller: the CLI is `certify.py handoff` (F6)"
    assert "python3 skills/" not in text
    unavailable = step[step.index("`certifier-unavailable`"):]
    assert "Cause: certification-unverified" in unavailable
    assert "as a subagent (no Agent tool)" in step
    return text


def test_impl_audit_template_has_mandatory_guards_certified_section():
    template = _template(_skill("tp-implementation-audit"))
    assert SECTION_HEADING in template and NO_CLAIMS in template  # the tokens the scan parses


def test_impl_audit_certify_step_dispatches_copies_and_runs():
    text = _assert_certify_step("tp-implementation-audit", "impl-audit")
    assert "`--auto`" in _certify_step(text)


def test_impl_audit_auto_verdict_joins_certification_after_compute_verdict():
    auto = _skill("tp-implementation-audit").split("## Auto Mode", 1)[1]
    assert "combine_verdict" in auto
    assert auto.index("compute_verdict") < auto.index("combine_verdict")
    assert "Cause: certification-unverified" in auto


def test_impl_audit_stays_under_200_lines():
    assert len(_skill("tp-implementation-audit").splitlines()) <= 200


def test_design_audit_certify_step_claims_existing_guards_on_the_base():
    text = _assert_certify_step("tp-design-audit", "design-audit")
    step = _certify_step(text)
    assert not _missing(step, "**existing**", "`--auto`")


def test_design_audit_presents_a_guards_certified_section():
    step = _certify_step(_skill("tp-design-audit"))
    assert SECTION_HEADING in step and NO_CLAIMS in step


def test_design_audit_auto_escalates_unverified_certification():
    auto = _skill("tp-design-audit").split("## Auto Mode", 1)[1]
    assert "Cause: certification-unverified" in auto
    assert "not-binding" in auto and "false-red" in auto


def test_phase_review_template_has_mandatory_guards_certified_section():
    template = _template(_skill("tp-phase-review"))
    assert SECTION_HEADING in template and NO_CLAIMS in template


def test_phase_review_certify_step_dispatches_copies_and_runs():
    text = _assert_certify_step("tp-phase-review", "phase-review")
    assert "certifications/phase-review.claims.json" in text.split("## Rules", 1)[0]


SURFACES = (("tp-implementation-audit", "impl-audit"), ("tp-design-audit", "design-audit"),
            ("tp-phase-review", "phase-review"))


def _protocol_surfaces() -> str:
    text = _read(PROTOCOL)
    return " ".join(text[text.index("**Interactive surfaces**"):text.index("\n## Certify-sweep")].split())


def test_zero_claim_surfaces_still_scan_the_artifact():
    """F2: with no claims the step still phrase-scans (`scan --artifact`); nothing skips it."""
    for skill, _ in SURFACES:
        step = " ".join(_certify_step(_skill(skill)).split())
        assert "skip to" not in step.lower(), skill
        assert 'python3 "$CERT" scan --artifact' in step, skill
        assert step.index(CERT_LINE) < step.index('"$CERT" scan'), skill
    assert 'python3 "$CERT" scan --artifact' in _protocol_surfaces()


SCAN_USE = {"tp-implementation-audit": "prints the `verdict` to join into `## Verdict`",
            "tp-design-audit": "prints the `verdict` to report with them",
            "tp-phase-review": "prints the `verdict` to report;"}


def _scan_sentence(flat: str) -> str:
    i = flat.index('"$CERT" scan --artifact')
    return flat[flat.rfind(". ", 0, i) + 2:flat.index(";", i) + 1]


def test_zero_claim_scan_verdict_is_joined_never_optional():
    """H4/F2: each surface's use of the zero-claim scan verdict is pinned verbatim."""
    surfaces = [(" ".join(_certify_step(_skill(s)).split()), s) for s in SCAN_USE]
    for step, skill in [*surfaces, (_protocol_surfaces(), None)]:
        start = step.index("With no claims")
        sentence = _scan_sentence(step) if skill else step[start:step.index(". ", start) + 1]
        want = SCAN_USE.get(skill, "prints the verdict the artifact's own verdict joins")
        # K3: the sentence ends at the pinned use (no trailing "when convenient")
        assert sentence[:-1].endswith(want.rstrip(";")), (skill, sentence)
        assert not any(w in sentence.lower() for w in ("optional", "ignor", "may skip")), skill


CERT_PATH = "the resolved absolute `$CERT` path"


def test_every_certifier_dispatch_passes_the_resolved_cert_path():
    """F7: a consumer-install certifier has no TP_ROOT; it runs the `$CERT` it is handed."""
    for skill, _ in SURFACES:
        step = " ".join(_certify_step(_skill(skill)).split())
        assert CERT_PATH in step, skill
        assert step.index(CERT_LINE) < step.index(DISPATCH) < step.index(CERT_PATH), skill
    flat = " ".join(_read(PROTOCOL).split())
    contract = flat[flat.index("## Certifier contract"):flat.index("## Statuses")]
    assert CERT_PATH in contract
    assert CERT_PATH in " ".join(_runbook().split())
    agent = " ".join(_read("agents", "tp-certifier.md").split())
    assert "use the `$CERT` path the dispatch prompt gives you" in agent
    assert "never resolve it yourself through `TP_ROOT`" in agent


def _protocol_step(n: int) -> str:
    text = _read(PROTOCOL)
    step2b = text[text.index("\n## Step 2b\n"):text.index("**Slot 4** uses")]
    start = step2b.index(f"\n{n}. ")
    nxt = step2b.find(f"\n{n + 1}. ", start)
    return " ".join(step2b[start:nxt if nxt != -1 else len(step2b)].split())


def test_protocol_names_the_caller_check_clis_never_check_handoff():
    """F6: `handoff` / `claimant-check` are CLIs with shipped callers; records-handoff is a cause."""
    text = _read(PROTOCOL)
    flat = " ".join(text.split())
    assert "check_handoff" not in text and "candidate_paths_ok" not in text
    assert "`certify_cli_checks.py`" in flat
    assert HANDOFF in flat and "--unverified records-handoff" in flat
    assert HANDOFF in _protocol_surfaces()
    assert 'python3 "$CERT" claimant-check --base tp/{slug} --ref S --design' in _protocol_step(1)
    assert HANDOFF in _protocol_step(3)
    step3, step7 = _protocol_step(3), _protocol_step(7)
    for n in range(1, 7):  # H4/F13: no step before 7 commits
        step = _protocol_step(n).replace("committed at step 7", "")
        assert "commit" not in step.lower(), f"protocol Step 2b step {n} mentions a commit"
    assert step7.startswith("7. **Commit once**") and "No earlier step commits." in step7
    assert step7.index("git symbolic-ref --short HEAD") < step7.index("one commit")
    # T2/J1: the records path is explicit; results take an injective index token
    assert "`records/impl-audit.json`" in step3 and "records/<name>.json" not in step3
    step4, step5 = _protocol_step(4), _protocol_step(5)
    assert "--out <scratch>/r<N>.result.json" in step4 and "1-based index" in step4
    assert "<flat>" not in step4 and "<scratch>/<name>." not in step4
    assert "`guard_claims[]` id" in step5 and "`no-result`" in step5  # J1 coverage
    assert ("--verdict-guards <scratch>/diff.txt` (`git -c core.quotePath=false diff "
            "--no-renames --name-only "
            "tp/{slug}...S > <scratch>/diff.txt`") in step5  # J3
    causes = flat[flat.index("Then, in order on every audit return"):]
    assert "`records-handoff`" in causes.split("**Slot 4**")[0]


# --------------------------------------------------------------------------- #
# Light checklist (Task 7.6, F11); the `.github/` review-doc pins are dev-only
# (test_certification_wiring_review_docs.py).
# --------------------------------------------------------------------------- #
def test_light_checklist():
    text = _read("skills", "_shared", "weight-class.md")
    checklist = text.split("> **Fidelity checklist (light weight class)**", 1)[1].split("\n\n", 1)[0]
    item = next(ln for ln in checklist.split("\n> - [ ]") if "[cert:<id>]" in ln)
    assert PROTOCOL in " ".join(item.replace(">", " ").split())


# --------------------------------------------------------------------------- #
# Post-merge certify-sweep (Task 10.3; N2, N7, N12, N13, P8, P10).
# --------------------------------------------------------------------------- #
CL_LINE = 'CL="$(python3 "$RS" certify_ledger.py)" || exit 1'
SWEEP_ADDS = ("certifications/records/", "sweep-ledger.md", "three-pillars-docs/known_issues.md",
              "three-pillars-docs/known_issues_resolved.md")


def _runbook() -> str:
    text = _read(PROTOCOL)
    start = text.index("\n## Certify-sweep\n")
    return text[start:text.index("\n## ", start + 1)]


def _mode_block() -> str:
    text = _skill("tp-implementation-audit")
    start = text.index("### Certify-sweep mode")
    ends = [i for i in (text.find("\n### ", start), text.find("\n## ", start)) if i != -1]
    return text[start:min(ends)]


def test_certify_sweep_mode_block():
    text = _skill("tp-implementation-audit")
    hint = next(ln for ln in text.splitlines() if ln.startswith("argument-hint:"))
    assert "--certify-sweep" in hint
    block = _mode_block()
    assert len(block.strip().splitlines()) <= 12
    assert not _missing(block, "`--certify-sweep`", PROTOCOL, "§Certify-sweep", "`--auto`")


def test_certify_sweep_runbook_steps_and_scoped_add():
    runbook = _runbook()
    flat = " ".join(runbook.split())
    assert not _missing(flat, "resolve_design_dir", 'python3 "$CL" design-dir', "refuses `--auto`",
                        'python3 "$CERT" validate', 'python3 "$CERT" run', "--watch-ref",
                        'python3 "$CL" ledger render', 'python3 "$CL" ledger verify',
                        'python3 "$CL" issues render', 'python3 "$CL" issues apply',
                        "tp/<slug>-certify-sweep", HANDOFF, DISPATCH, *SWEEP_ADDS)
    for n in range(1, 8):
        assert f"\n{n}. " in runbook, f"runbook step {n}"
    block = runbook[runbook.index("```bash"):]
    assert block.index(RS_LINE) < block.index(CERT_LINE) < block.index(CL_LINE)


def test_certify_sweep_certifier_probe_out_under_d_and_pr_chokepoint():
    flat = " ".join(_runbook().split())
    probe = flat[flat.index("tp-certifier` probe"):]
    assert "unknown subagent" in probe and "release + reinstall first" in probe  # N12
    assert "--out {D}/certifications/records/" in flat and "temp file beside `--out`" in flat  # N13
    assert 'GHPA="$(python3 "$RS" github_pr_author.py)" || exit 1' in flat  # N7
    assert 'python3 "$GHPA" create --context manual' in flat
    assert "gh pr create" not in flat and "gh pr create" not in _mode_block()


def test_certify_sweep_names_the_pending_entry_by_heading_only():
    import re
    for text in (_runbook(), _mode_block()):
        assert PENDING_PHRASE in text  # the phrase certify_ledger finds the entry by
        assert not re.search(r"\bM\d+\b", text), "no known-issue id in shipped prose (P8)"
        assert not re.search(r"(?:invariant|inv\.?)\s*#\d+|#\d+\b", text), "no invariant cite"


def test_certify_sweep_module_named_only_beside_inventory():
    """P10/N2: the dev-only sweep module is never a shipped surface's entry point."""
    for text in (_skill("tp-implementation-audit"), _read(PROTOCOL)):
        bad = [ln for ln in text.splitlines() if "certify_sweep" in ln and "inventory" not in ln]
        assert not bad, bad


def test_certification_protocol_stays_under_300_lines():
    assert len(_read(PROTOCOL).splitlines()) <= 300
