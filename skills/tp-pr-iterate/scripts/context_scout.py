"""context_scout — the repo-only context scout: sources, agent and prompt.

design: local-role-routing (Task 5.1)

The scout reads only repo files, condenses what a reviewer needs into a short cited
block, and returns ``{"block": ..., "files": [...]}`` as its final message. The driver
pipes that reply to ``context_scout.py put --out-dir <out_dir>``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import dispatch_log  # noqa: E402
from strata_spawn import SLOT_LOSS_SUFFIX  # noqa: E402

SCOUT_AGENT = "tp-review-confirmer"  # Read/Grep/Glob/Bash, no Write: it writes only via `put`

SOURCES = (
    "design.md decisions and non-goals",
    "decisions.md",
    "linked seeds' \"Operator rulings\"",
    "three-pillars-docs/vision.md",
    "architecture decisions in three-pillars-docs/architecture.md",
    "known_issues.md / known_issues_low.md entries for touched files",
    "the PR body",
)

MAX_CITED_LINES = 25
NO_DESIGN = "no design dir found"
SLOT_LOST = "scout unavailable: slot-lost"
DEFAULT_HEADER = "context scout"
KNOWN_HEADERS = (NO_DESIGN, SLOT_LOST)
# A "cited line" names a repo file: a path-like token with an extension, optionally `:line`.
_CITE_PATH = re.compile(r"(?:[\w.\-]+/)+[\w.\-]+|[\w\-]+\.[A-Za-z]{1,5}\b")


def prompt(design_dir, base, head, out_dir) -> str:
    """The scout prompt for ``design_dir`` over ``base...head``, delivering into ``out_dir``."""
    resolved = dispatch_log.resolve_dir(design_dir)
    if resolved.is_dir():
        where = f"The design dir is {resolved}. Read it first."
    else:
        where = (f"Neither {design_dir} nor its completed-tp-designs twin exists: send the "
                 f"block header `{NO_DESIGN}` and cover only the other sources.")
    sources = "\n".join(f"- {s}" for s in SOURCES)
    return (
        "You are the context scout for a review round. Read repo files only; never edit "
        "anything.\n"
        f"{where}\n"
        f"Sources:\n{sources}\n"
        f"Condense what a reviewer needs into one block of at most {MAX_CITED_LINES} cited "
        "lines (each line cites its file).\n"
        f"Take `files` from `git diff --name-only {base}...{head}`.\n"
        'Reply in place of the default {"findings": [...]} reply with exactly '
        '{"block": ..., "files": [...]} as your final message. The driver delivers it with:\n'
        f"context_scout.py put --out-dir {out_dir} <<'EOF'\n"
        '{"block": ..., "files": [...]}\n'
        "EOF\n"
        f"{SLOT_LOSS_SUFFIX}"
    )


def trim(text, max_lines=MAX_CITED_LINES) -> str:
    """Condense a scout block: header line plus at most ``max_lines`` cited lines.

    A cited line is a non-empty line containing a repo file reference (a path such as
    ``a/b.py`` or ``file.md``, optionally with ``:line``); uncited lines are dropped. The
    header is the first line when it is a known header (``no design dir found``,
    ``scout unavailable: slot-lost``), else ``context scout``. Never gates, never raises.
    """
    try:
        lines = str(text or "").splitlines()
    except Exception:
        lines = []
    header = DEFAULT_HEADER
    if lines and lines[0].strip() in KNOWN_HEADERS:
        header = lines[0].strip()
        lines = lines[1:]
    cited = [ln for ln in lines if ln.strip() and _CITE_PATH.search(ln)]
    return "\n".join([header] + cited[:max(0, max_lines)])


def needs_refresh(meta, touched) -> bool:
    """True when the diff touches a file outside the last scout's ``files``.

    Fail-closed: a missing or malformed ``meta`` (not a dict with a list ``files``) means
    refresh.
    """
    try:
        files = meta.get("files") if isinstance(meta, dict) else None
        if not isinstance(files, list):
            return True
        return bool(set(touched or ()) - set(files))
    except Exception:
        return True


def _parse_payload(raw):
    """``(block, files)`` from the scout reply, or ``None`` when the payload is invalid."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    block, files = data.get("block"), data.get("files")
    if not isinstance(block, str) or not isinstance(files, list):
        return None
    if not all(isinstance(f, str) for f in files):
        return None
    return block, files


def _put(out_dir) -> int:
    parsed = _parse_payload(sys.stdin.read())
    if parsed is None:
        print("context_scout put: invalid payload", file=sys.stderr)
        return 2
    block, files = parsed
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pairs = (("rulings.md", trim(block)), ("rulings.json", json.dumps({"files": files})))
    temps = []
    try:
        for name, content in pairs:
            tmp = out / f".{name}.tmp.{os.getpid()}"
            temps.append((tmp, out / name))
            tmp.write_text(content, encoding="utf-8")
        for tmp, dest in temps:
            os.replace(tmp, dest)
    except OSError as exc:
        print(f"context_scout put: {exc}", file=sys.stderr)
        for tmp, _ in temps:
            try:
                tmp.unlink()
            except OSError:
                pass
        return 1
    return 0


def _needs_refresh(meta_path, touched) -> int:
    try:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    except Exception:
        meta = None
    names = [t for t in str(touched or "").split(",") if t]
    return 0 if needs_refresh(meta, names) else 1


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="context_scout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prompt")
    for flag in ("--design-dir", "--base", "--head", "--out-dir"):
        p.add_argument(flag, required=True)
    put = sub.add_parser("put")
    put.add_argument("--out-dir", required=True)
    nr = sub.add_parser("needs-refresh")
    nr.add_argument("--meta", required=True)
    nr.add_argument("--touched", default="")
    args = ap.parse_args(argv)
    if args.cmd == "prompt":
        print(prompt(args.design_dir, args.base, args.head, args.out_dir))
        return 0
    if args.cmd == "put":
        return _put(args.out_dir)
    return _needs_refresh(args.meta, args.touched)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
