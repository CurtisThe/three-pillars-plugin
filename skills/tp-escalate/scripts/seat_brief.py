"""seat_brief.py — seat stop builder (fleet context) + relay line.

design: fable-escalation 6.3. ``build_stop`` composes a ``question`` stop (or
keeps a given stop's source/signal/target) whose ``detail`` adds ``fleet``:
registry rows (fail-open ``[]``), the orchestration handoff path when present,
and the run's newest ruling — read where the run writes it: first the run's
worktree, else ``tp/<S>`` via git, else null. Never "this checkout".
``relay --id I`` prints the one relay line. Every seam (registry, porcelain,
git) is injectable. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))

import finalizer_ruling as fr  # noqa: E402
import inflight_registry as ir  # noqa: E402
import launch_design_run as ldr  # noqa: E402
import ruling_file as rf  # noqa: E402
from project_root import find_project_root  # noqa: E402

HANDOFF_REL = "three-pillars-docs/tp-designs/orchestration/handoff.md"
_RULING_NAME_RE = re.compile(r"[a-z0-9-]+-\d{8}-[0-9a-f]{6}\.md")
DECIDED_CAP = 240


def _default_registry_rows():
    """The live in-flight registry rows (JSON-safe dicts)."""
    return json.loads(ir.to_json(ir.build_registry()))["entries"]


def _default_porcelain():
    out = subprocess.run(["git", "worktree", "list", "--porcelain"],
                         capture_output=True, text=True, encoding="utf-8")
    return out.stdout if out.returncode == 0 else ""


def _default_git(root, args):
    out = subprocess.run(["git", "-C", str(root)] + list(args),
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(map(str, args))} failed")
    return out.stdout


def _parse_text(text):
    """``ruling_file.parse`` over a string (temp file, reused parser)."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(text)
        tmp = fh.name
    try:
        return rf.parse(tmp)
    finally:
        os.unlink(tmp)


def _pick_newest(parsed_iter, scope):
    """The parsed ruling whose front ``slug`` equals ``scope``, newest ``at``."""
    best = None
    for parsed in parsed_iter:
        front = parsed.get("front") or {}
        if front.get("slug") != scope:
            continue
        best_at = str((best.get("front") or {}).get("at", "")) if best else None
        if best is None or str(front.get("at", "")) > best_at:
            best = parsed
    return best


def _run_ruling(scope, porcelain_fn, git_fn):
    """Newest run ruling for ``scope``: worktree, else ``tp/<S>``, else None."""
    if scope == "seat":
        return None
    try:
        wt = ldr.find_worktree(porcelain_fn(), scope)
        if wt:
            base = Path(wt) / rf.RULINGS_REL
            parsed = (rf.parse(p) for p in sorted(base.glob("*.md"))
                      if _RULING_NAME_RE.fullmatch(p.name))
        else:
            listing = git_fn(["ls-tree", "--name-only",
                              f"tp/{scope}:{rf.RULINGS_REL}"]).split()
            parsed = (_parse_text(git_fn(["show", f"tp/{scope}:"
                                          f"{rf.RULINGS_REL}/{name}"]))
                      for name in listing if _RULING_NAME_RE.fullmatch(name))
        return _pick_newest(parsed, scope)
    except Exception:
        return None  # fail-open: the seat proceeds without a run ruling


def _fleet(scope, root, registry_fn, porcelain_fn, git_fn):
    try:
        registry = list(registry_fn())
    except Exception:
        registry = []
    handoff = Path(root) / HANDOFF_REL
    return {"registry": registry,
            "handoff": str(handoff) if handoff.is_file() else None,
            "run_ruling": _run_ruling(scope, porcelain_fn, git_fn)}


def build_stop(scope, *, question=None, kind=None, stop=None, root,
               registry_fn, porcelain_fn, git_fn):
    """The seat stop: a question stop, or ``stop`` kept + fleet detail."""
    fleet = _fleet(scope, root, registry_fn, porcelain_fn, git_fn)
    if stop is not None:
        if not isinstance(stop, dict):
            raise ValueError(f"--stop must be a JSON object, got "
                             f"{type(stop).__name__}")
        detail = stop.get("detail")
        detail = dict(detail) if isinstance(detail, dict) else {"original":
                                                                detail}
        detail["fleet"] = fleet
        return {"source": stop.get("source"), "signal": stop.get("signal"),
                "target": stop.get("target", scope), "detail": detail}
    return {"source": "question", "signal": kind, "target": scope,
            "detail": {"question": question, "fleet": fleet}}


def _decided(ruling):
    opts = [o for o in ruling.get("options") or [] if isinstance(o, dict)]
    pick = fr.chosen(opts)
    label = str(pick.get("label") or "") if pick else ""
    desc = str(pick.get("description") or "") if pick else ""
    decided = f"{label}: {desc}" if label and desc else label or desc
    if len(decided) > DECIDED_CAP:
        decided = decided[:DECIDED_CAP - 1] + "…"
    return decided


def relay_line(parsed):
    """The one seat relay line for a parsed ruling file (nested ruling ok)."""
    result = parsed.get("ruling") if isinstance(parsed.get("ruling"), dict) \
        else {}
    inner = result.get("ruling")
    ruling = inner if isinstance(inner, dict) else result
    rid = (parsed.get("front") or {}).get("id", "")
    return (f"Seat (under operator delegation): ruling {rid} resolved — "
            f"{_decided(ruling)}; apply it and continue.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="seat-brief", description="Seat escalation stop builder + relay.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="write the seat stop JSON")
    b.add_argument("--scope", required=True)
    b.add_argument("--question-file")
    b.add_argument("--kind")
    b.add_argument("--stop")
    b.add_argument("--out", required=True)
    r = sub.add_parser("relay", help="print the relay line for a ruling")
    r.add_argument("--id", required=True)
    args = parser.parse_args(argv)
    root = find_project_root() or Path.cwd()
    seams = dict(registry_fn=_default_registry_rows,
                 porcelain_fn=_default_porcelain,
                 git_fn=lambda gargs: _default_git(root, gargs))
    if args.cmd == "build":
        if args.stop:
            stop = json.loads(Path(args.stop).read_text(encoding="utf-8"))
            built = build_stop(args.scope, stop=stop, root=root, **seams)
        else:
            if not args.question_file or not args.kind:
                print("seat-brief: build needs --question-file and --kind, "
                      "or --stop", file=sys.stderr)
                return 2
            q_text = Path(args.question_file).read_text(encoding="utf-8")
            built = build_stop(args.scope, root=root,
                               question=q_text.strip(), kind=args.kind,
                               **seams)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(built, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(json.dumps({"out": str(out), "source": built["source"],
                          "signal": built["signal"],
                          "target": built["target"]}, ensure_ascii=False))
        return 0
    path = rf.find(root, args.id)
    if path is None:
        print(f"seat-brief: no ruling for id {args.id!r}", file=sys.stderr)
        return 2
    print(relay_line(rf.parse(path)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
