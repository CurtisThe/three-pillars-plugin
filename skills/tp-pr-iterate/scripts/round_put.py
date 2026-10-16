"""round_put — `round_scratch.py put`: script-mediated reply / envelope delivery.

design: review-proof-out-of-tree (Task 1.4)

Sub-agents never file-write under the proof root: in a linked worktree it sits in
the git-dir, outside their cwd. An angle confirmer or the round tail pipes its reply
or envelope through Bash into `put` (the quoted-heredoc command its prompt names),
and `put` computes the target ITSELF — `R/<angle>/reply.md` or `R/tail/envelope.json`
— never trusting the manifest's `reply_path`. It refuses (exit 2, one JSON line on
stdout, nothing written): an unsafe slot name, a missing or unreadable manifest, a
slot the manifest does not list, a skipped angle, a missing or symlinked slot dir,
a symlinked target, and any target resolving outside R.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import round_scratch as rs  # noqa: E402


class PutRefused(ValueError):
    """`put` will not write this slot."""


def target_for(round_dir, slot: str) -> Path:
    """The one file `slot` may write in round dir `round_dir`, or `PutRefused`."""
    slot = str(slot)
    if not rs._SAFE_NAME.match(slot):
        raise PutRefused(f"unsafe slot name {slot!r}")
    rd = Path(round_dir).absolute()
    try:
        manifest = json.loads((rd / rs.MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PutRefused(f"{rd}: no readable {rs.MANIFEST} ({exc})") from exc
    if slot == rs.TAIL:
        sub, leaf = rs.TAIL, rs.ENVELOPE
    else:
        listed = [e for e in (manifest.get("angles") or ())
                  if isinstance(e, dict) and e.get("name") == slot]
        if not listed:
            raise PutRefused(f"slot {slot!r} is not an angle in {rs.MANIFEST}")
        if listed[0].get("skipped"):
            raise PutRefused(f"angle {slot!r} is skipped ({listed[0]['skipped']})")
        sub, leaf = slot, rs.REPLY
    slot_dir = rd / sub
    target = slot_dir / leaf
    if slot_dir.is_symlink() or target.is_symlink():
        raise PutRefused(f"{target}: symlinked slot dir or target")
    if not slot_dir.is_dir():
        raise PutRefused(f"{slot_dir}: slot dir missing")
    if rd.resolve() not in target.resolve().parents:
        raise PutRefused(f"{target} escapes {rd}")
    return target


def put(round_dir, slot: str, data: bytes) -> Path:
    """Write `data` to `slot`'s file (never through a symlink). → the target."""
    target = target_for(round_dir, slot)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(target, flags, 0o644), "wb") as fh:
        fh.write(data)
    return target


def cmd_put(a) -> int:
    """CLI: stdin → the slot file. Exit 2 + one JSON line on refusal."""
    try:
        target = put(a.round_dir, a.slot, sys.stdin.buffer.read())
    except (PutRefused, OSError) as exc:
        print(json.dumps(dict(refused=str(exc), slot=a.slot)))
        return 2
    print(json.dumps(dict(put=str(target), slot=a.slot)))
    return 0
