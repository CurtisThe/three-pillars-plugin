"""round_log_carry.py -- classify and strip round-log commits (review-log-survives-teardown).

A round-log commit is a single-parent commit that only adds to or modifies the round-log files of
ONE already-archived design dir. `strip_round_log_commits` walks the first-parent chain from a head
past at most `max_links` such commits and returns the anchor it stopped at; a caller compares the
anchor against reviewed heads, so a chain longer than the cap fails closed.

stdlib-only, total, never raises. `run_git(args) -> (rc, out, err)` is the same seam shape as
`base_sync_cert`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from dataclasses import dataclass

ROUND_LOG_NAMES = ("decisions.md", "dispatch-telemetry.ndjson", "escape-ledger.ndjson",
                   "finalizer-ledger.json")
_ARCHIVE_PREFIX = "three-pillars-docs/completed-tp-designs/"
_SLUG_RE = re.compile(r"[a-z0-9-]+")
RULINGS_PREFIX = "three-pillars-docs/escalations/rulings/"
_RULING_FILE_RE = re.compile(r"([a-z0-9-]+)-\d{8}-[0-9a-f]{6}\.md")
_ZERO_MODE = "000000"
_REG_MODE = "100644"
_DEFAULT_MAX_LINKS = 3


@dataclass(frozen=True)
class StripResult:
    anchor: "str | None" = None   # sha the walk stopped at; None = could not resolve (fail closed)
    links: int = 0                # round-log commits stripped
    reason: str = ""              # why the walk stopped (or why it could not start)


def _make_default_git(repo_root):
    def _run(args: list[str]) -> tuple[int, str, str]:
        try:
            r = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True)
        except Exception:
            return (-1, "", "")
        return (r.returncode, r.stdout.decode("utf-8", "surrogateescape"),
                r.stderr.decode("utf-8", "surrogateescape"))
    return _run


def _parse_raw(out: str):
    """Parse `diff-tree --raw -z` output into [(old_mode, new_mode, status, path)], or None."""
    toks = out.split("\0")
    if toks and toks[-1] == "":
        toks.pop()
    entries = []
    i = 0
    while i < len(toks):
        meta = toks[i].split()
        if len(meta) != 5 or not meta[0].startswith(":") or i + 1 >= len(toks):
            return None
        entries.append((meta[0][1:], meta[1], meta[4], toks[i + 1]))
        i += 2
    return entries


def round_log_slug(path: str) -> "str | None":
    """Archived round-log path or run ruling file -> its design slug; None otherwise."""
    parts = path.split("/")
    if path.startswith(_ARCHIVE_PREFIX) and len(parts) == 4:
        if parts[3] in ROUND_LOG_NAMES and _SLUG_RE.fullmatch(parts[2]):
            return parts[2]
    elif path.startswith(RULINGS_PREFIX) and len(parts) == 4:
        m = _RULING_FILE_RE.fullmatch(parts[3])
        if m and m.group(1) != "seat":  # a seat ruling is nobody's design
            return m.group(1)
    return None


def is_round_log_commit(git, parent: str, commit: str) -> tuple[bool, str]:
    """(True, "") when `commit` over `parent` flushes one archived design's logs (+ its rulings)."""
    try:
        rc, out, _ = git(["diff-tree", "-r", "--no-renames", "--raw", "-z", parent, commit])
        if rc != 0:
            return (False, "diff-tree failed")
        entries = _parse_raw(out)
        if not entries:
            return (False, "empty or unparseable diff")
        slugs = set()
        has_archived_log = False
        for old_mode, new_mode, status, path in entries:
            if status not in ("M", "A"):
                return (False, f"status {status} on {path}")
            if new_mode != _REG_MODE or old_mode != (_REG_MODE if status == "M" else _ZERO_MODE):
                return (False, f"mode change on {path}")
            if path.startswith(RULINGS_PREFIX):
                slug = round_log_slug(path)
                if slug is None:
                    return (False, f"{path} is not a ruling file")
                slugs.add(slug)
                continue
            if not path.startswith(_ARCHIVE_PREFIX):
                return (False, f"{path} is outside the archive")
            parts = path[len(_ARCHIVE_PREFIX):].split("/")
            if len(parts) != 2 or parts[1] not in ROUND_LOG_NAMES:
                return (False, f"{path} is not a round-log file")
            if not _SLUG_RE.fullmatch(parts[0]):
                return (False, f"bad slug in {path}")
            slugs.add(parts[0])
            has_archived_log = True
        if not has_archived_log:
            return (False, "no archived round-log file")
        if len(slugs) != 1:
            return (False, "touches more than one design")
        slug = next(iter(slugs))
        rc, _, _ = git(["cat-file", "-e", f"{parent}:{_ARCHIVE_PREFIX}{slug}/design.md"])
        if rc != 0:
            return (False, f"archive {slug} absent in parent")
        return (True, "")
    except Exception as exc:  # total: never raise
        return (False, f"error: {exc}")


def strip_round_log_commits(repo_root, head: str, *, max_links: int = _DEFAULT_MAX_LINKS,
                            run_git=None) -> StripResult:
    """Walk first-parent from `head` past up to `max_links` round-log commits; never raises."""
    try:
        git = run_git or _make_default_git(repo_root)
        cur = head
        links = 0
        while True:
            rc, out, _ = git(["rev-list", "--parents", "-n1", cur])
            fields = out.split()
            if rc != 0 or not fields:
                if links == 0:
                    return StripResult(None, 0, f"cannot resolve {head}")
                return StripResult(cur, links, f"cannot resolve parents of {cur}")
            cur = fields[0]
            if len(fields) == 1:
                return StripResult(cur, links, "root commit")
            if len(fields) > 2:
                return StripResult(cur, links, "merge commit")
            ok, why = is_round_log_commit(git, fields[1], cur)
            if not ok:
                return StripResult(cur, links, why)
            if links >= max_links:
                return StripResult(cur, links, f"round-log chain exceeds the cap of {max_links}")
            links += 1
            cur = fields[1]
    except Exception as exc:
        return StripResult(None, 0, f"error: {exc}")


_UNSET = object()


def pred_ci_local_stamp_carried(head_oid, *, repo_root, stamp=_UNSET, gate_command=None,
                                run_git=None):
    """`ci_local_stamp.pred_ci_local_stamp`, but a clean stamp at the anchor carries across
    round-log commits. Only a stale-stamp FAIL is ever upgraded; everything else is unchanged.
    An injected stamp with no `run_git` is the hermetic branch: no git is spawned."""
    import ci_local_stamp  # lazy: house style
    kw = {"repo_root": repo_root, "gate_command": gate_command}
    if stamp is not _UNSET:
        kw["stamp"] = stamp
    r = ci_local_stamp.pred_ci_local_stamp(head_oid, **kw)
    try:
        if r.verdict != ci_local_stamp.GateVerdict.FAIL:
            return r
        if stamp is _UNSET:
            stamp = ci_local_stamp.read_stamp(Path(repo_root))
        elif run_git is None:
            return r
        if not isinstance(stamp, dict) or stamp.get("dirty") is not False:
            return r
        stamp_sha = stamp.get("head_sha")
        if not stamp_sha or stamp_sha == head_oid:
            return r
        res = strip_round_log_commits(repo_root, head_oid, run_git=run_git)
        if res.links <= 0 or res.anchor != stamp_sha:
            return r
        kw["stamp"] = stamp
        anchored = ci_local_stamp.pred_ci_local_stamp(res.anchor, **kw)
        if anchored.verdict != ci_local_stamp.GateVerdict.PASS:
            return r
        return ci_local_stamp.PredicateResult(
            name="ci_local_stamp", verdict=ci_local_stamp.GateVerdict.PASS,
            detail=f"ci-local stamp carried across {res.links} round-log commit(s) "
                   f"from {stamp_sha[:12]} to head {head_oid[:12]}")
    except Exception:
        return r


def main(argv: "list[str] | None" = None) -> int:
    """`check [--repo .] [REV]`: 0 accepted, 1 rejected (reason on stdout), 2 error."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog="round_log_carry.py")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--repo", default=".")
    parser.add_argument("rev", nargs="?", default="HEAD")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        run = _make_default_git(args.repo)
        rc, out, err = run(["rev-list", "--parents", "-n1", args.rev, "--"])
        fields = out.split()
        if rc != 0 or not fields:
            print(f"cannot resolve {args.rev}: {(err or '').strip()}", file=sys.stderr)
            return 2
        if len(fields) != 2:
            print(f"rejected: {args.rev} is not a single-parent commit")
            return 1
        ok, why = is_round_log_commit(run, fields[1], fields[0])
        print("accepted" if ok else f"rejected: {why}")
        return 0 if ok else 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
