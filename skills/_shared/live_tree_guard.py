#!/usr/bin/env python3
"""live_tree_guard.py — did a cheap-tier drafter write the live tree? Undo only that.

design: cheap-tier-offload (PR #191 review r1). A drafter is told to write one scratch
file, but its cwd is the live worktree, so a stray edit there would ride into the
round's commit. The site snapshots the tree before the drafter runs and checks it
after:

- `snapshot(root, store)` records HEAD and every path `git status` lists (tracked
  changes, conflicts and untracked files; ignored files are out of scope) with its
  index entries, its worktree bytes and its worktree mode, under `store`;
- `guard(root, store, exclude=())` lists each path that changed since: a path that
  appeared in `git status`, or a snapshot path whose index entries or bytes differ.
  Paths under `exclude` (the scratch dir) and under `store` never count. It then undoes
  ONLY those paths: a snapshot path gets its bytes, mode and index entries back, a tracked
  path that was clean is restored from the snapshot HEAD, and a new untracked file is
  removed. Nothing else is touched (never a blanket checkout or clean). Any change is
  `ok: false` with reason `drafter-wrote-live-tree: <paths>`; a moved HEAD is reported,
  never reset. A missing snapshot or a failed git listing is `ok: false` too;
- `rebase(root, store, paths)` re-records `paths` as they are now: a change the caller
  made itself (an accepted cheap fix) is then the baseline, never a drafter write.

CLI (one JSON line, exit 0 on every path; a missing flag is argparse's exit 2):
    live_tree_guard.py snapshot --root R --store D
    live_tree_guard.py check --root R --store D [--exclude P ...]
Stdlib-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REASON = "drafter-wrote-live-tree"
_ZERO = "0" * 40
_SNAP = "snapshot.json"
SNAPSHOT = _SNAP  # the snapshot file's name inside `store`


class GuardError(RuntimeError):
    """git could not list the tree, or the snapshot is unreadable."""


def _git(root, *args, data: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(["git", "-C", str(root), "--literal-pathspecs", *args],
                              input=data, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GuardError(f"git {args[0]} did not run: {exc}") from exc
    if proc.returncode != 0:
        raise GuardError(f"git {args[0]} exited {proc.returncode}: "
                         + proc.stderr.decode(errors="replace").strip()[-300:])
    return proc.stdout


def _status(root) -> set[str]:
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all",
               "--no-renames")
    return {e[3:] for e in out.decode(errors="surrogateescape").split("\0") if len(e) > 3}


def _index(root, path: str) -> list[str]:
    out = _git(root, "ls-files", "-s", "-z", "--", path).decode(errors="surrogateescape")
    return sorted(e.split("\t", 1)[0] for e in out.split("\0") if e)


def _head(root) -> str | None:
    try:
        return _git(root, "rev-parse", "--verify", "-q", "HEAD").decode().strip()
    except GuardError:
        return None  # an unborn HEAD


def _bytes_fp(file: Path) -> str | None:
    if file.is_symlink():
        return "link:" + os.readlink(file)
    if file.is_file():
        return hashlib.sha256(file.read_bytes()).hexdigest()
    return None


def _mode(file: Path) -> int | None:
    if file.is_symlink() or not file.is_file():
        return None
    return stat.S_IMODE(file.stat().st_mode)


def _fp(root: Path, path: str) -> dict:
    return {"index": _index(root, path), "bytes": _bytes_fp(root / path),
            "mode": _mode(root / path)}


def _record(root: Path, store: Path, path: str, blob: str) -> dict:
    fp = _fp(root, path)
    if not (fp["bytes"] and not fp["bytes"].startswith("link:")):
        return {**fp, "blob": None}
    shutil.copyfile(root / path, store / blob)
    return {**fp, "blob": blob}


def _skip(path: str, skips: list[str]) -> bool:
    return any(path == s or path.startswith(s + "/") for s in skips)


def _rel_skips(root: Path, dirs) -> list[str]:
    out, top = [], root.resolve()
    for d in dirs:
        p = Path(d)
        p = (p if p.is_absolute() else top / p).resolve()
        if p == top or top in p.parents:
            out.append(p.relative_to(top).as_posix())
    return out


def snapshot(root, store) -> Path:
    """Record the live tree's dirty paths under `store`; returns the snapshot file."""
    root, store = Path(root), Path(store)
    skips = _rel_skips(root, [store])
    store.mkdir(parents=True, exist_ok=True)
    paths = {path: _record(root, store, path, f"b{i}") for i, path in
             enumerate(sorted(p for p in _status(root) if not _skip(p, skips)))}
    snap = store / _SNAP
    snap.write_text(json.dumps({"head": _head(root), "paths": paths}, sort_keys=True),
                    encoding="utf-8")
    return snap


def _load(store) -> dict:
    try:
        data = json.loads((Path(store) / _SNAP).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuardError(f"no live-tree snapshot in {store}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise GuardError(f"malformed live-tree snapshot in {store}")
    return data


def rebase(root, store, paths) -> None:
    """Re-record `paths` in the snapshot as the live tree holds them now."""
    root, store = Path(root), Path(store)
    data = _load(store)
    for path in paths:
        tag = hashlib.sha256(path.encode(errors="surrogateescape")).hexdigest()[:16]
        data["paths"][path] = _record(root, store, path, f"r{tag}")
    (store / _SNAP).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def _same(now: dict, fp: dict) -> bool:
    return now == {"index": fp["index"], "bytes": fp["bytes"], "mode": fp.get("mode")}


def changed(root, store, exclude=()) -> list[str]:
    """The paths that differ from the snapshot (not under `exclude` or `store`)."""
    root = Path(root)
    before = _load(store)["paths"]
    skips = _rel_skips(root, [store, *exclude])
    now = {p for p in _status(root) if not _skip(p, skips)}
    out = {p for p in now if p not in before}
    out |= {p for p, fp in before.items() if not _skip(p, skips)
            and not _same(_fp(root, p), fp)}
    return sorted(out)


def _set_index(root, path: str, entries: list[str]) -> None:
    lines = [f"0 {_ZERO}\t{path}"] + [f"{e}\t{path}" for e in entries]
    _git(root, "update-index", "-z", "--index-info",
         data="".join(line + "\0" for line in lines).encode(errors="surrogateescape"))


def _put_bytes(root: Path, store: Path, path: str, fp: dict) -> None:
    file = root / path
    if file.is_symlink() or file.is_file():
        file.unlink()
    if fp["bytes"] is None:
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    if fp["bytes"].startswith("link:"):
        os.symlink(fp["bytes"][len("link:"):], file)
    else:
        shutil.copyfile(store / fp["blob"], file)
        if fp.get("mode") is not None:
            os.chmod(file, fp["mode"])


def restore(root, store, paths) -> list[str]:
    """Undo `paths` only; returns the ones that could not be restored."""
    root, store = Path(root), Path(store)
    snap = _load(store)
    before, head, failed = snap["paths"], snap.get("head"), []
    for path in paths:
        try:
            if path in before:
                _set_index(root, path, before[path]["index"])
                _put_bytes(root, store, path, before[path])
                continue
            tree = _git(root, "ls-tree", "-z", head, "--", path).decode() if head else ""
            if tree:  # tracked and clean before: back to the snapshot HEAD
                _set_index(root, path, [tree.split(" ", 1)[0] + " "
                                        + tree.split("\t", 1)[0].split()[2] + " 0"])
                _git(root, "checkout-index", "-f", "--", path)
            else:  # new since the snapshot: the drafter created it
                _set_index(root, path, [])
                _put_bytes(root, store, path, {"bytes": None})
        except (GuardError, OSError):
            failed.append(path)
    return failed


def guard(root, store, exclude=()) -> dict:
    """{ok, reason, paths, unrestored}: undo any live-tree change since the snapshot."""
    try:
        paths = changed(root, store, exclude)
        moved = _load(store).get("head") != _head(root)
        unrestored = restore(root, store, paths)
    except GuardError as exc:
        return {"ok": False, "reason": f"live-tree unobservable: {exc}", "paths": [],
                "unrestored": []}
    if not paths and not moved:
        return {"ok": True, "reason": "", "paths": [], "unrestored": []}
    why = f"{REASON}: {', '.join(paths)}" if paths else REASON
    why += "; HEAD moved (not reset)" if moved else ""
    why += f"; could not restore {', '.join(unrestored)}" if unrestored else ""
    return {"ok": False, "reason": why, "paths": paths, "unrestored": unrestored}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="live_tree_guard.py",
                                     description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sn = sub.add_parser("snapshot", help="record the live tree before the drafter runs")
    ck = sub.add_parser("check", help="after the drafter: undo and report any live change")
    for p in (sn, ck):
        p.add_argument("--root", required=True)
        p.add_argument("--store", required=True)
    ck.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args(argv)
    if args.cmd == "snapshot":
        try:
            out = {"ok": True, "snapshot": str(snapshot(args.root, args.store))}
        except (GuardError, OSError) as exc:
            out = {"ok": False, "reason": f"live-tree unobservable: {exc}"}
    else:
        out = guard(args.root, args.store, args.exclude)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
