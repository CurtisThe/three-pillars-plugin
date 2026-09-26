"""Caller-side check of a certifier's records handoff.

design: audit-pass-does-not-bind (Task 4.3; detailed-design.md §Interfaces [R12]).
The certifier returns `records_file` + `records_sha256` + `record_count`
(certifier-return v1) and never inlines records. The caller copies the file,
then calls `check_handoff` on the copy: any mismatch (`record_count` must be an
`int`, never a bool or float), or a missing file, makes
every claim of that claims file `unverified` with reason `records-handoff`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REASON = "records-handoff"


def check_handoff(env: dict, copied_path: str | Path) -> list[str]:
    """Return [] when the copied bytes match the envelope, else ["records-handoff"]."""
    try:
        if env.get("status") != "pass":
            return [REASON]
        raw = Path(copied_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != env.get("records_sha256"):
            return [REASON]
        records = json.loads(raw.decode("utf-8"))
        count = env.get("record_count")
        if type(count) is not int or not isinstance(records, list) or len(records) != count:
            return [REASON]
    except (OSError, ValueError, AttributeError):
        return [REASON]
    return []
