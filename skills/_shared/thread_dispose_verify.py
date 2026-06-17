"""thread_dispose_verify — verify-before-dispose guard (T1.2).

Before resolving a thread, check whether the flagged pattern is still present
in current code. A finding whose code region has already been fixed is disposed
as 'stale_addressed' (honest reply + resolve, no code modification) rather than
re-dispatched to a fix round.

Design constraint: this module is STRICTLY READ-ONLY. It reads files from disk
to check for pattern presence, but NEVER writes, edits, or modifies any file.
There is no fix path here — the guard is a classifier, not a mutator.

Anchor strategy (audit note: low-confidence anchor, carry it):
  The only anchor available on a thread dict is `path` + the comment `body` text
  — NOT a line range. So the region check is implemented as:
  "does current code at `path` still contain the flagged pattern"
  (pattern-presence from the finding body/anchor).

  The pattern is extracted from the finding body by looking for the first
  backtick-quoted token. Falls back to a leading substring of the body.

C1: stdlib only — no `import anthropic`, no claude subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path


# ---------- pattern extraction ----------


_BACKTICK_RE = re.compile(r'`([^`]+)`')


def _extract_pattern(finding: dict) -> str | None:
    """Extract the most relevant pattern substring from a finding's body text.

    Strategy: first backtick-quoted token in the body is the most likely
    literal code pattern. Falls back to leading 60-char substring. Returns
    None if body is empty.
    """
    body = finding.get("body") or ""
    if not body.strip():
        return None
    m = _BACKTICK_RE.search(body)
    if m:
        return m.group(1)
    # Fallback: first 60 non-whitespace chars
    return body.strip()[:60] if body.strip() else None


# ---------- public API ----------


def pattern_still_present(finding: dict, *, base_dir: "Path | None" = None) -> "bool | None":
    """Check if the finding's flagged pattern is still present in the file.

    Returns:
        True   — pattern found in the file (finding still applies)
        False  — pattern NOT found (code has been fixed)
        None   — cannot verify (path missing, file absent, no pattern extractable)

    This function is STRICTLY READ-ONLY — it only reads files, never writes them.

    Args:
        finding:  thread dict (needs 'path' and 'body').
        base_dir: root directory to resolve relative paths. Defaults to cwd.
    """
    path_str = finding.get("path")
    if not path_str:
        return None

    base = Path(base_dir) if base_dir is not None else Path.cwd()
    file_path = base / path_str

    if not file_path.is_file():
        return None

    pattern = _extract_pattern(finding)
    if not pattern:
        return None

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    return pattern in content


def check_before_dispose(finding: dict, *, base_dir: "Path | None" = None) -> str:
    """Classify a finding before disposal.

    Returns:
        'stale_addressed' — the flagged pattern is no longer in the file. The
                            thread should be disposed with an honest stale/addressed
                            reply + resolve. Code must NOT be modified.
        'normal'          — the pattern is still present, OR cannot be verified
                            (missing file, no path, etc.). Proceed with the
                            standard disposition_for disposition.

    This function is STRICTLY READ-ONLY — no files are written or modified
    by this function or any function it calls.

    Design: when the result is 'normal', the caller uses disposition_for (from
    thread_resolver) as the authoritative classification. 'stale_addressed' is
    the one case where the verify-guard overrides the disposition — an honest
    acknowledgement that the code was already fixed before this round ran.
    """
    present = pattern_still_present(finding, base_dir=base_dir)

    if present is False:
        # Pattern gone — already fixed. Dispose as stale/addressed.
        return "stale_addressed"

    # present is True (still flagged) or None (unverifiable) → normal path
    return "normal"
