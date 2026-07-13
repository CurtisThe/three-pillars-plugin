"""iteration_lane.py — the iteration-vs-gate lane seam (design: fast-lane-worker-wiring).

Names the two test lanes the worker inner loop uses and encodes the boundary between
them in ONE place, so the fast-vs-full decision is not scattered across skill prose:

  * iteration lane (fast, writes NO stamp) — the tight inner loop:
      - granularity="task"  -> `python -m pytest -m unit -n0` (the <10s unit subset)
      - granularity="phase" -> `scripts/ci-local.sh --fast` (xdist pytest + framework-check)
  * gate lane (full, writes the merge-gate stamp) — the pre-push / land boundary:
      the full stamp-writing `scripts/ci-local.sh` (the sole stamp source).

Both lanes are CAPABILITY PROBES against the *target* repo root (never the plugin
checkout): the phase lane probes for `scripts/ci-local.sh --fast`; the task lane probes
for the `unit`-marker infra (pytest.ini `unit:` marker + conftest `_UNIT_MODULES`
allowlist). When a lane's capability is absent (a consumer repo) the seam DEGRADES to
the project-discovered test command (Makefile / pyproject-pytest / package.json). When
NOTHING resolves it emits no command and the CLI exits non-zero — never an empty command
a `tee`-piped caller would swallow as a green no-op.

Guardrail (design B1): the iteration lane can NEVER carry the stamp (`writes_stamp` is
always False) and is NEVER the same command as the gate lane. The full stamp-writing
`scripts/ci-local.sh` is the sole stamp source, forced once by the merge gate at land.

The repo-root default is `project_root.find_project_root()` (cwd git-toplevel) —
explicitly NOT `Path(__file__)`-anchored, so the plugin checkout's own
`scripts/ci-local.sh` can never be probed for a consumer repo.

Stdlib-only. Flat `_shared` module, bare sibling imports.

CLI:
  python3 iteration_lane.py --lane {iteration,gate} [--granularity {task,phase}]
                            [--repo-root PATH]
    prints the resolved command on stdout and exits 0; exits non-zero (stderr
    diagnostic, no stdout line) when no command resolves.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import namedtuple
from pathlib import Path

# Ensure _shared/ is on sys.path for bare sibling imports.
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from project_root import find_project_root  # noqa: E402

LaneResult = namedtuple("LaneResult", ["command", "lane", "writes_stamp", "source"])

# The exact `--fast` guard in scripts/ci-local.sh: `[ "${1:-}" = "--fast" ]`.
_FAST_GUARD_MARKER = '"${1:-}" = "--fast"'

# The task-lane fast command (whole `unit` subset, single-process, <10s inner loop).
_UNIT_COMMAND = "python -m pytest -m unit -n0"

# Emitted when nothing resolves — the CLI turns this into a non-zero exit (no stdout).
_NO_LANE = LaneResult(None, "none", False, "none")


def _resolve_root(repo_root):
    """Normalise repo_root to a Path; default to the cwd git toplevel (NEVER __file__)."""
    if repo_root is None:
        return find_project_root() or Path.cwd()
    return Path(repo_root)


def ci_local_path(repo_root) -> Path:
    """Path to the target repo's `scripts/ci-local.sh` (may or may not exist)."""
    return Path(repo_root) / "scripts" / "ci-local.sh"


def fast_lane_available(repo_root) -> bool:
    """True iff the target repo ships `scripts/ci-local.sh` carrying the `--fast` guard."""
    path = ci_local_path(repo_root)
    try:
        if not path.is_file():
            return False
        return _FAST_GUARD_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def unit_lane_available(repo_root) -> bool:
    """True iff the target repo carries the `unit`-marker infra: pytest.ini registers a
    `unit:` marker AND skills/_shared/conftest.py has the `_UNIT_MODULES` allowlist."""
    root = Path(repo_root)
    ini = root / "pytest.ini"
    conftest = root / "skills" / "_shared" / "conftest.py"
    try:
        if not ini.is_file() or not conftest.is_file():
            return False
        if "unit:" not in ini.read_text(encoding="utf-8"):
            return False
        return "_UNIT_MODULES" in conftest.read_text(encoding="utf-8")
    except OSError:
        return False


def discover_test_command(repo_root):
    """Best-effort project test command — NEVER blindly `pytest`:

      Makefile `test:` target        -> "make test"
      pyproject.toml [tool.pytest…]   -> "python -m pytest"
      package.json `test` script      -> "npm test"
      (none of the above)             -> None

    Probed in that order; returns the first that matches.
    """
    root = Path(repo_root)
    try:
        makefile = root / "Makefile"
        if makefile.is_file() and re.search(
            r"^test\s*:", makefile.read_text(encoding="utf-8"), re.M
        ):
            return "make test"
    except OSError:
        pass
    try:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file() and "[tool.pytest" in pyproject.read_text(encoding="utf-8"):
            return "python -m pytest"
    except OSError:
        pass
    try:
        pkg = root / "package.json"
        if pkg.is_file():
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts") if isinstance(data, dict) else None
            if isinstance(scripts, dict) and scripts.get("test"):
                return "npm test"
    except (OSError, ValueError):
        pass
    return None


def _discovered_lane(repo_root, lane) -> LaneResult:
    """Degrade to the discovered test command (never the stamp source), or _NO_LANE."""
    cmd = discover_test_command(repo_root)
    if cmd is None:
        return _NO_LANE
    return LaneResult(cmd, lane, False, "discovered")


def iteration_command(repo_root=None, *, granularity="phase") -> LaneResult:
    """The fast (no-stamp) inner-loop command for `granularity`, degrading to the
    discovered test command when the fast capability is absent (a consumer repo)."""
    if granularity not in ("task", "phase"):
        # Fail loud rather than fail-open to phase: the seam encodes the lane
        # decision in one place, so a bad granularity is a caller bug, not a
        # silent coercion to the fast lane. (The CLI is argparse-guarded; this
        # guards the module API the tests + callers invoke directly.)
        raise ValueError(
            f"unknown granularity {granularity!r}; expected 'task' or 'phase'"
        )
    root = _resolve_root(repo_root)
    if granularity == "task":
        if unit_lane_available(root):
            return LaneResult(_UNIT_COMMAND, "iteration", False, "unit")
        return _discovered_lane(root, "iteration")
    # granularity == "phase" (default)
    if fast_lane_available(root):
        return LaneResult(f"{ci_local_path(root)} --fast", "iteration", False, "fast")
    return _discovered_lane(root, "iteration")


def gate_command(repo_root=None) -> LaneResult:
    """The full stamp-writing gate command — the sole stamp source. Degrades to the
    discovered test command (`writes_stamp=False`) when `scripts/ci-local.sh` is absent;
    emits no command when nothing resolves."""
    root = _resolve_root(repo_root)
    if fast_lane_available(root):
        return LaneResult(str(ci_local_path(root)), "gate", True, "ci-local")
    return _discovered_lane(root, "gate")


def resolve(lane, *, granularity="phase", repo_root=None) -> LaneResult:
    """Dispatch to gate_command / iteration_command by lane name."""
    if lane == "gate":
        return gate_command(repo_root)
    return iteration_command(repo_root, granularity=granularity)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="iteration_lane — resolve the iteration (fast) vs gate (full) test command",
    )
    parser.add_argument("--lane", choices=("iteration", "gate"), default="iteration")
    parser.add_argument("--granularity", choices=("task", "phase"), default="phase")
    parser.add_argument(
        "--repo-root", default=None, help="target repo root (default: cwd git toplevel)"
    )
    args = parser.parse_args(argv)

    result = resolve(args.lane, granularity=args.granularity, repo_root=args.repo_root)
    if result.command is None:
        print(
            "iteration_lane: no test command resolved — no fast lane and no discoverable "
            "project test command (Makefile / pyproject / package.json). Discover the "
            "command from CLAUDE.md or configure one; do NOT treat this as a green no-op.",
            file=sys.stderr,
        )
        return 1
    print(result.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
