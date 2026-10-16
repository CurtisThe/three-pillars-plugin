"""Two lesson layers for escalation lessons: repo file + user config file.

Stdlib-only. Entry format in both files:

    ### L<n> — <title>
    - applies when: <text>
    - lesson: <text>
    - sources: <a, b>
    - date: <YYYY-MM-DD>

Blocks that do not match are skipped by :func:`read`.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_REL = "three-pillars-docs/escalations/lessons.md"

_HEADING_RE = re.compile(r"^###\s+(L\d+)\s+—\s+(.+?)\s*$")
_ID_RE = re.compile(r"^###\s+L(\d+)\s+—", re.M)
_BULLET_RE = re.compile(r"^-\s+([a-z][a-z ]*):\s*(.*)$")

_FIELD_KEYS = {"applies when": "applies_when", "lesson": "lesson",
               "sources": "sources", "date": "date"}


def user_path(env=os.environ):
    """Path of the user lesson layer: ${CLAUDE_CONFIG_DIR:-~/.claude}/three-pillars/lessons.md."""
    base = env.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else Path.home() / ".claude"
    return root / "three-pillars" / "lessons.md"


def read(path):
    """Parse every well-formed lesson entry in `path`; [] when the file is missing."""
    path = Path(path)
    if not path.is_file():
        return []
    return _parse(path.read_text(encoding="utf-8"))


def add(path, proposal, source_id, today, cap=60):
    """Append a lesson entry from `proposal`; refuses contradictions, duplicates, cap."""
    path = Path(path)
    contradicts = proposal.get("contradicts") or []
    if contradicts:
        return {"status": "refused-contradiction",
                "docs_update": _docs_update_text(contradicts)}
    text = " ".join(str(proposal.get("text", "")).split())
    if not text:
        return {"status": "empty"}
    entries = read(path)
    if len(entries) >= cap:
        return {"status": "cap-reached"}
    for entry in entries:
        if " ".join(entry["lesson"].split()) == text:
            return {"status": "duplicate", "id": entry["id"]}
    lesson_id = "L%d" % (_next_id(path), )
    block = _entry_block(lesson_id, _title(text),
                         " ".join(str(proposal.get("applies_when", "")).split()),
                         text, source_id, today)
    if path.is_file():
        content = path.read_text(encoding="utf-8")
        path.write_text(content + "\n" + block, encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Lessons\n\n" + block, encoding="utf-8")
    return {"status": "added", "id": lesson_id}


def remove(path, lesson_id, source_id):
    """Delete the entry block for `lesson_id`; unchanged file when unknown.

    The block ends at the next `### L<n> —` heading, the next level-1 or
    level-2 heading, or EOF — so trailing non-lesson sections survive.
    """
    path = Path(path)
    if not path.is_file():
        return {"status": "not-found", "id": lesson_id}
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^###\s+" + re.escape(lesson_id) +
        r"\s+—.*?(?=^###\s+L\d+\s+—|^#{1,2}\s|\Z)",
        re.S | re.M)
    new_text, count = pattern.subn("", text)
    if count == 0:
        return {"status": "not-found", "id": lesson_id}
    path.write_text(new_text, encoding="utf-8")
    return {"status": "removed", "id": lesson_id}


def _docs_update_text(contradicts):
    parts = []
    for item in contradicts:
        parts.append("%s § %s: \"%s\"" % (item.get("doc", "?"),
                                          item.get("section", "?"),
                                          item.get("quote", "")))
    return ("Refused: the lesson contradicts project docs. Update them first "
            "with /tp-docs-update, then re-propose. Contradicted: "
            + "; ".join(parts))


def _next_id(path):
    if not path.is_file():
        return 1
    nums = [int(m) for m in _ID_RE.findall(path.read_text(encoding="utf-8"))]
    return (max(nums) + 1) if nums else 1


def _title(text):
    if len(text) <= 60:
        return text
    cut = text[:60]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip()


def _entry_block(lesson_id, title, applies_when, lesson, sources, date):
    return ("### %s — %s\n"
            "- applies when: %s\n"
            "- lesson: %s\n"
            "- sources: %s\n"
            "- date: %s\n"
            % (lesson_id, title, applies_when, lesson, sources, date))


def _parse(text):
    entries = []
    current = None
    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            if current is not None:
                entries.append(current)
            current = {"id": heading.group(1), "title": heading.group(2)}
            continue
        if current is None:
            continue
        bullet = _BULLET_RE.match(line.strip())
        if not bullet:
            continue
        key = _FIELD_KEYS.get(bullet.group(1))
        if key is None:
            continue
        value = bullet.group(2).strip()
        if key == "sources":
            current[key] = [s.strip() for s in value.split(",") if s.strip()]
        else:
            current[key] = value
    if current is not None:
        entries.append(current)
    return [e for e in entries if all(k in e for k in
            ("id", "title", "applies_when", "lesson", "sources", "date"))]


def main(argv=None) -> int:
    """CLI over :func:`add` / :func:`remove`; prints the return dict as JSON.

    ``add --path P --proposal-file F --source S --today D [--cap N]`` reads the
    proposal JSON from ``F``; ``remove --path P --id L --source S`` deletes an
    entry. ``--path`` defaults to ``REPO_REL`` under cwd. A contradiction is
    printed (exit 0), never forced in; argparse errors exit 2.
    """
    parser = argparse.ArgumentParser(
        prog="lessons", description="Escalation lesson layers.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="apply an add proposal")
    a.add_argument("--path")
    a.add_argument("--proposal-file", required=True)
    a.add_argument("--source", required=True)
    a.add_argument("--today", required=True)
    a.add_argument("--cap", type=int, default=60)
    r = sub.add_parser("remove", help="delete a lesson entry")
    r.add_argument("--path")
    r.add_argument("--id", required=True)
    r.add_argument("--source", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse errors exit 2; --help exits 0
        return int(exc.code or 0)
    path = Path(args.path) if args.path else Path.cwd() / REPO_REL
    if args.cmd == "add":
        proposal = json.loads(Path(args.proposal_file).read_text(encoding="utf-8"))
        result = add(path, proposal, args.source, args.today, cap=args.cap)
    else:
        result = remove(path, args.id, args.source)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
