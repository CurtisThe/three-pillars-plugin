"""test_cheap_tier_slot_sites.py — the script-checked slot sites (plan Phase 5-6).

design: cheap-tier-offload (Tasks 5.2, 5.3, 6.4; slots doc §Phase 5-6, §Site wiring).

- `runbook`: `tp-post-merge` step 5 runs `teardown.py` as code, only after the merge
  gate, the seat verdict (with its STOP cases) and steps a and b; `tp-merge-from-main`
  step 8 forwards the flag on its `/tp-post-merge` chain.
- `base_sync_splice`: `tp-merge-from-main` step 4 shows a drafter's splice only when
  `zero_drop` is VERIFIED, never applies it, and leaves step 4's own text as it was.
- `pr_fix_reproducer` / `classifier_judge`: `tp-pr-fix` steps 5 and 3, fenced before today's
  fix generation and classifier call; `cheap-tier.md` §Reach states the flag's two limits.

Imports `test_cheap_tier_sites.py`'s helpers; that file holds the guard itself.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from test_cheap_tier_sites import ROOT, STUB_RE, argument_hint, find_violations  # noqa: E402
import skill_text  # noqa: E402

POST_MERGE = ROOT / "skills" / "tp-post-merge" / "SKILL.md"
FROM_MAIN = ROOT / "skills" / "tp-merge-from-main" / "SKILL.md"
HINT = "[--cheap-tier[=ab]]"
# Step 4 as it now stands outside the stub: the Resolution-boundary clause plus task 7.2's
# `base-sync-hunk` sentence; the text outside the stub never changes.
STEP4 = ("4. **Surface what the human must finish.** From the report's `partially_resolved` "
         "+ `deferred` lists, tell the user exactly which files still carry conflict markers "
         "and which hunks remain (e.g. \"`product_roadmap.md`: preamble + current-focus need "
         "you\"). **Never stage or commit a file that still contains conflict markers** — the "
         "driver enforces this; do not work around it. Each deferred or partially-resolved "
         "living-doc file outside the pillar docs (`PILLAR_DOCS` in "
         "`skills/_shared/finalizer_ruling.py`) is one `base-sync-hunk` question "
         "per `skills/_shared/escalation.md`, naming the file and the deferred hunk's heading or "
         "first changed line, raised after the cheap-tier proposal below with the proposal's "
         "scratch path in its `context` (or `none verified`) and the options `apply-proposal` "
         "(only when a zero-drop VERIFIED proposal exists) and `leave-for-human`; Fable rules it "
         "first. On `resolved` with `apply-proposal` re-run `python3 \"$TP_ROOT\"/skills/_shared/"
         "cheap_oracle_run.py check --slot base_sync_splice --artifact <A.json> --ctx <C.json>` "
         "on the proposal (must give `accept`; its `zero_drop` check also refuses any line not in "
         "ours + theirs + base), copy the proposal over the file (never "
         "hand-edit marker lines, never write text from the ruling), run `verify.py <ours> "
         "<theirs> <resolved> --base <base>` (must exit 0) and `file_size_guard.py` on it, stage "
         "it, and list it as `fable-applied (ruling <id>)` in the step-7 merge note. With "
         "`leave-for-human` (returned as `escalate`) or on `escalate` (including `low` "
         "confidence), the hunk waits for the human and the card carries Fable's recommendation. "
         "With no zero-drop VERIFIED proposal, skip Fable; with none, or when an `apply-proposal` "
         "re-check is not `accept` or exits non-zero, run `python3 \"$TP_ROOT\"/skills/_shared/"
         "finalizer_cli.py escalate --stop <stop> --reason no-proposal --decisions "
         "<d>/decisions.md --scope <slug>` so the park gets a ruling file and an "
         "`awaiting-operator` card, and the hunk waits for the human. A pillar-doc hunk skips Fable: raise its question and run `python3 "
         "\"$TP_ROOT\"/skills/_shared/finalizer_cli.py escalate --stop <stop> --reason pillar-doc "
         "--decisions <d>/decisions.md --scope <slug>` so it still gets a ruling file and an "
         "`awaiting-operator` card, and it waits for the human. "
         "Offer (f): if a deferred conflicted path is a lockfile, run `python3 "
         "\"$TP_ROOT\"/skills/tp-merge-from-main/scripts/generator_catalog.py detect --repo . --only "
         "<deferred paths> --json` and follow offer (f) in `skills/_shared/consumer-offers.md` "
         "(interactive: show the match, accept or decline; `--auto`: log a suggestion, write "
         "nothing). "
         "Wait for the "
         "human to finish the deferred hunks (an agent reports and stops here; see the "
         "Resolution boundary) before continuing (in `--dry-run`, stop here and "
         "`git merge --abort`).\n\n")
SPLICE_STUB_RE = re.compile(r"\n *<!-- cheap-tier:base_sync_splice -->.*?<!-- /cheap-tier -->\n",
                            re.S)
TEARDOWN_CALL = ('"$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --slug {name} '
                 "--base {base} --root <resolved seat>")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _stub(text: str, slot: str):
    found = [m for m in STUB_RE.finditer(text) if m.group(1) == slot]
    assert len(found) == 1, f"expected one cheap-tier:{slot} stub, found {len(found)}"
    return found[0]


def _line_offset(text: str, prefix: str) -> int:
    """Offset of the one line that starts (after indentation) with `prefix`."""
    hits = [i for i, line in _lines(text) if line.lstrip().startswith(prefix)]
    assert len(hits) == 1, f"expected one line starting with {prefix!r}, found {len(hits)}"
    return hits[0]


def _lines(text: str):
    offset = 0
    for line in text.splitlines(keepends=True):
        yield offset, line
        offset += len(line)


def test_post_merge_site():
    text = _text(POST_MERGE)
    stub = _stub(text, "runbook")
    # inside step 5: after the gate, the seat verdicts (STOP cases) and steps a, b
    step5 = _line_offset(text, "5. **Teardown**")
    for stop in ("- **`core-bare-flip`**", "- **`missing-seat`"):
        assert step5 < _line_offset(text, stop) < stub.start(), stop
    assert _line_offset(text, "b. `git pull --ff-only") < stub.start()
    assert stub.end() < _line_offset(text, "c. **Detect and remove sibling worktree**")
    body = _flat(stub.group(2))
    assert TEARDOWN_CALL in body
    assert "cheap_tier_cli.py spec --slot runbook" in body and "--cheap-tier <mode>" in body
    assert '"$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot runbook' in body
    assert "`exit_code`" in body and "`verify_argv`" in body
    assert "steps c–h" in body  # escalate means today's steps
    assert "gc_candidate_branches.py --apply" in body  # f and g stay on the reaper
    assert '"$TP_ROOT"/skills/_shared/cheap_ab.py alt-arm --slot runbook' in body
    assert "alt:runbook" in body
    # the opus arm records a verdict too: today's steps, then the same residue check
    # through the exit_code oracle (PR #191 r1), and alt-arm runs once per teardown
    assert '"$TP_ROOT"/skills/tp-post-merge/scripts/teardown.py --check --slug {name}' in body
    assert "the `opus` arm runs today's steps c–h, then" in body
    assert "--oracle" in body and "once per teardown" in body
    assert "an artifact file holding `{}`" in body  # exit_code reads no artifact keys
    # the row lands in one named tracked file on {base}; step 6 never commits, so it reverts
    # that one file and the seat is never left dirty (impl-audit #7). The loss is accepted:
    # the row is always reverted and lost, and telemetry never gates (plan deviation 4).
    row = "three-pillars-docs/completed-tp-designs/{name}/dispatch-telemetry.ndjson"
    assert "--design-dir three-pillars-docs/completed-tp-designs/{name}" in body
    assert "step 6 reverts that one file" in body
    assert "always reverted and lost" in body and "telemetry never gates" in body
    step6 = _flat(text[_line_offset(text, "6. **Doc-reconcile"):
                       _line_offset(text, "6.5. **Post-merge tripwires")])
    assert f"git add {row}" not in step6 and "git commit" not in step6
    assert f"`{row}`" in step6 and "never commits" in step6
    assert "`git restore --staged --worktree --` it" in step6  # L150: drops a staged row too


def test_post_merge_flag_reaches_the_site():
    assert HINT in argument_hint(POST_MERGE)
    assert HINT in argument_hint(FROM_MAIN)
    text = _text(FROM_MAIN)
    step8 = _flat(text[_line_offset(text, "8. **Post-merge auto-chain**"):text.index("\n## Rules")])
    assert "`/tp-post-merge {design-name} --cheap-tier`, bare" in step8  # always-on: bare flag (one-cheap-engine 3.6)


def test_teardown_script_exists_and_the_guard_is_clean():
    assert (ROOT / "skills" / "tp-post-merge" / "scripts" / "teardown.py").is_file()
    assert find_violations(ROOT) == []


def test_splice_site():
    text = _text(FROM_MAIN)
    stub = _stub(text, "base_sync_splice")
    step4, step5 = _line_offset(text, "4. **Surface"), _line_offset(text, "5. **Re-run")
    # before the wait: the proposal is computed while index stages :2/:3 still exist,
    # and a --dry-run (which stops at the wait) still shows it (impl-audit #8)
    wait = _line_offset(text, "Wait for the human to finish the deferred hunks")
    assert step4 < stub.start() < stub.end() < wait < step5
    # the text outside the stub never changes (only its line breaks around the stub)
    assert _flat(SPLICE_STUB_RE.sub(" ", text[step4:step5], count=1)) == _flat(STEP4)
    body = _flat(stub.group(2))
    assert "cheap_tier_cli.py spec --slot base_sync_splice" in body
    assert "--cheap-tier <mode>" in body
    assert "subagent_type=<spec.agent_ref>, model=<spec.model>" in body
    assert "`resolved`" in body and "`zero_drop`" in body
    assert '"$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot base_sync_splice' in body
    # VERIFIED is shown as not applied at draft time; only a `resolved` ruling applies it (step 4); anything else is dropped and logged
    assert "Only on `accept`" in body
    assert "`cheap-tier proposal (zero-drop VERIFIED, not applied)`" in body
    assert "Anything else drops the proposal" in body
    assert "Record each attempt per the dispatch doc" in body
    assert "applied only by a `resolved` `apply-proposal` ruling" in body and "stage" in body and "commit" in body
    assert "`partially_resolved` or `deferred`" in body  # only living-doc files
    assert "before the wait below" in body and "`--dry-run` too" in body


# --- Task 6.4: the tp-pr-fix sites + the reach note --------------------------------

PR_FIX = ROOT / "skills" / "tp-pr-fix" / "SKILL.md"
CHEAP_MD = skill_text.skill_paths("tp-run-full-design")[0].parent / "cheap-tier.md"
CLASSIFIER_CALL = 'model=model_policy.model_for("classifier", config),'


def _between(text: str, start: str, end: str) -> tuple[int, int]:
    lo = text.index(start)
    return lo, text.index(end, lo)


def test_pr_fix_sites():
    text = _text(PR_FIX)
    assert HINT in argument_hint(PR_FIX)
    # classifier_judge: in step 3, before (never inside) today's classifier call block
    stub = _stub(text, "classifier_judge")
    lo, hi = _between(text, "### 3. Borderline classification", "### 4.")
    call = text.index(CLASSIFIER_CALL)
    assert lo < stub.start() < stub.end() < text.rindex("```", lo, call) < call < hi
    body = _flat(stub.group(2))
    for needle in ("cheap_tier_cli.py spec --slot classifier_judge", "--cheap-tier <mode>",
                   "subagent_type=<spec.agent_ref>, model=<spec.model>", "`classifier_schema`",
                   '"$TP_ROOT"/skills/_shared/cheap_oracle_run.py check --slot classifier_judge',
                   "`response`", "`borderline_ids`", "Only on `accept`",
                   'today\'s `model_for("classifier")` call', "Record each attempt"):
        assert needle in body, needle
    # pr_fix_reproducer: at fix generation, before today's generation prose
    stub = _stub(text, "pr_fix_reproducer")
    lo, hi = _between(text, "### 5. Generate the fix", "### 6.")
    assert lo < stub.start() < stub.end() < text.index("For each structural+gated comment") < hi
    body = _flat(stub.group(2))
    for needle in ("cheap_tier_cli.py spec --slot pr_fix_reproducer", "--cheap-tier <mode>",
                   '"$TP_ROOT"/skills/tp-pr-fix/scripts/cheap_fix_cli.py scratch',
                   '"$TP_ROOT"/skills/tp-pr-fix/scripts/cheap_fix_cli.py adopt',
                   "subagent_type=<spec.agent_ref>, model=<spec.model>", "`reproducer_fixed`",
                   "`eligible: false`", 'today\'s `model_for("fix")` generation',
                   "never `ci.gate_command`",
                   "Nothing here commits or pushes", "Record each attempt"):
        assert needle in body, needle
    assert find_violations(ROOT) == []


def test_reach_note():
    text = _text(CHEAP_MD)
    reach = _flat(text[text.index("## Reach"):])
    for needle in ("`tp-pr-fix` takes the flag only from its own argument",
                   "`tp-pr-iterate`", "#188",
                   "the forward reaches the loop's fixes only as the round tail's `CHEAP_TIER:` line, a log line",
                   "classifier-rung.json", "`route`", "No site passes a route today",
                   "today's Sonnet `model_for(\"classifier\")` stays in effect until both the "
                   "verdict file and a route hold",
                   "its `pr_fix_reproducer` stub is inert in-loop and standalone"):
        assert needle in reach, needle
    assert "cheap_tier_cli.py spec" not in text
