"""finder_digest — what a reader or a finder sees of a segmented round's coverage.

design: finder-cap-coverage (Tasks 1.2, 1.6, 1.8, 1.12)

The text the coverage work adds to prompts and digests: the segment finder's
partial-delivery note (`partial_note`), the digest label suffix (`label_suffix`),
the round's one coverage line (`coverage_line`) and the Opus check's
uncovered-files block (`check_scope`). `finder_coverage` re-exports every public
name, so callers keep reading them from there. This module imports
`finder_coverage`, `finder_round` and `finder_segments` only inside functions:
`finder_coverage` imports this module at module level.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

UNCOPEN = "<!-- uncovered-files -->"
UNCCLOSE = "<!-- /uncovered-files -->"
COVERAGE_OK = 80  # under this, the line names how many files only the Opus check saw


def _scope_block(uncovered) -> str:
    return (UNCOPEN + "\nFiles no Strata finder covered — review every one yourself, "
            "as you would an `unparseable` segment's files:\n"
            + "".join(f"- {p}\n" for p in uncovered) + UNCCLOSE)


def check_scope(manifest, uncovered) -> dict:
    """The manifest with the `opus-check` prompt's uncovered-files block rewritten.

    An old block is removed first, so re-running the merge replaces it, never
    duplicates it; with nothing uncovered the prompt is byte-unchanged. At any
    coverage (design §Constraints: the check's scope only grows)."""
    import finder_round  # noqa: PLC0415 — lazy: the two modules import each other

    out = copy.deepcopy(manifest)
    block = _scope_block(sorted(uncovered)) if uncovered else ""
    for e in out.get("angles") or ():
        if e.get("name") != finder_round.CHECK_NAME:
            continue
        prompt = e.get("prompt") or ""
        i = prompt.find(UNCOPEN)
        if i != -1:
            j = prompt.find(UNCCLOSE, i)
            end = j + len(UNCCLOSE) if j != -1 else len(prompt)
            prompt = prompt[:i] + prompt[end:]
        if block:
            prompt = prompt.rstrip() + "\n\n" + block + "\n"
        e["prompt"] = prompt
    return out


def coverage_line(round_dir) -> str:
    """The round's one coverage line (Behavior 3), read from the merged file.

    No path prints a percent without a readable `segments-merged.json`: a round with
    no segment entries is `n/a (not segmented)`, one whose merge never ran or whose
    merged file cannot be read is `unknown`, never a default percent."""
    import finder_coverage  # noqa: PLC0415 — lazy: finder_coverage imports this module
    import finder_segments  # noqa: PLC0415 — lazy: the two modules import each other

    rd = Path(round_dir)
    try:
        manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "coverage unknown (merge not run)"
    if not finder_coverage.segment_entries(manifest):
        return "coverage n/a (not segmented)"
    merged = rd / "opus-check" / finder_segments.MERGED
    if not merged.exists():
        return "coverage unknown (merge not run)"
    try:
        out = json.loads(merged.read_text(encoding="utf-8"))
        cov, unc = out["coverage"], out["uncovered_files"]
        pct = int(cov["percent"])
    except (OSError, ValueError, KeyError, TypeError):
        return "coverage unknown (merge unreadable)"
    if pct >= COVERAGE_OK:
        return f"coverage {pct}%"
    return f"coverage {pct}%: {len(unc)} files reviewed only by the Opus check"


def label_suffix(entry) -> str:
    """The digest label's suffix for one manifest entry (Behaviors 2, 3, 5); `""` for none.

    A skip reads by its reason: a budget skip names its file count, a retried parent its two
    halves (never the backend-absent catch-all). Otherwise a telemetry outcome `capped` or
    `partial` reads ahead of the parse-lift mark's older `unparseable` suffix."""
    import finder_coverage  # noqa: PLC0415 — lazy: finder_coverage imports this module

    skipped, tel = entry.get("skipped"), entry.get("telemetry") or {}
    files = (entry.get("segment") or {}).get("files") or ()
    if skipped == "out-of-scope":
        return " [not run: out of scope]"
    if skipped == "segment-budget":
        return f" [skipped: segment budget{f', {len(files)} files' if files else ''}]"
    if skipped == finder_coverage.RETRIED:
        return f" [retried: split into {entry['name']}a, {entry['name']}b]"
    if skipped:
        return " [skipped: no local backend]"
    if tel.get("outcome") == "capped":
        return " [capped: re-covered by opus-check]"
    if tel.get("outcome") == "partial":
        return f" [partial: {len(tel.get('covered_files') or ())} of {len(files)} files]"
    if entry.get("unparseable") == "re-covered-by-opus-check":
        return " [unparseable: re-covered by opus-check]"
    return ""


def partial_note(angle) -> str:
    """The one prompt paragraph a segment finder gains (Task 1.2); "" without a `segment`.

    The shipped transport is reachable from every finder — `angles.build_prompt` names its
    `reply_path` — but nothing told a finder to use it, so a segment finder stopped at the cap
    left nothing to harvest. The note asks for the inline `FINDING` line `agent_caps.harvest`
    reads, in the finder's own message text (no tool turn, where the wall clock is the scarce
    thing), plus one progress line per finished file. They are a fallback for a stop, never the
    delivery, which stays the one `put` command. The marker is never followed by a brace here, so
    the prompt itself — which a finder quotes back into its transcript — harvests as nothing.
    """
    if not angle.get("segment"):
        return ""
    return ("Partial delivery if you are stopped: as soon as you confirm a finding, write it "
            "into your own message text as one line — the word FINDING, one space, then that "
            "finding's JSON object — with no tool call, and after you finish each file write one "
            'more such line whose object is {"progress": "<path>"} for that file. Those lines '
            "count only as a fallback when you are stopped before you deliver; they are never "
            "the delivery. Your final reply, sent through the `put` command above, must still "
            "hold every finding.")
