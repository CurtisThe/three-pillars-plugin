"""inflight_registry.py — build an in-flight design registry from origin/tp/* branches.

Stdlib-only helper (subprocess → git). Mirrors the shape of the other _shared
helpers: a dataclass model, pure logic functions, a thin git-I/O layer, and a
`python3 inflight_registry.py [...]` CLI `main()`. No third-party deps; the only
network access is via the user's own `git` against the user's own `origin`.

Data flow:
  `git ls-remote --heads origin 'refs/heads/tp/*'` (live SHAs, no fetch) →
  for each tp/* head, `git show {sha}:.../lock.json` (reads objects already
  local — freshness is the caller's job) → `classify` → `Registry`.

Two consumers:
  1. skills/_shared/collaboration.md preflight — build_registry + collision_verdict
     for the design being claimed (refuse-on-conflict unless --force-takeover) +
     print format_table for situational awareness.
  2. /tp-inflight (skills/tp-inflight/SKILL.md) — fail-open `git fetch` of tp/*
     refs, then this module's CLI to print the registry on demand, no side effects.

Design refs:
  - three-pillars-docs/tp-designs/inflight-design-registry/design.md
  - three-pillars-docs/tp-designs/inflight-design-registry/detailed-design.md
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional


STALE_DAYS = 30  # default staleness threshold; overridable via build_registry(stale_days=) and the --stale-days CLI flag

# Design-name charset per skills/_shared/validate-name.md — single-segment,
# lowercase, digits and hyphens only. Defends list_tp_branches against any
# non-conforming tp/* ref (uppercase, underscore, nested path) the glob surfaces.
_DESIGN_NAME_RE = re.compile(r"^[a-z0-9-]+$")


@dataclass
class RegistryEntry:
    design: str
    branch: str
    owner: Optional[str]
    phase: Optional[str]
    last_touched: Optional[str]
    sha: str
    age_days: Optional[float]
    stale: bool
    readable: bool


@dataclass
class Registry:
    entries: list[RegistryEntry]
    degraded: bool
    source: str


def _parse_iso8601(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime, or None.

    Tolerates a trailing 'Z' (treated as +00:00). Naive timestamps are assumed
    UTC. Any unparseable value yields None — callers treat that as "no age".
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def classify(design, branch, sha, lock, now, stale_days=STALE_DAYS):
    """Pure: turn a (possibly None) lock dict into a RegistryEntry.

    - lock is None → readable=False, all lock-derived fields None, stale=False.
    - last_touched read via .get (absent key OK) and parsed as ISO-8601;
      unparseable / absent → age_days None, stale False.
    - stale uses a strict comparison: age_days > stale_days (so exactly
      stale_days is NOT stale — the day-30 boundary is not abandoned).
    """
    if lock is None:
        return RegistryEntry(
            design=design,
            branch=branch,
            owner=None,
            phase=None,
            last_touched=None,
            sha=sha,
            age_days=None,
            stale=False,
            readable=False,
        )

    owner = lock.get("owner")
    phase = lock.get("phase")
    last_touched = lock.get("last_touched")

    age_days = None
    touched_dt = _parse_iso8601(last_touched)
    if touched_dt is not None:
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = now.astimezone(timezone.utc) - touched_dt
        age_days = delta.total_seconds() / 86400.0

    stale = age_days is not None and age_days > stale_days

    return RegistryEntry(
        design=design,
        branch=branch,
        owner=owner,
        phase=phase,
        last_touched=last_touched,
        sha=sha,
        age_days=age_days,
        stale=stale,
        readable=True,
    )


def collision_verdict(entries, design, owner_email):
    """Pure: resolve the collision verdict for the design being claimed.

    Returns (verdict, entry|None). Resolution order on the entry whose
    design == design:
      - no such entry                       → ("clear",   None)
      - readable and owner is None          → ("clear",   entry)  # released
      - readable and owner == owner_email   → ("self",    entry)  # you, elsewhere
      - readable and owner is someone else  → ("conflict",entry)  # different owner
      - not readable                        → ("conflict",entry)  # owner unconfirmed

    The readable flag is load-bearing: it distinguishes "owner None because
    released" (clear) from "owner unknown because the lock blob couldn't be
    read" (conflict — the same-name ref's existence is itself the collision
    signal, treated conservatively; --force-takeover overrides).
    """
    match = None
    for entry in entries:
        if entry.design == design:
            match = entry
            break

    if match is None:
        return ("clear", None)
    if not match.readable:
        return ("conflict", match)
    if match.owner is None:
        return ("clear", match)
    if match.owner == owner_email:
        return ("self", match)
    return ("conflict", match)


def _format_age(age_days):
    if age_days is None:
        return "-"
    return f"{age_days:.0f}d"


def format_table(registry):
    """Pure: render the registry as a human-readable table string.

    Columns: design | owner | phase | branch | age | flag. The flag column
    shows '⚠ stale' for stale entries and '· unreadable' for unreadable ones.
    A degraded registry prints an offline banner; an empty registry prints a
    'no in-flight designs' line.
    """
    lines = []
    if registry.degraded:
        lines.append(
            "⚠ in-flight registry unavailable (origin unreachable) — "
            "cannot list in-flight designs; your local work is unaffected"
        )

    if not registry.entries:
        if not registry.degraded:
            lines.append("No in-flight designs.")
        return "\n".join(lines)

    header = ("design", "owner", "phase", "branch", "age", "flag")
    rows = [header]
    for e in registry.entries:
        if not e.readable:
            flag = "· unreadable"
        elif e.stale:
            flag = "⚠ stale"
        else:
            flag = ""
        rows.append(
            (
                e.design,
                e.owner or "-",
                e.phase or "-",
                e.branch,
                _format_age(e.age_days),
                flag,
            )
        )

    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    for r in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip())

    return "\n".join(lines)


def to_json(registry):
    """Pure: render the registry as a stable, schema-stable JSON string.

    Top-level keys: degraded, source, entries[]. Each entry carries every
    RegistryEntry field (design, branch, owner, phase, last_touched, sha,
    age_days, stale, readable) — None values serialize as JSON null with the
    key present (not absent, not 0). Keys are sorted for stability.
    """
    payload = {
        "degraded": registry.degraded,
        "source": registry.source,
        "entries": [asdict(e) for e in registry.entries],
    }
    return json.dumps(payload, sort_keys=True, indent=2)


# --------------------------------------------------------------------------- #
# Git I/O layer
# --------------------------------------------------------------------------- #


class RemoteUnreachable(Exception):
    """Raised by list_tp_branches when the remote can't be listed."""


def list_tp_branches(remote="origin"):
    """Git I/O: list conforming tp/* design branches on the remote.

    Runs `git ls-remote --heads {remote} 'refs/heads/tp/*'`, parses each
    `<sha>\\trefs/heads/tp/<name>` line, and filters <name> against
    ^[a-z0-9-]+$ so only single-segment, lowercase design names pass — this
    drops non-conforming tp/* refs (uppercase, underscore, nested tp/a/b).
    (candidate/* and worktree-agent-* refs are already outside the glob.)
    Returns a sorted list of (name, sha). Always-live: no fetch, no cache.

    Raises RemoteUnreachable on a non-zero git exit (no remote, offline, auth)
    so build_registry can distinguish failure (degraded) from empty (reachable).
    """
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--heads", remote, "refs/heads/tp/*"],
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        # git not installed / not on PATH — treat as "remote can't be listed"
        # so build_registry fails-open to the degraded local view (matches
        # read_lock_blob's OSError handling). Without this the OSError would
        # bypass the RemoteUnreachable path and crash the whole build.
        raise RemoteUnreachable(str(exc)) from exc
    if proc.returncode != 0:
        raise RemoteUnreachable(proc.stderr.strip() or "git ls-remote failed")

    result = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, ref = parts
        prefix = "refs/heads/tp/"
        if not ref.startswith(prefix):
            continue
        name = ref[len(prefix):]
        if not _DESIGN_NAME_RE.match(name):
            continue
        result.append((name, sha))

    return sorted(result)


def read_lock_blob(sha, design):
    """Git I/O: read the committed lock.json for `design` at commit `sha`.

    Runs `git show {sha}:three-pillars-docs/tp-designs/{design}/lock.json` and
    returns the parsed dict, or None when:
      - the object isn't present locally (never fetched) — non-zero git exit;
      - the file is absent at that path — non-zero git exit;
      - the blob is present but not valid JSON — JSONDecodeError.
    Per-entry fail-open: never raises. This is the path the data flow relies on
    so a single unfetched/malformed lock degrades to an unreadable entry rather
    than crashing the whole registry build.
    """
    path = f"three-pillars-docs/tp-designs/{design}/lock.json"
    try:
        proc = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def build_registry(remote="origin", now=None, stale_days=STALE_DAYS):
    """Compose list → read → classify into a Registry.

    On list_tp_branches success (remote reachable), classifies every tp/*
    branch — including ones whose lock blob is unreadable (readable=False) —
    and returns Registry(degraded=False, source="remote"). An empty-but-
    reachable remote yields entries=[] with degraded=False (distinct from the
    degraded path). On list_tp_branches failure (no remote, offline, auth),
    returns Registry(entries=[], degraded=True, source="local") — whole-
    registry fail-open.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    try:
        branches = list_tp_branches(remote=remote)
    except RemoteUnreachable:
        return Registry(entries=[], degraded=True, source="local")

    entries = []
    for name, sha in branches:
        lock = read_lock_blob(sha, name)
        entries.append(
            classify(
                design=name,
                branch=f"tp/{name}",
                sha=sha,
                lock=lock,
                now=now,
                stale_days=stale_days,
            )
        )

    return Registry(entries=entries, degraded=False, source="remote")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def main(argv=None):
    """CLI entry point. Always exits 0 (read-only, fail-open).

    Flags: --json (emit to_json instead of format_table), --remote NAME,
    --stale-days N. Any internal error degrades to an empty/degraded payload
    rather than a non-zero exit — callers (and /tp-inflight) must never be
    blocked by a registry failure. Even argparse usage errors (unknown flag,
    non-int --stale-days) and --help are caught and return 0: argparse has
    already written its message to stderr, and the contract is that this CLI
    never blocks a caller with a non-zero exit.
    """
    parser = argparse.ArgumentParser(
        prog="inflight_registry",
        description="Build an in-flight design registry from origin/tp/* branches.",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument("--remote", default="origin", help="git remote name or path")
    parser.add_argument(
        "--stale-days", type=int, default=STALE_DAYS,
        help=f"days before a branch is flagged stale (default {STALE_DAYS})",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits non-zero on usage errors (and 0 on --help); both raise
        # SystemExit. The message is already on stderr — honor always-exit-0.
        return 0

    try:
        registry = build_registry(remote=args.remote, stale_days=args.stale_days)
    except Exception:
        registry = Registry(entries=[], degraded=True, source="local")

    try:
        if args.json:
            print(to_json(registry))
        else:
            print(format_table(registry))
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
