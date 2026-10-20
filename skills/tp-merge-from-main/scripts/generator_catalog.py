#!/usr/bin/env python3
"""The lockfile catalog and the pure detector for undeclared generated files.

A committed lockfile (`package-lock.json`, `uv.lock`) beside its manifest is a generated file the
base sync can rebuild instead of deferring - but only once it is declared in
`merge_from_main.generators`. This module holds the catalog of known lockfiles and the pure
functions that decide which tracked lockfiles are worth offering, what config item one becomes, and
how the offer is recorded. Nothing here shells out or writes config; the CLI that wires it to a
repository comes later. Stdlib only.

Every catalog argv carries its tool's no-lifecycle-scripts flag (`--ignore-scripts` for npm,
`--no-build` for uv): regeneration runs unreviewed dependency code, so it must never execute a
package's own install scripts (Behavior 7).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# _shared/ for repo_config_load, imported lazily inside the CLI functions so the pure
# detector stays importable without it (the idiom of gate_cli.py / archive_moves.py).
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "_shared"


@dataclass(frozen=True)
class CatalogEntry:
    """One known generated file: the `basename` to look for, the `inputs` (manifest basenames that
    must sit beside it), the `tool` that must be on PATH, the `write` argv that rebuilds the file,
    the optional `check` argv that must exit 0 afterwards, and the per-run `timeout`."""
    basename: str
    inputs: tuple[str, ...]
    tool: str
    write: list[str]
    check: list[str] | None = None
    timeout: int = 300


CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        basename="package-lock.json",
        inputs=("package.json",),
        tool="npm",
        write=["npm", "install", "--package-lock-only", "--ignore-scripts",
               "--no-audit", "--no-fund"],
        check=["npm", "ci", "--dry-run", "--ignore-scripts", "--no-audit", "--no-fund"],
    ),
    CatalogEntry(
        basename="uv.lock",
        inputs=("pyproject.toml",),
        tool="uv",
        write=["uv", "lock", "--no-build"],
        check=["uv", "lock", "--check", "--no-build"],
    ),
]

_BY_BASENAME = {e.basename: e for e in CATALOG}


@dataclass(frozen=True)
class CatalogMatch:
    """A tracked lockfile the catalog knows: its repo-relative `path`, the `cwd` (its directory,
    None at the repo root) the tool runs in, and the `entry` that matched."""
    path: str
    cwd: str | None
    entry: CatalogEntry


def _dir_of(path: str) -> str:
    """The directory part of a repo-relative posix path, "" at the repo root."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _declared_paths(config: dict) -> set[str]:
    """Paths already covered by a `merge_from_main.generators` item (absent key -> none)."""
    items = config.get("merge_from_main", {}).get("generators", [])
    if not isinstance(items, list):
        return set()
    return {i["path"] for i in items if isinstance(i, dict) and isinstance(i.get("path"), str)}


def _offered_paths(config: dict) -> set[str]:
    """Paths already put to the operator by `merge_from_main.generator_offer` (absent -> none)."""
    offer = config.get("merge_from_main", {}).get("generator_offer", {})
    paths = offer.get("offered_paths", []) if isinstance(offer, dict) else []
    return {p for p in paths if isinstance(p, str)} if isinstance(paths, list) else set()


def detect(tracked, config: dict, only=None) -> list[CatalogMatch]:
    """The tracked lockfiles worth offering: a tracked path whose basename the catalog knows, whose
    sibling manifests are all tracked in the same directory, that no `merge_from_main.generators`
    item declares, and that `generator_offer.offered_paths` has not already offered. `only`, when
    given, restricts the result to those paths. Sorted by path; a pure function of its inputs."""
    tracked_set = set(tracked)
    declared = _declared_paths(config)
    offered = _offered_paths(config)
    wanted = set(only) if only is not None else None
    matches: list[CatalogMatch] = []
    for path in sorted(tracked_set):
        if wanted is not None and path not in wanted:
            continue
        if path in declared or path in offered:
            continue
        entry = _BY_BASENAME.get(path.rsplit("/", 1)[-1])
        if entry is None:
            continue
        directory = _dir_of(path)
        siblings = [f"{directory}/{name}" if directory else name for name in entry.inputs]
        if not all(s in tracked_set for s in siblings):
            continue
        matches.append(CatalogMatch(path=path, cwd=directory or None, entry=entry))
    return matches


def config_entry(m: CatalogMatch) -> dict:
    """The `merge_from_main.generators` item for a match: concrete argv (never a catalog reference)
    and repo-relative `inputs`. `cwd` is present only for a nested lockfile and `check` only when
    the entry declares one, so `regenerate.load_generators` accepts it unchanged."""
    entry = m.entry
    out = {
        "path": m.path,
        "write": list(entry.write),
        "timeout": entry.timeout,
        "inputs": [f"{m.cwd}/{name}" if m.cwd else name for name in entry.inputs],
    }
    if entry.check is not None:
        out["check"] = list(entry.check)
    if m.cwd is not None:
        out["cwd"] = m.cwd
    return out


def offer_record(config: dict, paths, *, accepted: bool, now: str) -> dict:
    """The merged `generator_offer` block: `offered_at` is `now`, `declined` is the answer, and
    `offered_paths` is what the config already held plus `paths` - deduped and sorted, so a repeat
    offer of the same lockfile stays one entry."""
    merged = _offered_paths(config) | {p for p in paths if isinstance(p, str)}
    return {"offered_at": now, "declined": not accepted, "offered_paths": sorted(merged)}


def tool_on_path(m: CatalogMatch, which=shutil.which) -> bool:
    """Whether the matched entry's tool resolves on PATH - through the injected `which`, so the
    detector stays testable with no npm or uv installed."""
    return bool(which(m.entry.tool))


# --- Task 3.3: the detect / accept / decline CLI -------------------------------

def _tracked_paths(repo) -> list[str]:
    """The repository's tracked paths, from the INDEX (`git ls-files`), never the working tree —
    so a lockfile staged but not yet committed is still seen. List argv, no shell."""
    proc = subprocess.run(["git", "-C", str(repo), "ls-files"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"git ls-files failed: {proc.stderr.strip()}")
    return [line for line in proc.stdout.splitlines() if line]


def _load_config(repo) -> dict:
    """The pruned repo config (`load_repo_config` never raises; absent -> {})."""
    if str(_SHARED_DIR) not in sys.path:
        sys.path.insert(0, str(_SHARED_DIR))
    import repo_config_load
    return repo_config_load.load_repo_config(repo).config


def _now() -> str:
    """The offer timestamp: UTC, ISO-8601, second resolution."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _raw_merge_from_main(repo) -> dict:
    """The `merge_from_main` block exactly as the file holds it (absent file / block -> {}).

    The base for the rewrite is the RAW block, not the pruned one the reader returns: rewriting a
    block whose keys this tool does not know would silently drop them, so the write is refused
    instead (fail closed) and the operator keeps the file they wrote."""
    path = Path(repo) / ".three-pillars" / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    block = data.get("merge_from_main", {}) if isinstance(data, dict) else {}
    return block if isinstance(block, dict) else {}


def _config_without_offers(config: dict) -> dict:
    """A copy of `config` with `generator_offer.offered_paths` emptied.

    `accept` re-detects through this: a path an earlier `decline` recorded is still acceptable (the
    operator changed their mind), so the offered-path exclusion must not swallow it. The
    declared-generator exclusion is left intact, so accepting twice appends the entry once."""
    copied = dict(config)
    block = copied.get("merge_from_main")
    block = dict(block) if isinstance(block, dict) else {}
    offer = block.get("generator_offer")
    offer = dict(offer) if isinstance(offer, dict) else {}
    offer["offered_paths"] = []
    block["generator_offer"] = offer
    copied["merge_from_main"] = block
    return copied


def _write_merged(repo, config, paths, tracked, *, accepted: bool) -> int:
    """One `update_config` call for the whole `merge_from_main` object: the existing generators
    kept in order, the detected entries for `paths` appended (accept only - a decline leaves them
    untouched), and the `generator_offer` record. `tracked` is the repository's tracked paths, read
    once by `main`. A refused write (one `update_config` would prune) is exit 2 with one stderr
    line, file untouched."""
    if str(_SHARED_DIR) not in sys.path:
        sys.path.insert(0, str(_SHARED_DIR))
    import repo_config_load
    merged = dict(_raw_merge_from_main(repo))
    generators = merged.get("generators", [])
    merged["generators"] = list(generators) if isinstance(generators, list) else []
    if accepted:
        for match in detect(tracked, _config_without_offers(config), only=paths):
            merged["generators"].append(config_entry(match))
    merged["generator_offer"] = offer_record(config, paths, accepted=accepted, now=_now())
    try:
        repo_config_load.update_config(repo, "merge_from_main", merged)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv=None) -> int:
    """`generator_catalog.py detect --repo R [--only P ...] --json | accept --repo R --paths P ...
    | decline --repo R --paths P ...`.

    `detect` writes nothing. `accept` / `decline` write the whole `merge_from_main` object in ONE
    `repo_config_load.update_config` call. Every subcommand reads its repository's tracked paths
    first, so a repo that is not a git checkout is refused before anything is written. Exit 0 ok;
    2 on a usage error (argparse's own), a repo outside git, or a refused write."""
    parser = argparse.ArgumentParser(prog="generator_catalog.py")
    sub = parser.add_subparsers(dest="command", required=True)

    det = sub.add_parser("detect", help="list lockfiles worth offering; writes nothing")
    det.add_argument("--repo", required=True)
    det.add_argument("--only", action="extend", nargs="+", default=None, metavar="P")
    det.add_argument("--json", action="store_true", dest="as_json")

    for name, help_text in (("accept", "declare the offered generators"),
                            ("decline", "record the offer as declined")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--repo", required=True)
        cmd.add_argument("--paths", nargs="+", required=True, metavar="P")

    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])

    try:
        tracked = _tracked_paths(args.repo)
    except ValueError as exc:
        # One line whatever git printed: outside a repo git's stderr is one line when the cwd
        # shares a filesystem with `/` and two when it does not, so the message is collapsed.
        print("error: " + " ".join(str(exc).split()), file=sys.stderr)
        return 2

    if args.command == "detect":
        matches = detect(tracked, _load_config(args.repo), only=args.only)
        items = [{"path": m.path, "tool": m.entry.tool, "tool_on_path": tool_on_path(m),
                  "entry": config_entry(m)} for m in matches]
        print(json.dumps(items if args.as_json else [i["path"] for i in items], indent=2))
        return 0

    config = _load_config(args.repo)
    return _write_merged(args.repo, config, args.paths, tracked,
                         accepted=args.command == "accept")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
