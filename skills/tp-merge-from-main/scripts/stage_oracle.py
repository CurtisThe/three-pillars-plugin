#!/usr/bin/env python3
"""THE GIT INDEX IS THE ORACLE FOR THE TEXT PARSE.

Every silent-drop mechanism found on this branch's resolver side shares ONE cause: `parse_conflict`
reconstructs a conflict region's STRUCTURE by shape-matching git's marker grammar inside content
that can legitimately contain that grammar. A markdown table row of empty cells is `|||||||`. A
setext underline is `=======`. This repo's own docs quote `<<<<<<<` constantly. Every rule built on
text shape is therefore defeasible, and each round has produced a new counterexample to the last
round's rule — S-J1 being the sharpest: a CONTENT line beginning `|||||||` is read as the base
marker, genuine `ours` content lands in `h.base`, and all three `resolve_totality` layers pass,
because `unplaceable()` deliberately excludes `h.base` (sound for a correctly-scanned hunk, fatal
for a misrouted one) and `embedded_marker()` never inspected the marker FIELDS.

There is an unambiguous source of the same structure that no content can imitate: **the merge
index**. Stage 1 is the base blob, stage 2 ours, stage 3 theirs — three separate, marker-free,
authoritative texts. `git merge-file` builds the conflict text out of those three files and nothing
else, so every line on a region's `ours` side IS a line of stage 2, every base-section line a line
of stage 1, every theirs line a line of stage 3. That containment is a property of how the conflict
text was PRODUCED, not of how it looks, which is exactly what a shape rule cannot be.

So this module cross-checks the parse against the stages and reports any disagreement. It is a
VALIDATION GATE, not a re-implementation: it changes no bytes, and `resolve_conflict_bytes` — the
RME-certified byte path both the producer and the Phase-2 certificate verifier run — is untouched.
The caller's only response to a disagreement is to DEFER the file untouched.

**Where it runs, and what happens when the stages are not there.** `merge_driver.resolve_living_doc`
calls it: it has already read stages 1/2/3 to build the conflict text at all. Callers WITHOUT the
three stage texts — `resolve.py`'s CLI on a file of markers, a unit test calling `resolve_file` on
a synthetic blob — cannot run this check, and their only protection remains the in-resolver layers
(`CannotPlace`, `unplaceable`, `embedded_marker`). `base_sync_cert._cond5_resolve` is NOT in that
group: it does read all three stage blobs (from its recomputed merge) before re-running the byte
path, so it could run this gate — it simply does not call it today. What the certifier does get
from the byte path itself is the labelled parse and `auto_safe_resolution.check_conflict_count`
(round 17), which are inside `resolve_conflict_bytes` rather than here. That is stated here rather
than assumed. Within the gate itself the unavailable case IS reachable
(a missing stage is a `None` blob) and it is FAIL-SAFE: a `None` stage is reported as a
disagreement, so the file defers. `merge_driver` already defers add/add and add/delete before
reaching here, so that arm is defence in depth.

**What this gate is actually FOR** (m-K1 — corrected, because it was built for something else).
S-J1's own shape does not need it: real `git merge-file -p --diff3` emits a genuine `||||||| <label>`
line even when the base is empty, that line lands inside the misrouted `h.base`, and the
`embedded_marker` field scan catches it there. The S-J1 wiring test has to SUBSTITUTE synthetic
conflict text to exercise this path at all, which is the honest tell. So the gate's value is not
marker-mimicry: it is that it is the only source of truth in this stack that does not read the
conflict text's shape, and therefore the only layer that can catch a parse bug NOBODY anticipated —
a `_scan_region` off-by-one, a marker-size change, a future refactor that moves a line between
sides. That is a claim about parse bugs in general, not about one adversarial line.

**What it cannot see** (stated, not hidden). Containment is per LINE and MULTISET (S-K3): a
misrouted line is caught unless the stage it landed in holds more copies of that exact text than
the hunk's own side already claims (the charging is per hunk — see below). Set containment was
strictly weaker and blind in the routine case — `| --- |`, a blank line and a repeated table
header all recur constantly in these documents, so any misroute involving one was invisible.
Counting closes that for all but genuine surplus copies. Contiguity and ORDER are still
deliberately NOT checked: `merge-file`'s minimization chooses each region's extent, and while
in practice a region's ours-section is a contiguous run of stage 2, that is an observation about
today's xdiff, not a documented guarantee — a gate enforcing it would defer legitimate merges the
day the observation stops holding. The gate narrows the hole; it does not close it.

**How the copies are counted, and why EACH HUNK is charged separately** (S-L1 — corrected, because
the previous form's safety claim was false). The count was a single budget spent across the whole
file in hunk order, and that made one hunk's verdict depend on another hunk's lines. It could
therefore INVENT a disagreement and blame the wrong region: in a two-hunk file where stage 2 holds
one copy of a line, a MISROUTED hunk 1 that wrongly claims that line spends the only copy and is
reported clean, and hunk 2 — whose parse is exactly right and which legitimately carries the line —
takes the fault. A false fault is not merely noise here: it defers a legitimate merge, and it names
a region that is not the broken one, which is worse than saying nothing.

So each hunk is now charged INDEPENDENTLY against the full stage multiset. A hunk's verdict is a
function of its own lines and the three stage texts, and of nothing else in the file. Three
consequences, all of them meant:

  * **The gate cannot invent a disagreement.** For a faithfully parsed hunk, each side-section is
    drawn by `merge-file` out of that stage, so its lines are a sub-multiset of the whole stage and
    the charge always fits. A fault therefore implies the parse claimed more copies of some line
    than the stage has ever held — which no faithful parse can do. That sentence is now literally
    true of the code; in the shared-budget form it was not.
  * **It can only UNDER-report**, and here is the exact cost: a misroute whose line the stage does
    hold enough copies of goes unseen, including the case where two hunks each claim every copy of
    the same line (jointly impossible, individually fine). The shared budget could see that one
    total overrun and this cannot. That is the safe direction — an unseen misroute leaves the
    resolver's own three layers, a false one costs a correct merge — but it is a real narrowing and
    is stated rather than glossed.
  * Clean (non-conflicted) regions consume stage lines too and are still not charged, so charging
    against the full stage is generous in the same direction as before.

`n` counts HUNKS, not segments: the message names the region a reader can find by counting conflict
markers, which is the only numbering visible in the file.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "_shared"))

from classify import Hunk, classify_file  # noqa: E402
from resolve import RESOLVED, resolve_hunk  # noqa: E402

from auto_safe_resolution import diff3_conflict  # noqa: E402

STAGE_OF_SIDE = (("ours", 2), ("base", 1), ("theirs", 3))


def parse_disagrees_with_index(*, base, ours, theirs, conflict_text: str, labels=None,
                               conflicts: int | None = None) -> list[str]:
    """Every way the PARSE of `conflict_text` contradicts the index stages it was built from.

    `labels` selects the labelled parse `merge-file`'s `-L` labels allow (see `conflict_parse`);
    `conflicts`, when known, is merge-file's own region count, and a parse that found a different
    number of regions is a disagreement too.

    Empty list == the two agree and the mechanical result may be accepted. Non-empty == the parse
    put a line on a side the index says it did not come from, so the region was cut in the wrong
    place and the caller must DEFER.

    Only hunks the resolver actually RESOLVED are checked. A deferred hunk is re-emitted verbatim
    by `resolve._deferred`, so a mis-cut there loses nothing and deferring it twice would only cost
    legitimate merges. `resolve_hunk` is a pure function of the hunk, so calling it here is a
    read-only second opinion, not a second resolution. It can check MORE hunks than the byte path
    finally keeps (`resolve.resolve_file` defers some per-hunk resolutions for a file-level
    reason), and an extra check can only add a fault, i.e. a deferral.
    """
    stages = {1: base, 2: ours, 3: theirs}
    missing = sorted(s for s, text in stages.items() if text is None)
    if missing:
        return [f"index stage(s) {missing} unavailable — the parse cannot be cross-checked, "
                f"so it is not trusted"]
    have = {s: Counter(text.split("\n")) for s, text in stages.items()}
    faults: list[str] = []
    segments = classify_file(conflict_text, labels=labels).segments
    found = sum(isinstance(seg, Hunk) for seg in segments)
    if conflicts is not None and found != conflicts:
        faults.append(f"git merge-file wrote {conflicts} conflict region(s) but the parse found "
                      f"{found}")
    n = 0
    for seg in segments:
        if not isinstance(seg, Hunk):
            continue
        n += 1                                          # HUNKS, not segments: see the module note
        if resolve_hunk(seg).status != RESOLVED:
            continue
        claimed: dict[int, Counter] = {1: Counter(), 2: Counter(), 3: Counter()}
        for side, stage in STAGE_OF_SIDE:
            for line in getattr(seg, side):
                claimed[stage][line] += 1               # charged against the FULL stage, per hunk
                if claimed[stage][line] <= have[stage][line]:
                    continue
                had = have[stage][line]
                short = ("does not contain that line" if not had
                         else f"contains only {had} copy/copies of that line and this hunk claims "
                              f"{claimed[stage][line]}")
                faults.append(f"hunk {n} ({seg.label}): the parse put {line!r} on the {side} "
                              f"side, but index stage {stage} {short}")
    return faults


def index_disagreement(*, base, ours, theirs) -> str | None:
    """One sentence naming the first disagreement between the parse and the index, or None.

    Rebuilds the diff3 conflict from the same three stage blobs the byte path uses, and parses it
    LABELLED with this call's own labels. `git merge-file` is deterministic on identical inputs, so
    this is the text `resolve_conflict_bytes_detail` parsed except for the nonce on marker lines —
    re-derived rather than threaded through, so the RME-certified byte path keeps its exact
    signature and behaviour.
    """
    if base is None or ours is None or theirs is None:
        return "index stages unavailable — the parse cannot be cross-checked"
    d = diff3_conflict(base=base, ours=ours, theirs=theirs)
    faults = parse_disagrees_with_index(base=base, ours=ours, theirs=theirs,
                                        conflict_text=d.text, labels=d.labels,
                                        conflicts=d.conflicts)
    if not faults:
        return None
    extra = f" (+{len(faults) - 1} more)" if len(faults) > 1 else ""
    return faults[0] + extra
