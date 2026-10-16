"""fragility_items.py — the per-branch store of confirmed fragile items.

design: fragile-test-prevention (detailed-design-stages.md Part C4). Store:
`<git-dir>/three-pillars/fragility/items.json`: a `sources` list per branch bound to its
head, plus named waivers. Only blocking findings whose `fragility_class` is in
`FRAGILE_CLASSES` become items; an id hashes `source|path|class|anchor` (never the summary),
so a reworded re-report keeps its id and waiver. `anchor` is the lint rule id, else the
enclosing qualname at the line (`ast`, Python only), else `<module>`. `open_items` uses the
newest head's list (git ancestry, then `at`). Local state under the git dir, like the
ci-local stamp: drift, not forgery, is the residual. CLI: `list`, `waive [--scope
item|path-class]`, `replace` (`--branch`, `--root` shared).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from finding_fields import FRAGILE_CLASSES

SCHEMA = 1

def store_path(root) -> Path:
    """Where the store lives: under the git dir, never in the working tree."""
    out = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"],
                         capture_output=True, text=True, check=True).stdout.strip()
    git_dir = Path(out)
    git_dir = git_dir if git_dir.is_absolute() else (Path(root) / git_dir).resolve()
    return git_dir / "three-pillars" / "fragility" / "items.json"

def _load(root) -> dict:
    try:
        data = json.loads(store_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.CalledProcessError):
        data = None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        data = {"schema": SCHEMA, "branches": {}}
    data.setdefault("branches", {})
    return data

def _write(root, data: dict) -> None:
    path = store_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".items-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2); fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise

def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

def item_id(source: str, path: str, fragility_class: str, anchor: str) -> str:
    key = "|".join([source, path, fragility_class, anchor])
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]

def _start_line(line_range) -> int | None:
    """Start line of an int, an "a-b" string, or the `[start, end]` pair
    normalized-finding.v1 carries; anything else is None."""
    if isinstance(line_range, (list, tuple)):
        line_range = line_range[0] if line_range else None
        if not isinstance(line_range, int):
            return None
    if isinstance(line_range, bool):
        return None
    if isinstance(line_range, int):
        return line_range
    if not isinstance(line_range, str):
        return None
    first = line_range.split("-")[0].strip()
    return int(first) if first.isdecimal() else None

def _qualname_at_line(tree: ast.AST, line: int) -> str | None:
    """The innermost function/class enclosing `line`, dotted, or None outside any def. A
    def's span starts at its first decorator: `lineno` is the `def` line on 3.8+."""
    best = None
    def visit(node, prefix):
        nonlocal best
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                if start <= line <= getattr(child, "end_lineno", child.lineno):
                    best = f"{prefix}.{child.name}" if prefix else child.name
                    visit(child, best); continue
            visit(child, prefix)
    visit(tree, "")
    return best

def _anchor(root, head, *, rule_id, path, line) -> str:
    """The lint rule id, else the enclosing qualname (Python only), else `<module>`."""
    if rule_id:
        return rule_id
    qual = None
    if path and str(path).endswith(".py") and isinstance(line, int):
        try:
            text = subprocess.run(["git", "-C", str(root), "show", f"{head}:{path}"],
                                  capture_output=True, text=True, check=True).stdout
            qual = _qualname_at_line(ast.parse(text), line)
        except (OSError, subprocess.CalledProcessError, SyntaxError):
            pass
    return qual or "<module>"

def build_items(root, head, source: str, findings: list[dict]) -> list[dict]:
    items = []
    for f in findings:
        if not f.get("blocking"):
            continue
        fclass = f.get("fragility_class") or f.get("class")
        if fclass not in FRAGILE_CLASSES:
            continue
        path = f.get("path") or f.get("file") or ""
        line = f.get("line") if f.get("line") is not None else _start_line(f.get("line_range"))
        anchor = _anchor(root, head, rule_id=f.get("rule_id"), path=path, line=line)
        items.append({"id": item_id(source, path, fclass, anchor), "source": source,
                      "path": path, "line": line, "fragility_class": fclass,
                      "anchor": anchor, "summary": f.get("summary", "")})
    return items

def replace_source(root, branch: str, source: str, head, items: list[dict]) -> None:
    data = _load(root)
    br = data["branches"].setdefault(branch, {"sources": {}, "waivers": {}})
    br.setdefault("sources", {})[source] = {"head": head, "at": _now(), "items": list(items)}
    br.setdefault("waivers", {})
    _write(root, data)

def record_round(root, branch: str, head, findings: list[dict]) -> int:
    items = build_items(root, head, "pr-loop", findings)
    replace_source(root, branch, "pr-loop", head, items)
    return len(items)

def _newer(root, cand: dict, cur: dict) -> bool:
    """True when `cand` (a source record) supersedes `cur`, by git ancestry then `at`."""
    if cand["head"] != cur["head"]:
        try:
            rc = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                                 cur["head"], cand["head"]], capture_output=True).returncode
            if rc in (0, 1): return rc == 0
        except OSError:
            pass
    return cand.get("at", "") > cur.get("at", "")

def open_items(root, branch: str) -> list[dict]:
    br = _load(root)["branches"].get(branch)
    if not br or not br.get("sources"):
        return []
    sources = br["sources"]
    chosen = next(iter(sources))
    for name in sources:
        if name != chosen and _newer(root, sources[name], sources[chosen]):
            chosen = name
    return [i for i in sources[chosen]["items"] if i["id"] not in br.get("waivers", {})]

def waive(root, branch: str, target_id: str, *, by: str, reason: str, scope: str = "item"):
    """Refuses an empty `by`/`reason`; `path-class` scope also waives every item that matches."""
    if not by or not reason:
        raise ValueError("waive needs a non-empty by and reason")
    data = _load(root)
    br = data["branches"].setdefault(branch, {"sources": {}, "waivers": {}})
    br.setdefault("waivers", {})
    targets = {target_id}
    if scope == "path-class":
        all_items = [i for src in br.get("sources", {}).values() for i in src.get("items", [])]
        found = next((i for i in all_items if i["id"] == target_id), None)
        if found:
            key = (found["path"], found["fragility_class"])
            targets = {i["id"] for i in all_items if (i["path"], i["fragility_class"]) == key}
    at = _now()
    for tid in targets:
        br["waivers"][tid] = {"by": by, "reason": reason, "at": at}
    _write(root, data)

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fragility_items")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lst, wv, rep = (sub.add_parser(n) for n in ("list", "waive", "replace"))
    wv.add_argument("--id", required=True, dest="item_id")
    wv.add_argument("--by", required=True); wv.add_argument("--reason", required=True)
    wv.add_argument("--scope", choices=("item", "path-class"), default="item")
    for name in ("--source", "--head", "--findings"):
        rep.add_argument(name, required=True)
    for p in (lst, wv, rep):
        p.add_argument("--branch", required=True); p.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps(open_items(args.root, args.branch), indent=2)); return 0
    if args.cmd == "waive":
        try:
            waive(args.root, args.branch, args.item_id, by=args.by, reason=args.reason,
                 scope=args.scope)
        except ValueError as exc:
            print(f"fragility_items: {exc}", file=sys.stderr); return 2
        return 0
    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    items = build_items(args.root, args.head, args.source, findings)
    replace_source(args.root, args.branch, args.source, args.head, items)
    print(json.dumps(items, indent=2)); return 0

if __name__ == "__main__":
    sys.exit(main())
