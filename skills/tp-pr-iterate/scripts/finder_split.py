"""finder_split — the one re-plan of a capped segment as two half-size segments.

design: finder-cap-coverage (Tasks 1.9, 1.10)

`split_segment` cuts a segment at file, then hunk, boundaries (pure); `retry`
writes the two half entries into the manifest, each with its own slot, paths and
prompt, under the parent's `fraction` (Behavior 2). `finder_retry` re-exports
both and keeps the CLI; this module imports `finder_retry` only inside `retry`.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import agent_caps_watch  # noqa: E402
import angle_tree  # noqa: E402
import finder_round  # noqa: E402
import finder_segments  # noqa: E402
import run_scratch  # noqa: E402


def _halve_hunks(path: str, hunks: list[dict]) -> tuple[dict, dict] | None:
    """Two halves of one file's hunk list, each carrying its new-side `ranges`."""
    if len(hunks) < 2:
        return None
    mid = len(hunks) // 2
    out = []
    for part in (hunks[:mid], hunks[mid:]):
        out.append({"files": [path], "lines": sum(h["lines"] for h in part),
                    "ranges": [part[0]["start"], part[-1]["end"]]})
    return out[0], out[1]


def split_segment(seg: dict, file_rows: list[dict]) -> tuple[dict, dict] | None:
    """Cut one segment into two halves: at file boundaries, or at hunk boundaries.

    `file_rows` is `finder_segments.parse_diff` output; rows for files outside
    `seg["files"]` are ignored. Several files split greedily, largest first, so the
    halves come out balanced by changed lines and each stays `{files, lines, ranges:
    None}`. One file with two or more hunks splits its hunk list instead, each half
    carrying the new-side `ranges` of its own hunks. One file with one hunk cannot be
    halved: `None`. A segment with its own `ranges` (a hunk-range piece of a file over
    the limit) splits only the hunks inside that range, never the whole file's: fewer
    than two there is `None`. Pure — no manifest, no filesystem.
    """
    rows = [r for r in file_rows or () if r.get("path") in set(seg.get("files") or ())]
    if len(rows) == 1:
        hunks = rows[0].get("hunks") or []
        rng = seg.get("ranges")
        if rng:
            hunks = [h for h in hunks if rng[0] <= h["start"] and h["end"] <= rng[1]]
        return _halve_hunks(rows[0]["path"], hunks)
    if len(rows) < 2:
        return None
    halves = [{"files": [], "lines": 0, "ranges": None}, {"files": [], "lines": 0, "ranges": None}]
    for r in sorted(rows, key=lambda r: -r["lines"]):
        put = halves[0] if halves[0]["lines"] <= halves[1]["lines"] else halves[1]
        put["files"].append(r["path"])
        put["lines"] += r["lines"]
    return halves[0], halves[1]


_WHOLE = "The whole change, so you can name a cross-segment concern without seeing it all: "
_SEG_TAIL = ". The Opus check merges the segments and owns cross-segment judgement."
_SEG_BLOCK = re.compile(r"SEGMENT \S+ of \d+:.*?owns cross-segment judgement\.", re.S)


def _rebuild_prompt(prompt, old, new, half_seg, *, n, base, head):
    """The parent's prompt re-pointed at one half: slot, paths, and the SEGMENT block."""
    m = _SEG_BLOCK.search(prompt)
    if m:
        block = m.group(0)
        whole = ""
        if _WHOLE in block and _SEG_TAIL in block:
            whole = block.split(_WHOLE, 1)[1].split(_SEG_TAIL, 1)[0]
        rebuilt = finder_segments.segment_prompt("", half_seg, n=n, base=base, head=head,
                                                 whole=whole).lstrip("\n")
        prompt = prompt[:m.start()] + rebuilt + prompt[m.end():]
    for old_s, new_s in ((old["tree_dir"], new["tree_dir"]),
                         (old["exec_dir"], new["exec_dir"]),
                         (old["reply_path"], new["reply_path"])):
        if old_s:
            prompt = prompt.replace(str(old_s), str(new_s))
    prompt = re.sub(r"(?m)^TP_SCRATCH: .*$", f"TP_SCRATCH: {Path(new['reply_path']).parent}",
                    prompt)
    return prompt.replace(f"--slot {old['name']} ", f"--slot {new['name']} ")


def _half_entry(parent, half, suffix, round_dir, *, repo, head):
    """One half's manifest entry: its own slot, reply path, exec dir, tree dir, prompt."""
    seg = parent.get("segment") or {}
    name = f"{parent['name']}{suffix}"
    hseg = {"angle": seg.get("angle"), "id": f"{seg.get('id')}{suffix}", "of": seg.get("of"),
            "files": list(half["files"]), "fraction": seg.get("fraction"),
            "lines": half["lines"], "ranges": half["ranges"],
            "max_segments": seg.get("max_segments"), "retry_of": parent["name"]}
    e = copy.deepcopy(parent)
    e["name"] = name
    e["segment"] = hseg
    e["attempt"] = 2
    e["rung"] = parent.get("rung")
    e.pop("skipped", None)
    e.pop("unparseable", None)
    e.pop("telemetry", None)
    (round_dir / name).mkdir(parents=True, exist_ok=True)
    e["reply_path"] = str(round_dir / name / agent_caps_watch.REPLY)
    e["exec_dir"] = tempfile.mkdtemp(prefix=f"tp-angle-{name}-",
                                     dir=run_scratch.outside_tmpdir())
    rev = angle_tree.head_commit(repo, head)
    e["tree_dir"] = angle_tree.make_tree(repo, rev, e["exec_dir"]) if rev else None
    return e


def _is_capped(entry, round_dir) -> bool:
    """A capped entry: its telemetry outcome is `capped`, or, never settled, its reply
    is missing, empty or placeholder-only (what `put-capped` writes)."""
    import finder_retry as fr  # noqa: PLC0415 — lazy: finder_retry imports this module
    import review_merge  # noqa: PLC0415

    outcome = (entry.get("telemetry") or {}).get("outcome")
    if outcome:
        return outcome == "capped"
    text = fr._reply_text(entry, round_dir)
    if not text.strip():
        return True
    findings, ok = review_merge.parse_codereview_result(text)
    return ok and fr._placeholder_only(findings)


def retry(round_dir, angle, *, repo=".", diff_text=None) -> dict:
    """Re-plan one capped first-attempt segment as two halves, once (Behavior 2).

    Returns `{"next"}`: `retry` (two half entries appended, the parent `skipped:
    "retried"`), `sonnet` (an unsplittable segment takes `settle`'s shared Sonnet
    transition) or `uncovered` (the per-angle budget is spent: the entry is marked
    exactly as `settle`'s `uncovered` does). An entry that is not an unmarked
    `attempt` 1 on Strata, or is not capped (`_is_capped`), or the Opus check, or an
    unknown angle: exit 2 — no third attempt, and a delivered or partial reply is
    never thrown away. `diff_text` is a test seam; the CLI reads the diff from `repo`.
    """
    import finder_retry as fr  # noqa: PLC0415 — lazy: finder_retry imports this module

    round_dir = Path(round_dir)
    manifest = fr._read_manifest(round_dir)
    if isinstance(manifest, int):
        return {"next": None, "exit": manifest}
    if angle == finder_round.CHECK_NAME:
        return {"next": None, "exit": fr._fail("refusing to retry the Opus check")}
    entry = fr._find(manifest, angle)
    if entry is None:
        return {"next": None, "exit": fr._fail(f"unknown angle {angle!r}")}
    seg = entry.get("segment")
    if not seg:
        return {"next": None, "exit": fr._fail(f"angle {angle!r} is not a segment entry")}
    if (entry.get("attempt") or 1) != 1 or str(entry.get("rung") or "").startswith("sonnet") \
            or entry.get("unparseable") or entry.get("skipped"):
        return {"next": None, "exit": fr._fail(
            f"angle {angle!r}: only an unmarked first attempt on Strata is retried")}
    if not _is_capped(entry, round_dir):
        return {"next": None, "exit": fr._fail(
            f"angle {angle!r}: only a capped entry is retried (settle it first)")}
    diff = diff_text
    if diff is None:
        diff = finder_segments.whole_diff(repo, manifest.get("base"), manifest.get("head"))
    halves = split_segment(seg, finder_segments.parse_diff(diff or ""))
    a_name = f"{angle}a"
    needed = 2 if halves else 1
    if fr.retry_used(manifest, seg.get("angle")) + needed > fr.budget(manifest, seg.get("angle")):
        old = entry.get("telemetry") or {}
        fr._mark_uncovered(entry)
        entry["telemetry"] = fr._telemetry(entry, seg, "capped", [], None, None, old)
        finder_round._atomic_write(round_dir / fr.MANIFEST, json.dumps(manifest, indent=2) + "\n")
        return {"next": "uncovered"}
    if not halves:
        fr._to_sonnet(entry, fr._slot_dir(round_dir, entry))
        finder_round._atomic_write(round_dir / fr.MANIFEST, json.dumps(manifest, indent=2) + "\n")
        return {"next": "sonnet"}
    base, head = manifest.get("base"), manifest.get("head")
    made = []
    for half, suffix in zip(halves, ("a", "b")):
        e = _half_entry(entry, half, suffix, round_dir, repo=repo, head=head)
        e["prompt"] = _rebuild_prompt(e["prompt"], entry, e, e["segment"],
                                      n=seg.get("of") or 1, base=base, head=head)
        manifest["angles"].append(e)
        made.append(e["name"])
    old = entry.get("telemetry") or {}
    entry["skipped"] = "retried"
    entry["telemetry"] = fr._telemetry(entry, seg, "retried", [], None, None, old)
    finder_round._atomic_write(round_dir / fr.MANIFEST, json.dumps(manifest, indent=2) + "\n")
    return {"next": "retry", "halves": made}
