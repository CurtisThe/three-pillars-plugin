"""finder_harvest — the partial-findings harvest for a capped segment finder.

design: finder-cap-coverage (Task 1.1)

`read_partial` reads the two shipped transport sources and nothing else: the
`agent_caps` sidecar a `put-partial` wrote beside the reply, and the finder's
own transcript (located from the slot's `spawn.json` agent id through
`attempt_scan.locate` over each `child_profile.candidate_dirs` dir), harvested
through `agent_caps.harvest` over its `assistant` records only — no user record
(prompt, commit subjects, rulings) can inject a finding. Neither source has an
ownership check, so both are read as untrusted: a line that is not a JSON object
is skipped and counted in `malformed`, never raised. This module only reads; it
adds no writer to the sidecar. `finder_coverage` re-exports its public names.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, NamedTuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import agent_caps  # noqa: E402
import agent_caps_watch  # noqa: E402

SIDECAR = "sidecar"
TRANSCRIPT = "transcript"


class Partial(NamedTuple):
    findings: list
    progress: list
    covered_files: list
    malformed: int
    sources: list
    transcript_found: bool


def _json_obj(line):
    """json.loads(line) when it parses to a JSON object, else None."""
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _finding_key(obj):
    """(file, start line) — the same dedup key `finder_segments.merge_segment_replies` uses."""
    rng = obj.get("line_range")
    start = rng[0] if isinstance(rng, list) and rng else obj.get("line")
    return (str(obj.get("file")), start if isinstance(start, int) else None)


def _read_sidecar(path):
    """(findings, progress, malformed) from the sidecar, one line at a time."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], [], 0
    findings, progress, malformed = [], [], 0
    for line in text.splitlines():
        obj = _json_obj(line)
        if obj is None:
            if line.strip():
                malformed += 1
            continue
        if isinstance(obj.get("progress"), str):
            progress.append(obj["progress"])
        else:
            findings.append(obj)
    return findings, progress, malformed


def _spawn_agent_id(round_dir, name):
    """The slot's `agent_id` from its `spawn.json`; None with no readable record."""
    try:
        rec = json.loads((Path(round_dir) / name / agent_caps_watch.SPAWN)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec.get("agent_id") if isinstance(rec, dict) else None


def _default_locate(agent_id):
    """The transcript for `agent_id`, searched in every candidate config dir, primary first."""
    import attempt_scan  # noqa: PLC0415 — lazy: only the default seam needs it
    import child_profile  # noqa: PLC0415
    for d in child_profile.candidate_dirs(None):
        found = attempt_scan.locate(agent_id, d)
        if found:
            return found
    return None


def _assistant_text(path):
    """The transcript's `assistant` records as JSONL text; None when unreadable."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    out = [ln for ln in lines if (rec := _json_obj(ln)) and rec.get("type") == "assistant"]
    return "\n".join(out)


def _malformed_markers(text) -> int:
    """Transcript `FINDING` markers whose payload is not a JSON object — the ones
    `agent_caps.harvest` drops silently — counted as malformed, as a bad sidecar line
    is. Scans each assistant text block the way `harvest` does (`raw_decode` at the
    marker), never the JSON-escaped record line itself."""
    bad, dec, mark = 0, json.JSONDecoder(), agent_caps.FINDING_MARK
    for line in text.splitlines():
        msg = (_json_obj(line) or {}).get("message")
        blocks = msg.get("content") if isinstance(msg, dict) else None
        for b in blocks if isinstance(blocks, list) else ():
            body = b.get("text") if isinstance(b, dict) else None
            i = -1
            while isinstance(body, str) and (i := body.find(mark, i + 1)) >= 0:
                try:
                    obj, i = dec.raw_decode(body, i + len(mark))
                except ValueError:
                    bad += 1
                    i += len(mark)
                    continue
                bad += not isinstance(obj, dict)
    return bad


def read_partial(round_dir, entry, *, locate: Callable | None = None) -> Partial:
    """The segment entry's partial findings from the sidecar and its finder's transcript."""
    reply = entry.get("reply_path") or str(Path(round_dir) / (entry.get("name") or "")
                                           / agent_caps_watch.REPLY)
    findings, progress, malformed = _read_sidecar(agent_caps.partial_path(reply))
    sources = [SIDECAR]

    agent_id = _spawn_agent_id(round_dir, entry.get("name") or "")
    transcript = (locate or _default_locate)(agent_id) if agent_id else None
    text = _assistant_text(transcript) if transcript else None
    if text is not None:
        sources.append(TRANSCRIPT)
        malformed += _malformed_markers(text)
        for obj in filter(None, map(_json_obj, agent_caps.harvest(text))):
            if isinstance(obj.get("progress"), str):
                progress.append(obj["progress"])
            else:
                findings.append(obj)
        transcript_found = True
    else:
        transcript_found = False

    seen, deduped = set(), []
    for obj in findings:
        if (key := _finding_key(obj)) not in seen:
            seen.add(key)
            deduped.append(obj)

    # A progress path names a file the finder finished; only one inside `segment.files`
    # counts as covered, and `progress` carries exactly those paths.
    seg_files = set((entry.get("segment") or {}).get("files") or ())
    covered = sorted({p for p in progress if p in seg_files})
    return Partial(deduped, covered, covered, malformed, sources, transcript_found)
