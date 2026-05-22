"""Emit a worker Agent's candidate.v1 response as four files on disk.

Layout under ``dir``::

    candidates/{candidate_id}/
        branch.txt          # parsed["branch"] + "\n"
        summary.md          # "# Candidate {candidate_id}\n\n{parsed["summary"]}\n"
        test-results.json   # pretty-printed parsed["test_results"]
        telemetry.json      # parsed["telemetry"] ∪ agent_meta ∪ {written_at: <iso-utc>}

Each file is written via a tmp-staging-file in the same directory followed by
``os.replace`` so a mid-write failure cannot leave a partial final file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via tmp file + os.replace.

    The tmp file lives in the same directory as ``path`` so the rename is
    same-filesystem and atomic. If ``os.replace`` raises, the tmp file is
    cleaned up so no partial state is left behind.
    """
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(content)
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_candidate_artifacts(
    parsed: dict, dir: Path, agent_meta: dict
) -> None:
    """Write the four candidate artifacts to ``{dir}/candidates/{candidate_id}/``."""
    candidate_id = parsed["candidate_id"]
    cand_dir = Path(dir) / "candidates" / candidate_id
    cand_dir.mkdir(parents=True, exist_ok=True)

    telemetry = {
        **parsed["telemetry"],
        **agent_meta,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    _atomic_write(cand_dir / "branch.txt", f"{parsed['branch']}\n")
    _atomic_write(
        cand_dir / "summary.md",
        f"# Candidate {candidate_id}\n\n{parsed['summary']}\n",
    )
    _atomic_write(
        cand_dir / "test-results.json",
        json.dumps(parsed["test_results"], indent=2) + "\n",
    )
    _atomic_write(
        cand_dir / "telemetry.json",
        json.dumps(telemetry, indent=2) + "\n",
    )
