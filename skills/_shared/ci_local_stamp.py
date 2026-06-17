"""ci_local_stamp.py — CI-local green stamp for the merge gate.

Writes a SHA-keyed stamp under the git dir when ci-local.sh completes
successfully. The merge gate requires a fresh, clean stamp matching the PR head.

Threat model: DRIFT, not forgery. The stamp guards against a PR that is
evaluated against a head the operator never ran CI on — e.g. a late force-push
after a green ci-local run. A forged stamp requires a deliberate act (writing a
file under .git/) that the git transcript does not record; this is a considered
residual, documented honestly. The stamp is NOT a cryptographic proof — it is a
mechanical drift guard that requires intentional circumvention to bypass.

Symbols exported:
  write_stamp(repo_root)   -> Path (stamp file path)
  read_stamp(repo_root)    -> dict | None
  pred_ci_local_stamp(...) -> PredicateResult
  StampError               (exception)

CLI:
  python3 ci_local_stamp.py --write   (writes stamp for cwd repo, exits 0 on success)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from deterministic_gate import GateVerdict, PredicateResult  # noqa: E402

# Sentinel for "stamp not provided; read from disk"
_UNSET = object()

STAMP_SCHEMA = 1
STAMP_SUBDIR = "three-pillars"
STAMP_FILENAME = "ci-local-stamp.json"


class StampError(Exception):
    """Raised by read_stamp when the stamp file exists but is unreadable/unparseable."""


def _get_git_dir(repo_root: Path) -> Path:
    """Return the absolute path to the git dir for this repo_root.

    For a linked worktree this is the per-checkout .git/worktrees/<name>/ dir.
    For a main checkout it is <repo_root>/.git (or the bare .git dir).
    Raises subprocess.CalledProcessError or OSError on failure.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    git_dir_str = result.stdout.strip()
    git_dir = Path(git_dir_str)
    if not git_dir.is_absolute():
        git_dir = (repo_root / git_dir).resolve()
    return git_dir


def _get_head_sha(repo_root: Path) -> str:
    """Return the current HEAD SHA. Raises subprocess.CalledProcessError on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _is_dirty(repo_root: Path) -> bool:
    """Return True if there are uncommitted changes in the working tree.

    Uses check=True so any git failure raises (matching _get_head_sha's posture).
    Fail-closed: a git error propagates to the caller (write_stamp) rather than
    silently recording dirty=False on a tree whose cleanliness was never proven.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def _stamp_path(repo_root: Path) -> Path:
    """Compute the stamp file path (under the git dir, never in the working tree)."""
    git_dir = _get_git_dir(repo_root)
    return git_dir / STAMP_SUBDIR / STAMP_FILENAME


def write_stamp(
    repo_root: Path,
    *,
    expect_head: "str | None" = None,
    expect_start_dirty: "bool | None" = None,
) -> Path:
    """Write a stamp for the current HEAD of repo_root.

    Creates <gitdir>/three-pillars/ci-local-stamp.json with:
      {"schema": 1, "head_sha": <HEAD oid>, "created_at": <ISO-8601>, "dirty": <bool>}

    Args:
        repo_root:          Repository root path.
        expect_head:        If provided, the SHA captured at the START of the CI run.
                            write_stamp re-samples HEAD at write time and refuses
                            (raises StampError) if the current HEAD differs from
                            expect_head. This closes the drift window: a commit that
                            lands mid-run would be stamped by tests that never ran
                            against it. ci-local.sh captures HEAD before the first
                            check and passes it here.
        expect_start_dirty: If provided, the dirty state sampled at the START of the
                            CI run (True=dirty, False=clean). write_stamp re-samples
                            dirty at write time and refuses (raises StampError) if:
                              (a) the run started dirty (expect_start_dirty=True), or
                              (b) the write-time dirty state disagrees with start dirty.
                            This closes the asymmetric-drift window: a stash/revert or
                            temp-commit + hard-reset mid-run would otherwise produce a
                            false-clean stamp.  ci-local.sh captures dirtiness before
                            the first check and passes it here.
                            Residual: two-point sampling (start + write) cannot catch a
                            mid-run transient that restores both HEAD and cleanliness
                            before write time. Such a transient would still produce a
                            false-clean stamp; this is a known residual alongside the
                            forgery residual documented in the module docstring.

    Returns the Path to the stamp file.
    Raises StampError if expect_head is given and HEAD has drifted.
    Raises StampError if expect_start_dirty is given and the dirty guard fires.
    Raises subprocess.CalledProcessError or OSError on other git/IO failure.
    The stamp lands under the git dir, so it never appears in `git status`.
    For linked worktrees, the git dir is the per-checkout .git/worktrees/<name>/ dir.
    """
    repo_root = Path(repo_root).resolve()
    head_sha = _get_head_sha(repo_root)

    if expect_head is not None and head_sha != expect_head:
        raise StampError(
            f"HEAD drifted during CI run: expected {expect_head!r} "
            f"(captured at run start) but current HEAD is {head_sha!r}. "
            "A commit landed mid-run; re-run ci-local.sh on the new HEAD."
        )

    dirty = _is_dirty(repo_root)

    if expect_start_dirty is not None:
        if expect_start_dirty:
            raise StampError(
                "CI run started with uncommitted changes (dirty working tree); "
                "stamps must be written from a clean tree. "
                "Commit or stash your changes and re-run ci-local.sh."
            )
        if dirty != expect_start_dirty:
            raise StampError(
                f"Working tree dirty state changed during CI run: "
                f"started {'dirty' if expect_start_dirty else 'clean'} "
                f"but now {'dirty' if dirty else 'clean'}. "
                "A stash/revert or mid-run change was detected; "
                "re-run ci-local.sh on a consistently clean tree."
            )

    created_at = datetime.now(tz=timezone.utc).isoformat()

    stamp_data: dict[str, Any] = {
        "schema": STAMP_SCHEMA,
        "head_sha": head_sha,
        "created_at": created_at,
        "dirty": dirty,
    }

    stamp_file = _stamp_path(repo_root)
    stamp_file.parent.mkdir(parents=True, exist_ok=True)
    stamp_file.write_text(json.dumps(stamp_data, indent=2))
    return stamp_file


def read_stamp(repo_root: Path) -> "dict | None":
    """Read the stamp for repo_root.

    Returns:
      dict  — if the stamp exists and is parseable
      None  — if the stamp file does not exist (no stamp written yet)

    Raises:
      StampError — if the stamp file exists but cannot be parsed (broken stamp)
    """
    repo_root = Path(repo_root).resolve()
    try:
        stamp_file = _stamp_path(repo_root)
    except Exception as e:
        raise StampError(f"could not resolve stamp path: {e}") from e

    if not stamp_file.exists():
        return None

    try:
        data = json.loads(stamp_file.read_text())
    except Exception as e:
        raise StampError(f"stamp file unreadable or unparseable: {e}") from e
    if not isinstance(data, dict):
        raise StampError(
            f"stamp file contains invalid content (expected a JSON object, "
            f"got {type(data).__name__!r}): {data!r}"
        )
    return data


def pred_ci_local_stamp(
    head_oid: str,
    *,
    repo_root: str,
    stamp: "dict | None | object" = _UNSET,
) -> PredicateResult:
    """Predicate: a fresh, clean ci-local stamp exists matching head_oid.

    Total function — never raises.

    Verdict matrix:
      PASS          — stamp.head_sha == head_oid AND dirty == False
      FAIL          — stamp absent (None): run ci-local.sh first
      FAIL          — stamp.head_sha != head_oid: stale stamp (drift)
      FAIL          — stamp.dirty == True: tests ran on uncommitted state
      INDETERMINATE — StampError or any internal error reading the stamp

    If stamp=_UNSET (default), the predicate calls read_stamp(repo_root).
    An injected stamp dict (or None) is used as-is (hermetic seam for tests).

    Threat model: drift, not forgery. A forged stamp requires deliberate action
    under .git/ that the git transcript does not record — this is a considered
    residual. The predicate guards against accidental drift, not adversarial acts.
    """
    try:
        if stamp is _UNSET:
            try:
                resolved_stamp: "dict | None" = read_stamp(Path(repo_root))
            except StampError as e:
                return PredicateResult(
                    name="ci_local_stamp",
                    verdict=GateVerdict.INDETERMINATE,
                    detail=f"stamp read error: {e}",
                )
        else:
            resolved_stamp = stamp  # type: ignore[assignment]

        if not head_oid:
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.INDETERMINATE,
                detail="empty head_oid passed to pred_ci_local_stamp — cannot evaluate stamp",
            )

        if resolved_stamp is None:
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.FAIL,
                detail="no ci-local stamp — run scripts/ci-local.sh on this head before landing",
            )

        stamp_schema = resolved_stamp.get("schema")
        if stamp_schema != STAMP_SCHEMA:
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.INDETERMINATE,
                detail=(
                    f"stamp schema mismatch: expected schema={STAMP_SCHEMA!r}, "
                    f"got schema={stamp_schema!r}; stamp may be from an incompatible version"
                ),
            )

        stamp_sha = resolved_stamp.get("head_sha", "")
        if stamp_sha != head_oid:
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.FAIL,
                detail=(
                    f"stale stamp: stamp.head_sha={stamp_sha!r} != head_oid={head_oid!r} "
                    "(drift — run ci-local.sh on the current head)"
                ),
            )

        dirty_val = resolved_stamp.get("dirty")
        if dirty_val is not False:
            return PredicateResult(
                name="ci_local_stamp",
                verdict=GateVerdict.FAIL,
                detail=(
                    f"stamp was written with uncommitted changes (dirty={dirty_val!r}) — "
                    "tests ran on uncommitted state; commit your changes and re-run ci-local.sh"
                ),
            )

        return PredicateResult(
            name="ci_local_stamp",
            verdict=GateVerdict.PASS,
            detail=f"ci-local green stamp matches head ({head_oid[:12]}), clean",
        )

    except Exception as e:
        return PredicateResult(
            name="ci_local_stamp",
            verdict=GateVerdict.INDETERMINATE,
            detail=f"stamp predicate internal error: {e}",
        )


def main(argv: "list[str]") -> int:
    """CLI: --write writes the stamp for the cwd repo and exits 0 on success."""
    parser = argparse.ArgumentParser(
        description="ci_local_stamp — write or inspect the ci-local green stamp",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the stamp for the cwd repo (called by ci-local.sh on success)",
    )
    parser.add_argument(
        "--expect-head",
        metavar="SHA",
        default=None,
        help=(
            "SHA captured at the START of the CI run. The writer re-samples HEAD "
            "at write time; if they differ (a commit landed mid-run) it refuses "
            "with a non-zero exit so ci-local.sh aborts and no stale stamp is written."
        ),
    )
    parser.add_argument(
        "--start-dirty",
        metavar="0|1",
        default=None,
        type=int,
        choices=(0, 1),
        help=(
            "Dirty state (0=clean, 1=dirty) sampled at the START of the CI run. "
            "The writer re-samples dirty at write time; if the run started dirty OR "
            "the dirty state changed mid-run, it refuses with a non-zero exit so "
            "ci-local.sh aborts and no false-clean stamp is written."
        ),
    )
    args = parser.parse_args(argv)

    if not args.write:
        parser.print_help()
        return 1

    try:
        repo_root = Path.cwd()
        expect_start_dirty: "bool | None" = None
        if args.start_dirty is not None:
            expect_start_dirty = bool(args.start_dirty)
        stamp_path = write_stamp(
            repo_root,
            expect_head=args.expect_head,
            expect_start_dirty=expect_start_dirty,
        )
        print(f"ci-local stamp written: {stamp_path}")
        return 0
    except Exception as e:
        print(f"Error writing ci-local stamp: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
