#!/usr/bin/env python3
"""auto_safe_resolution.py -- the ONE definition of AUTO-SAFE conflict resolution shared by the
merge-back producer (`merge_driver.py`) and the base-sync certificate verifier (Phase 2's
`base_sync_cert.py`). Both sides must execute byte-identical logic, or the carry's soundness
proof (RME condition 5) does not hold.

Re-exports `RESOLVED`/`DEFER` from `resolve.py` via the `Path(__file__)`-relative sys.path shim
into `tp-merge-from-main/scripts/` (precedent: `proof_predicate.py` -> `tp-pr-iterate/scripts`).

Bytes-explicit policy (ONE policy, both sides): blob text is acquired as raw bytes via
subprocess **binary capture, never `text=True`** (no universal-newline translation anywhere on
the path -- CRLF bytes survive verbatim), then decoded strict UTF-8 (`decode_blob_strict`); a
decode failure is the caller's problem to handle (producer defers the file, verifier fails the
link -- neither papers over it). Tempfiles for `git merge-file` are written as raw UTF-8 bytes,
never via a text-mode write.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_MERGE_SCRIPTS = _HERE.parent / "tp-merge-from-main" / "scripts"
if str(_MERGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_MERGE_SCRIPTS))

from resolve import resolve_file, RESOLVED, DEFER  # noqa: E402,F401

# The single definition of AUTO-SAFE -- exactly merge_driver.DEFAULT_LIVING_DOCS' 5 paths.
# merge_driver imports THIS as DEFAULT_LIVING_DOCS once it refactors onto this module; a
# single-definition-guard test pins the equality regardless of which side owns the literal.
AUTO_SAFE_PATHS = frozenset({
    "three-pillars-docs/known_issues.md",
    "three-pillars-docs/known_issues_resolved.md",
    "three-pillars-docs/product_roadmap.md",
    "three-pillars-docs/architecture.md",
    "three-pillars-docs/vision.md",
})


def decode_blob_strict(raw: bytes) -> str:
    """Strict-UTF-8 decode of raw git blob bytes acquired via binary subprocess capture.

    No newline translation ever happens on this path -- the caller captured `raw` without
    `text=True`. Raises `UnicodeDecodeError` on undecodable content; that is deliberate: the
    caller catches it and defers (producer) / fails (verifier), never silently substitutes.
    """
    return raw.decode("utf-8")


def _diff3_conflict_text(*, base: str, ours: str, theirs: str) -> str:
    """Build a `git merge-file --diff3` conflict block from the three versions.

    Lifted from `merge_driver.diff3_text` (parameter order corrected -- see
    `resolve_conflict_bytes`). Bytes-explicit: tempfiles are written as raw UTF-8 bytes (never a
    text-mode write) and the subprocess output is captured binary (never `text=True`), then
    strict-UTF-8 decoded -- so CRLF bytes and encoding survive this step byte-for-byte.
    """
    with tempfile.TemporaryDirectory() as d:
        p_ours, p_base, p_theirs = Path(d) / "ours", Path(d) / "base", Path(d) / "theirs"
        p_ours.write_bytes(ours.encode("utf-8"))
        p_base.write_bytes(base.encode("utf-8"))
        p_theirs.write_bytes(theirs.encode("utf-8"))
        r = subprocess.run(
            ["git", "merge-file", "-p", "--diff3", str(p_ours), str(p_base), str(p_theirs)],
            capture_output=True,
        )
        return decode_blob_strict(r.stdout)


def resolve_conflict_bytes(*, base: str, ours: str, theirs: str) -> tuple[str, str]:
    """The byte-production path BOTH producer (`merge_driver`) and verifier (`base_sync_cert`,
    Phase 2) execute -- the single shared definition RME condition 5 certifies against.

    `git merge-file -p --diff3` over tempfiles -> `resolve.resolve_file` -> `"\\n".join(lines)`
    + trailing-`"\\n"` normalization -> `(file_status, merged_text)`.

    Keyword-only (`*`): this function's parameter order (`base, ours, theirs`) deliberately
    differs from `merge_driver.diff3_text`'s legacy `(ours, base, theirs)`, so ANY positional
    call -- and hence any positional swap -- raises `TypeError` immediately at the call site
    rather than silently miscomputing.
    """
    conflict = _diff3_conflict_text(base=base, ours=ours, theirs=theirs)
    status, lines, _results = resolve_file(conflict)
    merged = "\n".join(lines)
    if not merged.endswith("\n"):
        merged += "\n"
    return status, merged
