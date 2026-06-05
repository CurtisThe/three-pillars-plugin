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


def build_synth_prompt(
    artifact_paths: list[str],
    round1: list[dict],
    round2: list[dict] | None,
    slot: str,
) -> str:
    """Assemble the synthesizer subagent prompt.

    round2 None ⇒ --fast-audit (Round-2 skipped). Returns prompt text; raises
    ValueError on empty round1 or member-set mismatch between round1 and round2.
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

    return "\n".join(lines)
