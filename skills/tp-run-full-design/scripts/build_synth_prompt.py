"""Assemble the synthesizer subagent prompt for the orchestrator's audit fan-out.

Pure string/dict assembly — NO file I/O, NO dispatch. This is the unit-testable
seam (detailed-design §4). It embeds artifact PATHS (the synthesizer subagent
reads them itself, preserving context isolation) and serializes the Round-1
verdict dicts + Round-2 rebuttal dicts (including each challenged_finding_indices,
F4) into the prompt text the synthesizer weighs.

The synthesizer is dispatched as a general-purpose, read-only subagent (NO
isolation="worktree", F8) and emits the existing audit-return.v1 envelope.
"""

from __future__ import annotations

import json


# Slots 4/6 carry the state-space map-check angle; its findings are tagged so the
# orchestrator can exempt them from retry-with-advice (they go to the operator).
MAP_CHECK_SLOTS = frozenset({"design-audit", "plan-audit"})
MAP_CHECK_CATEGORY = "map-check"

# Slots 4/8 return guard claims for Step 2b (skills/_shared/certification-protocol.md):
# the synthesizer names claims only; the tp-certifier agent authors every RED/GREEN.
GUARD_CLAIM_SLOTS = frozenset({"design-audit", "impl-audit"})
# The claim keys the brief asks for: audit-return.v1.json `guard_claims.items.properties`
# (a test keeps the two equal). `subjects` is the certifier's allowlist.
GUARD_CLAIM_KEYS = ("id", "guard", "property", "parameters", "subjects")
# Wording the Step 2b fold counts as certifying (cert_phrase_scan [R8]): affirmative,
# negated, or about a guard not yet written. Quoted in the brief so the synthesizer
# never writes one untagged; a test keeps each example a real scan hit.
CERT_PHRASE_EXAMPLES = ("the test binds", "the check is non-vacuous", "no test catches X",
                        "the new guard will catch it")


def build_synth_prompt(
    artifact_paths: list[str],
    round1: list[dict],
    round2: list[dict] | None,
    slot: str,
    code_input: dict | None = None,
) -> str:
    """Assemble the synthesizer subagent prompt.

    round2 None ⇒ --fast-audit (Round-2 skipped). Returns prompt text; raises
    ValueError on empty round1 or member-set mismatch between round1 and round2.

    ``code_input`` is the Slot-8-only (impl-audit) code addition: when not
    ``None`` it is ``{"base": <ref>, "candidate": <ref>, "touched_files":
    [<path>, ...]}`` carrying the three-dot ``tp/{slug}...origin/candidate/{slug}
    /single`` ref pair (the ``origin/`` prefix lives on the candidate ref) + the
    diff's name-only touched-file paths. The prompt names the REFS and PATHS only
    — never the diff body; the synthesizer re-derives any line it needs via its
    own ``git diff {base}...{candidate}`` / ``git show {candidate}:<file>``. When
    ``code_input is None`` (every Slot-4/6 dispatch) no code section is added, but a
    ``GUARD_CLAIM_SLOTS`` slot (Slot 4 ``design-audit``) still gets its guard-claims line.
    """
    if not round1:
        raise ValueError("round1 must be a non-empty list of Round-1 verdict dicts")

    if round2 is not None:
        r1_members = {r.get("member") for r in round1}
        r2_members = {r.get("member") for r in round2}
        if r1_members != r2_members:
            raise ValueError(
                "member set mismatch between round1 and round2: "
                f"{sorted(m for m in r1_members if m)} vs "
                f"{sorted(m for m in r2_members if m)}"
            )

    lines: list[str] = []
    lines.append(
        f"You are the SYNTHESIZER for the `{slot}` audit slot of the autonomous "
        "tp-run-full-design orchestrator."
    )
    lines.append(
        "You are a read-only, general-purpose subagent. Read the artifact paths "
        "below yourself; weigh the council deliberation; emit ONE fenced ```json "
        "block carrying the `audit-return.v1` envelope "
        "(schema tp-run-full-design/audit-return/v1)."
    )
    lines.append("")

    lines.append("## Artifacts under audit (read these paths yourself)")
    for p in artifact_paths:
        lines.append(f"- {p}")
    lines.append("")

    if code_input is not None:
        base = code_input["base"]
        candidate = code_input["candidate"]
        touched_files = code_input.get("touched_files", [])
        lines.append("## Candidate code under audit (read it yourself via git)")
        lines.append(
            "This is the `impl-audit` (Slot 8) code addition — judge the candidate "
            "code AGAINST the artifact paths above. You are given the git REFS, not "
            "the diff body."
        )
        lines.append(f"- base ref: `{base}`")
        lines.append(f"- candidate ref: `{candidate}`")
        if touched_files:
            lines.append("- touched files (name-only; read each yourself):")
            for f in touched_files:
                lines.append(f"  - `{f}`")
        else:
            lines.append(
                "- touched files: NONE — the candidate diff is **empty**. An empty "
                "candidate diff is itself an audit signal (nothing was changed "
                "relative to the base), not an error."
            )
        lines.append(
            f"Run `git diff {base}...{candidate}` (three-dot) and "
            f"`git show {candidate}:<file>` yourself to read the candidate code; "
            "do NOT expect the diff inlined."
        )
        lines.append("")

    lines.append("## Round 1 — independent verdicts")
    lines.append(
        "Each finding already carries its per-finding `confidence`; carry it "
        "forward VERBATIM into the audit-return findings[] (do not invent values)."
    )
    for r in round1:
        lines.append(f"### {r.get('member', '<unknown>')}")
        lines.append("```json")
        lines.append(json.dumps(r))
        lines.append("```")
    lines.append("")

    if round2 is not None:
        lines.append("## Round 2 — cross-examination rebuttals")
        lines.append(
            "Honor each `challenged_finding_indices`: a Round-1 finding whose index "
            "appears in a peer's Round-2 challenged_finding_indices is annotated "
            "weakened (or its confidence lowered) when the counter_argument argues "
            "against it; findings no peer challenged are annotated upheld. Round-1 "
            "findings remain the authoritative finding-of-record."
        )
        for r in round2:
            lines.append(f"### {r.get('member', '<unknown>')}")
            lines.append("```json")
            lines.append(json.dumps(r))
            lines.append("```")
        lines.append("")

    lines.append(
        "Merge + deduplicate the Round-1 findings, compute the overall `verdict` "
        "from the confidence/verdict mix exactly as the standalone audit skill "
        "would, and emit the audit-return.v1 envelope."
    )
    if slot in MAP_CHECK_SLOTS:
        lines.append(
            "Map-check findings (the state-space Check-mode angle: a better locus or "
            f"alternative dismissed without evidence) MUST carry `category: \"{MAP_CHECK_CATEGORY}\"` "
            "exactly, whatever their confidence (keep a member's tag; add it if a member "
            "omitted it). They question design.md's own framing, so the orchestrator never "
            "turns them into retry advice; it escalates them straight to the operator."
        )
    if slot in GUARD_CLAIM_SLOTS:
        lines.append(
            "Guard claims: where a finding or verdict rests on a guard (test, check, lint, "
            "gate, script) *enforcing* a property, return it in `guard_claims[]` as "
            "`{" + ", ".join(GUARD_CLAIM_KEYS) + "}` only (`guard` = `path[::node]`, "
            "`property` one line, `subjects` the repo-relative files the guard checks: the only "
            "files the certifier may perturb, so a claim without them certifies `unverified`; "
            "no RED/GREEN inputs, no status: an independent certifier authors and runs "
            "those). Set `guards_certified` to the `## Guards certified` body: one line per claim "
            "tagged `[cert:<id>]`, or exactly `No guard claims.` alone. Never write a "
            "certifying phrase unless the same field carries `[cert:<id>]` for a returned "
            "claim (the tag alone binds; the field need not name the guard path); an untagged "
            "one counts as `unverified`. "
            "Negated wording and wording about a guard not yet written count too: "
            + ", ".join(f'"{e}"' for e in CERT_PHRASE_EXAMPLES)
            + " are all certifying phrases. Describe such a guard without that wording."
        )

    return "\n".join(lines)
