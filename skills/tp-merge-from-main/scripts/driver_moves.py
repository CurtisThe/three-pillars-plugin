"""driver_moves.py — wires `archive_moves.verify_with_moves` into the merge driver.

Exists only to keep `merge_driver.py` under the file-size cap (basesync-autoresolve-coverage,
Task 3.3); the archive-move rule itself lives in `archive_moves.py`.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import archive_moves  # noqa: E402


def verify_living(repo, path: str, base: str, ours: str, theirs: str, merged: str, *,
                  mechanical_applied: bool):
    return archive_moves.verify_with_moves(
        base, ours, theirs, merged, mechanical_applied=mechanical_applied,
        archives=archive_moves.driver_archives(repo, path))
