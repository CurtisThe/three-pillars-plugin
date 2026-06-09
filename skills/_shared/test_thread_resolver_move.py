"""Whole-tree move-completeness test for thread_resolver (Phase 0, Task 0.1).

Asserts:
  (a) No PRODUCTION file in the repo tree (excluding this test file itself and
      design documents) contains the old path reference from the old script
      location under tp-pr-iterate (grep-verified, whole-tree).
  (b) `import thread_resolver` resolves to a module whose __file__ lives under
      `skills/_shared/`, not under the old location.

Both assertions FAIL before the move (the path string still appears in SKILL.md;
the module is still under tp-pr-iterate/scripts/).
Both PASS once tasks 0.2–0.4 land.

This greps the `skills/` tree (where code lives), not a named-file check — any future
code importer of the old path is caught. It excludes this test file itself. Living docs
under `three-pillars-docs/` are out of scope here (archived design docs legitimately
retain the old path as historical record).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# _shared/ is beside this file; resolve repo root via parents
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent  # skills/_shared/.. = skills/ .. = repo root

# The old path segment to search for in production code (skills/ and SKILL.md files).
# Exclude this file (test_thread_resolver_move.py) and design docs (decisions.md)
# from the grep since they legitimately mention the old path for documentary purposes.
_OLD_PATH_SEGMENT = "tp-pr-iterate/scripts/thread_resolver"


def test_no_stale_thread_resolver_path_references() -> None:
    """grep over the skills/ subtree returns no match for the old path segment.

    Scoped to skills/ only (the production code), not design docs or completed
    archives. Excludes this test file itself (.py exclusion would over-exclude).
    A match in SKILL.md, test_pr_iterate_skill_md.py, or any skills/*.py = stale.
    """
    skills_dir = REPO_ROOT / "skills"
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--exclude-dir=.git",
            "--exclude=test_thread_resolver_move.py",
            _OLD_PATH_SEGMENT,
            str(skills_dir),
        ],
        capture_output=True,
        text=True,
    )
    # grep exit codes: 0 = matches found, 1 = no matches (the green case), 2+ = error.
    # Guard so a grep error (missing grep / unreadable path) is NOT read as "no stale refs".
    assert result.returncode in (0, 1), (
        f"grep errored (exit {result.returncode}); cannot trust the completeness check:\n{result.stderr}"
    )
    matches = result.stdout.strip()
    assert matches == "", (
        f"Stale path references to old location found in skills/:\n{matches}"
    )


def test_thread_resolver_imports_from_shared() -> None:
    """import thread_resolver resolves to skills/_shared/thread_resolver.py.

    The module's __file__ must be under skills/_shared/, not under
    tp-pr-iterate/scripts/.
    """
    shared_dir = HERE
    if str(shared_dir) not in sys.path:
        sys.path.insert(0, str(shared_dir))

    import importlib
    import importlib.util

    spec = importlib.util.find_spec("thread_resolver")
    assert spec is not None, "thread_resolver module not found in sys.path"
    assert spec.origin is not None, "thread_resolver has no __file__ (is it a namespace package?)"

    module_path = Path(spec.origin).resolve()
    expected_parent = shared_dir.resolve()
    assert module_path.parent == expected_parent, (
        f"thread_resolver resolved to {module_path} — expected it under {expected_parent}"
    )
