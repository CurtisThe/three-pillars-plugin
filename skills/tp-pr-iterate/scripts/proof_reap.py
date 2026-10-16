"""proof_reap — keep only the proof files of a /tp-pr-iterate proof root.

design: fragile-test-prevention (Task 12.1)

`prune_to_proof(pr_dir)` reduces `<root>/rounds/<pr>` to the proof files and
`size_check(root)` is the size backstop. A PR dir whose latest round has no
terminal yet (open) is never reaped; the state is read from the round's own
files (`tail/envelope.json` terminal, or a `tail/closed.json` marker), never
from mtime. Manifests that still name a pre-migration root are repointed first.
Symlinks are never followed; they are unlinked.

CLI: `prune --pr N [--root R]` | `size-check [--root R] [--max-mb M]` print one
JSON object; exit 2 + one JSON line on a refusal. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import proof_root  # noqa: E402

PROOF_FILES = {
    "round": ("angles.json", "tail/envelope.json", "tail/closed.json"),
    "angle": ("reply.md",),
    # Only the latest round keeps these: a scoped round-2 prepare reads the prior round's
    # findings (`round_plan._findings`), so the flush must not reap them.
    "latest": ("tail/findings.json",),
    "head": ("meta.json", "transcripts.json", "numstat.txt"),
    "root": ("iterate-state.*.v1.json", "iterate-log.*.md"),
}
_ROUND_RE = re.compile(r"^r(\d+)(\.1)?$")
TAIL = "tail"


def _size(p) -> int:
    try:
        return os.lstat(p).st_size
    except OSError:
        return 0


def _strip(top: Path, keep: set) -> list:
    """Remove all but `keep` (posix paths relative to `top`); → [(path, bytes)]."""
    removed = []
    for cur, dirs, files in os.walk(top, topdown=False, followlinks=False):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(cur, d))]:
            p = os.path.join(cur, name)
            rel = Path(os.path.relpath(p, top)).as_posix()
            if os.path.islink(p) or rel not in keep:
                removed.append((p, _size(p)))
                os.unlink(p)
        if Path(cur) != Path(top) and not os.listdir(cur):
            os.rmdir(cur)
    return removed


def strip_angle_dir(angle_dir) -> list:
    """Remove everything under the angle dir except reply.md; → removed paths."""
    return [p for p, _ in _strip(Path(angle_dir), set(PROOF_FILES["angle"]))]


def _rounds(pr_dir: Path) -> list:
    found = []
    if pr_dir.is_dir():
        for p in pr_dir.iterdir():
            m = _ROUND_RE.match(p.name)
            if m and p.is_dir() and not p.is_symlink():
                found.append((int(m.group(1)), bool(m.group(2)), p))
    return [t[2] for t in sorted(found, key=lambda t: (t[0], t[1]))]


def latest_round(pr_dir):
    """The newest round dir of a PR dir (`r<N>.1` after `r<N>`), or None."""
    rounds = _rounds(Path(pr_dir))
    return rounds[-1] if rounds else None


def _terminal(rd: Path) -> bool:
    if os.path.isfile(rd / TAIL / "closed.json") and not os.path.islink(rd / TAIL / "closed.json"):
        return True
    try:
        env = json.loads((rd / TAIL / "envelope.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(env, dict) and env.get("terminal") is not None


def is_open(pr_dir) -> bool:
    """True when the latest round has neither a terminal envelope nor closed.json."""
    rd = latest_round(pr_dir)
    return rd is not None and not _terminal(rd)


def _repoint(node, old: str, new: str):
    if isinstance(node, str):
        if node == old:
            return new
        return node.replace(old + os.sep, new + os.sep)
    if isinstance(node, list):
        return [_repoint(v, old, new) for v in node]
    if isinstance(node, dict):
        return {k: _repoint(v, old, new) for k, v in node.items()}
    return node


def _repoint_manifest(rd: Path):
    mf = rd / "angles.json"
    actual = os.path.abspath(rd.parent.parent.parent)
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        old = data["paths"]["proof_root"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(old, str) or not old or os.path.realpath(old) == os.path.realpath(actual):
        return None
    old = old.rstrip(os.sep)
    tmp = mf.with_name(mf.name + ".tmp")
    tmp.write_text(json.dumps(_repoint(data, old, actual), indent=2), encoding="utf-8")
    os.replace(tmp, mf)
    print(f"proof_reap: repointed {mf}: {old} -> {actual}", file=sys.stderr)
    return {"manifest": str(mf), "old": old, "new": actual}


def _reap_round(rd: Path, latest: bool = False) -> list:
    removed = []
    tail_keep = PROOF_FILES["round"] + (PROOF_FILES["latest"] if latest else ())
    for e in sorted(rd.iterdir()):
        if e.is_symlink() or e.is_file():
            if e.is_symlink() or e.name != "angles.json":
                removed.append((str(e), _size(e)))
                e.unlink()
        elif e.name == TAIL:
            keep = {Path(f).relative_to(TAIL).as_posix() for f in tail_keep if f.startswith(TAIL + "/")}
            removed += _strip(e, keep)
        else:
            removed += _strip(e, set(PROOF_FILES["angle"]))
    return removed


def prune_to_proof(pr_dir) -> dict:
    """Reduce `<root>/rounds/<number>` to proof; refuse any other dir."""
    pr_dir = Path(pr_dir)
    if pr_dir.parent.name != "rounds" or not pr_dir.name.isdigit():
        raise ValueError(f"not a <root>/rounds/<number> dir: {pr_dir}")
    res = {"removed_files": 0, "removed_bytes": 0, "kept": 0, "open": None, "repointed": []}
    for rd in _rounds(pr_dir):
        info = _repoint_manifest(rd)
        if info:
            res["repointed"].append(info)
    latest = latest_round(pr_dir)
    if latest is not None and not _terminal(latest):
        res["open"] = latest.name
        return res
    for rd in _rounds(pr_dir):
        gone = _reap_round(rd, latest=rd == latest)
        res["removed_files"] += len(gone)
        res["removed_bytes"] += sum(b for _, b in gone)
        res["kept"] += sum(1 for _, _, fs in os.walk(rd) for _ in fs)
    return res


def close_and_prune(root, pr, *, closed_by) -> dict:
    """Close the latest round (`tail/closed.json`) then prune; the one place a round closes."""
    pr_dir = Path(root) / "rounds" / str(pr)
    rd = latest_round(pr_dir)
    if rd is None:
        print(f"proof_reap: no rounds dir {pr_dir}; nothing reaped (if the proof root "
              f"moved, pass the root proof_root.py prints)", file=sys.stderr)
        return {"missing": str(pr_dir), "removed_files": 0, "removed_bytes": 0}
    (rd / TAIL).mkdir(exist_ok=True)
    marker = rd / TAIL / "closed.json"
    tmp = marker.with_name(marker.name + ".tmp")
    tmp.write_text(json.dumps({"closed_by": closed_by,
                               "at": datetime.now(tz=timezone.utc).isoformat()}), encoding="utf-8")
    os.replace(tmp, marker)
    return prune_to_proof(pr_dir)


def _tree_bytes(root: Path) -> int:
    return sum(_size(os.path.join(c, f)) for c, _, fs in os.walk(root, followlinks=False) for f in fs)


def size_check(root, *, max_mb=5) -> dict:
    """Prune closed PR dirs when the root exceeds the cap; never removes proof."""
    root = Path(root)
    before = _tree_bytes(root)
    over = before > max_mb * 1024 * 1024
    res = {"before": before, "after": before, "over_cap": over, "open": [], "repointed": []}
    if over and (root / "rounds").is_dir():
        for pr in sorted((root / "rounds").iterdir()):
            if not (pr.is_dir() and not pr.is_symlink() and pr.name.isdigit()):
                continue
            r = prune_to_proof(pr)
            res["repointed"] += r["repointed"]
            if r["open"]:
                res["open"].append(str(pr))
        res["after"] = _tree_bytes(root)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="proof_reap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prune")
    p.add_argument("--pr", required=True)
    p.add_argument("--root")
    s = sub.add_parser("size-check")
    s.add_argument("--root")
    s.add_argument("--max-mb", type=float, default=5)
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else Path(proof_root.default_proof_root())
    try:
        if a.cmd == "prune":
            pr_dir = root / "rounds" / a.pr
            out = prune_to_proof(pr_dir)
            if out["open"]:
                print(f"proof_reap: skipped open round {pr_dir / out['open']} "
                      f"(no terminal yet); nothing reaped", file=sys.stderr)
        else:
            out = size_check(root, max_mb=a.max_mb)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
