"""iteration_lane.py — the iteration-vs-gate lane seam (design: fast-lane-worker-wiring).

Names the two test lanes the worker inner loop uses and encodes the boundary between
them in ONE place, so the fast-vs-full decision is not scattered across skill prose:

  * iteration lane (fast, writes NO stamp) — the tight inner loop:
      - granularity="task"  -> `python -m pytest -m unit -n0` (the <10s unit subset)
      - granularity="phase" -> `scripts/ci-local.sh --fast` in the three-pillars dev repo
  * gate lane (full, writes the merge-gate stamp) — the pre-push / land boundary:
      a declared `ci.gate_command`, run and stamped by `ci_gate_run.py`; else the
      stamp-writing `scripts/ci-local.sh` in the three-pillars dev repo; else the
      discovered test command (no stamp).

Both lanes are CAPABILITY PROBES against the *target* repo root (never the plugin
checkout): the phase lane probes for `scripts/ci-local.sh --fast` (dev-repo only); the
task lane probes
for the `unit`-marker infra (pytest.ini `unit:` marker + conftest `_UNIT_MODULES`
allowlist). When a lane's capability is absent (a consumer repo) the seam DEGRADES to
the project-discovered test command (Makefile / pyproject-pytest / package.json). When
NOTHING resolves it emits no command and the CLI exits non-zero — never an empty command
a `tee`-piped caller would swallow as a green no-op.

Guardrail (design B1): the iteration lane can NEVER carry the stamp (`writes_stamp` is
always False) and is NEVER the same command as the gate lane. The stamp-writing gate
lane is the sole stamp source; the `/tp-merge` `ci_local_stamp` predicate reads it at
land, and only when `ci.gate_command` is declared.

The repo-root default is `project_root.find_project_root()` (cwd git-toplevel) —
explicitly NOT `Path(__file__)`-anchored, so the plugin checkout's own
`scripts/ci-local.sh` (dev-repo only) can never be probed for a consumer repo.

Stdlib-only. Flat `_shared` module, bare sibling imports.

CLI:
  python3 iteration_lane.py --lane {iteration,gate} [--granularity {task,phase}]
                            [--repo-root PATH] [--exec]
    prints the resolved command on stdout and exits 0; exits non-zero (stderr
    diagnostic, no stdout line) when no command resolves.
    --exec: RUN the resolved command through the shell (`shell=True`, in the repo
    root — the same semantics `ci_gate_run.py` gives a declared gate command) and exit
    with its status, so a recorded compound command (`cd app && make test`) behaves
    the same in every lane. Callers use this instead of word-splitting `$CMD`. When
    nothing resolves it runs nothing and exits EXEC_NO_LANE_EXIT (78, sysexits
    EX_CONFIG) — distinct from a failing test run.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

# Ensure _shared/ is on sys.path for bare sibling imports.
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from project_root import find_project_root  # noqa: E402
from repo_config_load import load_repo_config  # noqa: E402

LaneResult = namedtuple("LaneResult", ["command", "lane", "writes_stamp", "source"])

# The exact `--fast` guard in scripts/ci-local.sh: `[ "${1:-}" = "--fast" ]`.
_FAST_GUARD_MARKER = '"${1:-}" = "--fast"'

# The task-lane fast command (whole `unit` subset, single-process, <10s inner loop).
_UNIT_COMMAND = "python -m pytest -m unit -n0"

# Emitted when nothing resolves — the CLI turns this into a non-zero exit (no stdout).
_NO_LANE = LaneResult(None, "none", False, "none")

# `--exec` exit status when no command resolves (sysexits EX_CONFIG): distinct from the
# command's own failure status, so a caller can report "no test command recorded".
EXEC_NO_LANE_EXIT = 78


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

      1. a recorded `test.command` (non-empty string)  -> that command (wins over
         every probe; `null` / absent / empty means none recorded and falls through)
      2. Makefile `test:` target                        -> "make test"
      3. pyproject.toml [tool.pytest…]                  -> "python -m pytest"
      4. package.json `test` script                     -> "npm test"
      5. a pytest config marker (pytest.ini / tox.ini
         [pytest] / setup.cfg [tool:pytest], via
         `task_scope_runner.pytest_config`)             -> "python3 -m pytest"
      6. (none of the above)                            -> None

    Checks in that order; returns the first that matches. The step-1 config read and the
    step-5 marker probe reuse their canonical sites (load_repo_config / task_scope_runner)
    so the two cannot drift.
    """
    root = Path(repo_root)
    # Step 1: a recorded `test.command` wins over every probe. `null` (offered and
    # declined), an absent key, or an empty string means none recorded — fall through.
    config = load_repo_config(root).config
    test = config.get("test")
    if isinstance(test, dict):
        command = test.get("command")
        if isinstance(command, str) and command:
            return command
    # Step 2: the existing Makefile / pyproject / package.json probes (unchanged).
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
    # Step 5: a pytest config marker (pytest.ini / tox.ini [pytest] / setup.cfg
    # [tool:pytest]) → the python3 pytest runner. Reuse task_scope_runner's probe so the
    # two sites cannot drift; import lazily (it imports iteration_lane only inside
    # _discover) so loading order can never cause a cycle.
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.insert(0, shared)
    import task_scope_runner  # noqa: E402 — lazy import, see the note above
    if task_scope_runner.pytest_config(root):
        return "python3 -m pytest"
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
        return LaneResult(f"{shlex.quote(str(ci_local_path(root)))} --fast", "iteration", False, "fast")
    return _discovered_lane(root, "iteration")


def gate_command(repo_root=None) -> LaneResult:
    """The full stamp-writing gate command — the sole stamp source. Resolves, in order
    (consumer-repo-parity H1):
      1. a declared `ci.gate_command` (non-empty string) → the `ci_gate_run.py`
         wrapper lane (runs the declared command, then stamps the head) — this is how
         a consumer repo names its own local CI gate. `null` (offered and declined)
         and a missing key fall through;
      2. `scripts/ci-local.sh` (dev + existing adopters) — unchanged;
      3. the discovered test command (`writes_stamp=False`).
    A declared command that stamps by itself (the dev repo's `scripts/ci-local.sh`)
    still goes through the wrapper, which re-stamps the same head (the second write
    is harmless). Emits no command when nothing resolves."""
    root = _resolve_root(repo_root)
    config = load_repo_config(root).config
    ci = config.get("ci")
    if isinstance(ci, dict):
        command = ci.get("gate_command")
        if isinstance(command, str) and command:
            return LaneResult(
                f"python3 {shlex.quote(str(_SHARED_DIR / 'ci_gate_run.py'))}", "gate", True, "config"
            )
    if fast_lane_available(root):
        return LaneResult(shlex.quote(str(ci_local_path(root))), "gate", True, "ci-local")
    return _discovered_lane(root, "gate")


def resolve(lane, *, granularity="phase", repo_root=None) -> LaneResult:
    """Dispatch to gate_command / iteration_command by lane name."""
    if lane == "gate":
        return gate_command(repo_root)
    return iteration_command(repo_root, granularity=granularity)


def run_lane(command, repo_root) -> int:
    """Run a resolved lane command through the shell in `repo_root`; return its status.

    The single execution owner for the lane: `shell=True` matches `ci_gate_run.py`, so
    a recorded command is parsed identically whichever lane runs it."""
    sys.stdout.flush()
    proc = subprocess.run(command, shell=True, cwd=str(repo_root))  # nosec B602 — operator's own recorded command
    return proc.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="iteration_lane — resolve the iteration (fast) vs gate (full) test command",
    )
    parser.add_argument("--lane", choices=("iteration", "gate"), default="iteration")
    parser.add_argument("--granularity", choices=("task", "phase"), default="phase")
    parser.add_argument(
        "--repo-root", default=None, help="target repo root (default: cwd git toplevel)"
    )
    parser.add_argument(
        "--exec", dest="execute", action="store_true",
        help="run the resolved command through the shell in the repo root and exit "
        f"with its status ({EXEC_NO_LANE_EXIT} when nothing resolves)",
    )
    args = parser.parse_args(argv)

    result = resolve(args.lane, granularity=args.granularity, repo_root=args.repo_root)
    if result.command is None:
        print(
            "iteration_lane: no test command resolved — no fast lane and no discoverable "
            "project test command (recorded test.command / Makefile / pyproject / "
            "package.json / pytest config). Run /tp-test-setup to record one; do NOT "
            "treat this as a green no-op.",
            file=sys.stderr,
        )
        return EXEC_NO_LANE_EXIT if args.execute else 1
    if args.execute:
        return run_lane(result.command, _resolve_root(args.repo_root))
    print(result.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
