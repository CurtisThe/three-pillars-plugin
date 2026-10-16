"""Scaffold selection for cheap-tier review prep loops — cheap-tier-review-prep (Tasks 5.2, 5.3).

Pick the findings `finding_class.coerce` left *blocking* without a reproducer
(`schema_note == "blocking-without-reproducer"`) — the claims the loop refused
to block on for lack of a runnable repro — and surface a stable `finding_key`
so a later adoption step can match the same finding across the merge path.

Stdlib only; one responsibility per function (5.3 adds the scratch wrappers,
write_note and the adopted_reproducers reader on top of these two).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import round_scratch  # noqa: E402
from finding_class import is_sentinel  # noqa: E402
from review_merge import merge_codereview_angles  # noqa: E402

SCAFFOLD_CAP = 5
TARGET_NOTE = "blocking-without-reproducer"
SCAFFOLDS = ("prep", "scaffolds")
INDEX = "index.json"
ORIGIN = "scaffold-adopted"
_KEY_RE = re.compile(r"^[0-9a-f]{16}$")


def _range(f: dict) -> tuple:
    rng = f.get("line_range")
    if isinstance(rng, (list, tuple)) and len(rng) >= 2:
        return rng[0], rng[1]
    return 0, 0


def finding_key(f: dict) -> str:
    """`sha256("file|start|end|summary")[:16]` — stable across merge paths.

    Uses `file`/`line_range`/`summary` exactly as `finding_class` / `review_merge`
    preserve them in a normalized finding, so the same claim gets the same key
    whether it arrives raw or through `merge_codereview_angles`.
    """
    start, end = _range(f)
    digest = hashlib.sha256(
        f"{f.get('file', '')}|{start}|{end}|{f.get('summary', '')}".encode("utf-8")
    )
    return digest.hexdigest()[:16]


def _log_cap(round_dir: Path, capped: list) -> None:
    """Append one `scaffold-cap` line per over-cap target to the round log."""
    if not capped:
        return
    manifest = json.loads((round_dir / "angles.json").read_text(encoding="utf-8"))
    log_path = Path(manifest["paths"]["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        for item in capped:
            start = _range(item["finding"])[0]
            fh.write(f"[cheap-tier] scaffold-cap: {item['key']} "
                     f"{item['finding'].get('file', '')}:{start}\n")


def _picked(round_dir) -> list:
    """All blocking-claims-without-reproducer for this round, uncapped, no log write.

    Reads the round's angle replies via `round_scratch.read_replies`, merges them
    the way `reproduce.run_cli` does (`review_merge.merge_codereview_angles`), and
    keeps the non-sentinel findings carrying `schema_note == TARGET_NOTE`.
    """
    round_dir = Path(round_dir)
    merged = merge_codereview_angles(round_scratch.read_replies(round_dir))
    return [
        {"key": finding_key(f), "finding": f}
        for f in merged
        if not is_sentinel(f) and f.get("schema_note") == TARGET_NOTE
    ]


def targets(round_dir, log=True) -> list:
    """The round's scaffold targets, first `SCAFFOLD_CAP`, in reply order.

    With `log` (the `scaffold-targets` listing), anything past the cap is logged
    to the round's `log_path` as `scaffold-cap`; a per-unit lookup passes
    `log=False` so the cap lines are written once per round, not once per `open`.
    """
    round_dir = Path(round_dir)
    picked = _picked(round_dir)
    kept, capped = picked[:SCAFFOLD_CAP], picked[SCAFFOLD_CAP:]
    if log:
        _log_cap(round_dir, capped)
    return kept


def _cheap_fix():
    """Import `cheap_fix` lazily (plan-audit #4): it pulls in `reproduce` at module
    top, so importing it here — inside the wrapper — keeps `review_prep_scaffold`
    importable on the cheap side without the reproduce chain."""
    fix_dir = str(_HERE.parent.parent / "tp-pr-fix" / "scripts")
    if fix_dir not in sys.path:
        sys.path.insert(0, fix_dir)
    import cheap_fix
    return cheap_fix


def scratch(repo, head) -> Path:
    """A detached worktree of `repo` at `head`, under a `review-prep-*` owner dir —
    `cheap_fix.scratch` with its review-prep prefix (see cheap-fix.md Scratch)."""
    return _cheap_fix().scratch(repo, head, prefix="review-prep")


def discard(path) -> None:
    """Remove a review-prep scratch worktree and its owner dir (idempotent)."""
    _cheap_fix().discard(path)


def write_note(round_dir, key, artifact, head) -> Path:
    """Record an accepted scaffold for a real target of `round_dir`.

    `artifact` is the accepted drafter output `{"source": str, "test_name": str}`.
    Writes `prep/scaffolds/<key>.json` (key, head, accepted, source, test_name,
    finding) and upserts `prep/scaffolds/index.json` (one entry per key:
    key, file, summary, note). Raises `ValueError` on a bad artifact, a key that
    is not 16 hex, or a key that is not one of the round's targets.
    """
    if not _KEY_RE.match(str(key)):
        raise ValueError(f"not a scaffold key: {key!r}")
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be {'source': str, 'test_name': str}")
    for field in ("source", "test_name"):
        value = artifact.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"artifact {field!r} must be a non-empty str")
    pick = next((p for p in _picked(round_dir) if p["key"] == key), None)
    if pick is None:
        raise ValueError(f"not a target: {key}")

    round_dir = Path(round_dir)
    scaffolds = round_dir.joinpath(*SCAFFOLDS)
    note_path = scaffolds / f"{key}.json"
    note = {"key": key, "head": str(head), "accepted": True,
            "source": artifact["source"], "test_name": artifact["test_name"],
            "finding": pick["finding"]}
    scaffolds.mkdir(parents=True, exist_ok=True)
    note_path.write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8")

    index_path = scaffolds / INDEX
    index = []
    try:
        loaded = json.loads(index_path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            index = [e for e in loaded
                     if not (isinstance(e, dict) and e.get("key") == key)]
    except (OSError, ValueError):
        pass  # absent or unparseable: start fresh
    index.append({"key": key, "file": pick["finding"].get("file", ""),
                  "summary": pick["finding"].get("summary", ""),
                  "note": str(note_path)})
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return note_path


def adopted_reproducers(round_dir, adopted_path, head) -> tuple:
    """Map the tail's adopted scaffold keys onto test reproducers.

    `adopted_path` is `tail/adopted.json`: `[{"key": "<16 hex>"}, ...]`. A key
    counts only when its note exists at `prep/scaffolds/<key>.json` for this
    `head`, is `accepted: true` and carries a non-empty `source`. Anything else
    yields one refusal line `scaffold-adopt-refused: <key>: <reason>` (complete
    log lines — Task 5.5 writes them verbatim). A missing/malformed adopted file
    is one refusal on `*`. Returns `(out, refusals)`.
    """
    malformed = "scaffold-adopt-refused: *: malformed adopted.json"
    try:
        entries = json.loads(Path(adopted_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, [malformed]
    if not isinstance(entries, list) or any(
            not isinstance(e, dict) or not isinstance(e.get("key"), str)
            for e in entries):
        return {}, [malformed]

    round_dir = Path(round_dir)
    out: dict = {}
    refusals: list = []
    for entry in entries:
        key = entry["key"]
        if key in out:
            continue
        if not _KEY_RE.match(key):
            refusals.append(f"scaffold-adopt-refused: {key}: unknown key")
            continue
        note_path = round_dir.joinpath(*SCAFFOLDS, f"{key}.json")
        try:
            note = json.loads(note_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            refusals.append(f"scaffold-adopt-refused: {key}: unknown key")
            continue
        if not isinstance(note, dict) or note.get("head") != head:
            refusals.append(f"scaffold-adopt-refused: {key}: stale head")
        elif note.get("accepted") is not True:
            refusals.append(f"scaffold-adopt-refused: {key}: not accepted")
        elif not isinstance(note.get("source"), str) or not note["source"]:
            refusals.append(f"scaffold-adopt-refused: {key}: note has no source")
        else:
            out[key] = {"kind": "test", "source": note["source"]}
    return out, refusals
