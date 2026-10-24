"""Assemble the synthesizer subagent prompt for the orchestrator's audit fan-out.

Pure string/dict assembly — NO file I/O, NO dispatch. This is the unit-testable
seam (detailed-design §4). It embeds artifact PATHS (the synthesizer subagent
reads them itself, preserving context isolation) and serializes the Round-1
verdict dicts + Round-2 rebuttal dicts (including each challenged_finding_indices,
F4) into the prompt text the synthesizer weighs.

The synthesizer is dispatched as a read-only `tp-readonly-auditor` subagent (Slot 8:
`tp-impl-auditor`; NO worktree isolation, F8) and emits the audit-return.v1 envelope.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# Slots 4/6 carry the state-space map-check angle; its findings are tagged so the
# orchestrator can exempt them from retry-with-advice (they go to the operator).
MAP_CHECK_SLOTS = frozenset({"design-audit", "plan-audit"})
MAP_CHECK_CATEGORY = "map-check"
# Every finding's `severity` keys the audit-retry lows rule (run-throughput Part C:
# `audit_retry_rules.lows_only` — all non-map-check findings `minor` → one patch, one re-audit).
SEVERITIES = ("critical", "medium", "minor")
# review-convergence 9.2: the three fields beside `severity` the orchestrator folds
# downstream (a finding's locus + the run evidence behind it). One constant so the
# brief and its test never drift.
FIELD_REQUEST = ("Each finding also carries `file` (repo-relative path), `line` (an int, "
                 "or null when no single line applies) and `run_failure` (the command or "
                 "test plus the observed failure; an empty string when none) beside its "
                 "`severity` (`" + "|".join(SEVERITIES) + "`).")

# review-convergence 9.2: the Security block caps its rendered surfaces; the rest
# are counted, never dropped silently.
SECURITY_SURFACE_LIMIT = 40

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

# member_engine: "opus" (default, prompt unchanged) or "local" (members ran on local
# models; the synthesizer adds its own gap pass and returns escape_dispositions[]).
MEMBER_ENGINES = ("opus", "local")
DISPOSITIONS = ("kept", "dropped", "downgraded", "opus-added")
GAP_PASS_BRIEF = [
    "",
    "## Gap pass (members ran on local models)",
    "The members above ran on a local model. Before you emit the envelope, do "
    "your own pass over the artifacts under audit and add any real defect the "
    "members missed.",
    "Also return `escape_dispositions[]` alongside the audit-return.v1 fields "
    "(the envelope is otherwise unchanged): one entry per member finding, plus "
    "one per finding you add. Each item is `{from, disposition, defect_class?, "
    "served?}`: `from` names the member (or `opus` for your own addition), "
    "`disposition` is one of `" + "|".join(DISPOSITIONS) + "` (`opus-added` for "
    "findings you add), `defect_class` is an optional short class label.",
    "Where this prompt marks a member as Sonnet-served because the local slot "
    "was busy, copy `served: \"sonnet-busy\"` onto every item from that member.",
]


def _shared_path() -> str:
    """`skills/_shared` on sys.path (lazily, so importing this module stays cheap)."""
    shared = str(Path(__file__).resolve().parents[2] / "_shared")
    if shared not in sys.path:
        sys.path.insert(0, shared)
    return shared


def _known_item_lines(design_dir) -> list[str]:
    """The `## Known items (per-phase check)` block, or [] when nothing is carried.

    review-convergence 9.2: the per-phase checks already found and carried these, so
    the synthesizer must not re-raise one as a new find.
    """
    _shared_path()
    import phase_check

    items = phase_check.known_items(design_dir)
    if not items:
        return []
    lines = [
        "## Known items (per-phase check)",
        "The per-phase checks found these and carried them forward, so they are "
        "KNOWN, not new finds: do not re-raise one or count it against the verdict "
        "unless it is still open in the code.",
    ]
    for item in items:
        line = (f"- [phase {item.get('phase')}] {item.get('id')} "
                f"{item.get('file')}:{item.get('line_range')} — "
                f"{item.get('summary')} ({item.get('status')})")
        if item.get("status") == "disputed" and item.get("reason"):
            line += f" — disputed: {item['reason']}"
        lines.append(line)
    lines.append("")
    return lines


def _security_lines(repo, code_input, run_git) -> list[str]:
    """The `## Security` block for a code-bearing (Slot-8) dispatch.

    Names the repo's own brief (or the shipped checklist), the shared security bar,
    the finding tag, and the trust-boundary surfaces of the whole design diff. A
    failed git read fails CLOSED: every touched file is in scope.
    """
    _shared_path()
    import trust_boundary

    lines = [
        "## Security",
        f"Brief: read `{trust_boundary.brief_path(repo)}` yourself.",
        trust_boundary.SECURITY_BAR,
        'Mark the lens: security findings carry `category: "security"` exactly.',
    ]
    try:
        found = trust_boundary.surfaces_for_range(
            repo, code_input["base"], code_input["candidate"],
            three_dot=True, run_git=run_git)
    except trust_boundary.TrustBoundaryError as exc:
        lines.append(f"- surfaces unavailable ({exc}): treat every touched file "
                     "as in scope")
        lines.append("")
        return lines
    if not found:
        lines.append("- none flagged")
    else:
        for surface in found[:SECURITY_SURFACE_LIMIT]:
            lines.append(f"- `{surface['surface']}` {surface['path']}:{surface['line']}")
        if len(found) > SECURITY_SURFACE_LIMIT:
            lines.append(f"- … ({len(found) - SECURITY_SURFACE_LIMIT} more)")
    lines.append("")
    return lines


def build_synth_prompt(
    artifact_paths: list[str],
    round1: list[dict],
    round2: list[dict] | None,
    slot: str,
    code_input: dict | None = None,
    member_engine: str = "opus",
    *,
    busy_members=(),
    capped_members=(),
    design_dir=None,
    repo=None,
    run_git=None,
) -> str:
    """Assemble the synthesizer subagent prompt.

    round2 None ⇒ --fast-audit (Round-2 skipped). Returns prompt text; raises
    ValueError on empty round1 or member-set mismatch between round1 and round2.

    ``capped_members`` names council members whose reply was cut off at the hard
    limit (on either cheap engine); the prompt marks them so the synthesizer
    copies ``capped: true`` onto their ``escape_dispositions[]`` items.

    ``design_dir`` (review-convergence 9.2) is the in-flight design directory: its
    ``phase-check-carry.json`` items render as a ``## Known items (per-phase check)``
    block so the synthesizer treats them as carried, not re-discovered. ``None`` or an
    empty carry ⇒ no block.

    ``repo`` + ``run_git`` (review-convergence 9.2) add the ``## Security`` block to a
    code-bearing dispatch: the repo's security brief (its ``SECURITY.md``, else the
    shipped checklist), the shared security bar, and the trust-boundary surfaces of
    ``base...candidate``. ``run_git`` is the test seam handed to ``trust_boundary``.
    Either of ``repo`` / ``code_input`` being ``None`` ⇒ no block.

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
    if member_engine not in MEMBER_ENGINES:
        raise ValueError(f"unknown member_engine {member_engine!r}; expected one of {MEMBER_ENGINES}")
    busy_members = list(busy_members)
    capped_members = list(capped_members)
    if busy_members and member_engine != "local":
        raise ValueError("busy_members requires member_engine='local'")
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
    agent = "tp-impl-auditor" if slot == "impl-audit" else "tp-readonly-auditor"
    lines.append(
        f"You are a read-only `{agent}` subagent. Read the artifact paths "
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

    if repo is not None and code_input is not None:
        lines.extend(_security_lines(repo, code_input, run_git))

    if design_dir is not None:
        lines.extend(_known_item_lines(design_dir))

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
    lines.append(
        f"`severity` (`{'|'.join(SEVERITIES)}`) is REQUIRED on every finding, independent of "
        "its `confidence`: `critical` blocks the artifact's purpose, `medium` is a real defect "
        "a run or user would hit, `minor` is polish. A finding without it takes the full "
        "retry loop (the orchestrator's lows rule treats it as not minor)."
    )
    lines.append(FIELD_REQUEST)
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

    if member_engine == "local":
        lines.extend(GAP_PASS_BRIEF)
        if busy_members:
            lines.append("Sonnet-served (slot busy): " + ", ".join(busy_members))

    if capped_members:
        lines.append("Capped at the hard limit: " + ", ".join(capped_members)
                     + ". Copy `capped: true` onto every escape_dispositions[] item from these members.")

    return "\n".join(lines)
