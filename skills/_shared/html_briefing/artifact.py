"""html_briefing/artifact.py — per-round artifact path + git staging.

Public API:
  briefing_artifact_path(decisions_dir, round_id) -> Path
  stage_briefing(repo, path)

The HTML briefing for each promote round is committed beside decisions.md
as an auditable artifact.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# briefing_artifact_path
# ---------------------------------------------------------------------------

def briefing_artifact_path(decisions_dir: Path, round_id: str) -> Path:
    """Return the canonical path for the HTML briefing artifact.

    The artifact is placed beside decisions.md (same directory) and named
    deterministically: ``confirm-<round_id>.html``.

    Args:
        decisions_dir: Directory that contains (or will contain) decisions.md.
        round_id:      A round identifier string (e.g. ``"r1"``, ``"round42"``).

    Returns:
        Path to the HTML artifact (not created by this function).
    """
    return Path(decisions_dir) / f"confirm-{round_id}.html"


# ---------------------------------------------------------------------------
# stage_briefing
# ---------------------------------------------------------------------------

def stage_briefing(repo: Path, path: Path) -> None:
    """Stage the HTML briefing artifact in the git repo.

    Runs ``git add <rel_path>`` where rel_path is the path of the artifact
    relative to the repo root.  Only that file is staged — no other files
    (including decisions.md, lock.json, or gate files) are touched.

    Args:
        repo: Path to the git repository root.
        path: Absolute (or repo-relative) path to the HTML artifact.

    Raises:
        subprocess.CalledProcessError: if git add fails.
    """
    repo = Path(repo)
    path = Path(path)

    # Compute repo-relative path for a scoped `git add`
    try:
        rel = path.relative_to(repo)
    except ValueError:
        # path is already relative — use as-is
        rel = path

    subprocess.run(  # nosec B603 B607
        ["git", "-C", str(repo), "add", str(rel)],
        check=True,
        capture_output=True,
    )
