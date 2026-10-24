"""changes_fragment.py — the living-doc fragment grammar: ``parse`` + ``validate`` + the CLI.

design: living-doc-fragments, Task 1.1. A design branch never edits a shared living doc; its doc
changes live in ``three-pillars-docs/changes/<slug>.md`` (grammar: design §Entities and
``skills/_shared/living-doc-fragments.md``). Frontmatter: ``slug`` (= file stem, ``[a-z0-9-]+``, never
``docs-compile``), ``kind`` (design|spike), ``date``, optional ``learned`` (dates are YYYY-MM-DD).
Then only the ``SECTIONS`` headings, each at most once; frontmatter alone is a valid fragment.
``## Roadmap`` / ``## Architecture`` hold ``### <heading in that doc>`` blocks of ``+ <line>`` (insert)
and ``- <line>`` (remove the exact doc line, so the doc line ``- old row`` is ``- - old row``).

``parse`` never raises: a malformed shape is a ``Problem`` in ``Fragment.problems``. ``validate``
adds, with a ``repo_root``, each ``###`` heading and ``-`` line absent from the live target doc.
CLI ``validate <path> [--repo-root R] [--json] [--require-learned]``: exit 0 ok, 1 problems (each
printed ``changes_fragment: <section>: <reason>``; a missing file is ``file: missing``), 2 usage.
Stdlib only.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from number_issues import DEFINED  # noqa: E402  (the one placeholder-heading regex)

SECTIONS = ("Roadmap", "Architecture", "Known issues — add", "Known issues — resolve", "Vision")
TARGET_DOCS = {"Roadmap": "three-pillars-docs/product_roadmap.md",
               "Architecture": "three-pillars-docs/architecture.md"}
KINDS = ("design", "spike")
RESERVED_SLUGS = ("docs-compile",)
FRONTMATTER_KEYS = ("slug", "kind", "date", "learned")

_SLUG = re.compile(r"^[a-z0-9-]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RESOLVE = re.compile(r"^- ([HML][0-9]+):[ \t]*(.*)$")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*$")
_VERBATIM = ("Known issues — add", "Vision")  # sections whose text may hold fenced code


@dataclass
class Op:
    kind: str    # "+" insert, "-" remove
    text: str    # the line text after the two-character prefix
    line: int    # 1-based line in the fragment file


@dataclass
class Block:
    heading: str  # ### text; the ID for a resolve line; "" for Vision
    line: int
    ops: list[Op] = field(default_factory=list)    # Roadmap / Architecture
    body: list[str] = field(default_factory=list)  # add / resolve / Vision


@dataclass
class Problem:
    section: str
    line: int | None
    reason: str


@dataclass
class Fragment:
    slug: str | None = None
    kind: str | None = None
    date: str | None = None
    learned: str | None = None
    sections: dict[str, list[Block]] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)


def format_problem(problem: Problem) -> str:
    where = f"line {problem.line}: " if problem.line else ""
    return f"changes_fragment: {problem.section}: {where}{problem.reason}"


def _real_date(value: str) -> bool:
    try:
        return bool(_DATE.match(value)) and bool(datetime.date.fromisoformat(value))
    except ValueError:
        return False


def _parse_frontmatter(lines: list[str], frag: Fragment, stem: str | None) -> int:
    """Fill ``frag`` from the leading ``---`` block; return the index of the first body line."""
    def problem(line, reason):
        frag.problems.append(Problem("frontmatter", line, reason))

    if not lines or lines[0].strip() != "---":
        problem(1, "missing: the file must open with a --- block holding slug, kind and date")
        return 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        problem(1, "unclosed: no closing --- line")
        return len(lines)
    seen: dict[str, int] = {}
    for ln, raw in enumerate(lines[1:end], 2):
        key, sep, value = raw.partition(":")
        key = key.strip()
        if not raw.strip():
            continue
        if not sep or key not in FRONTMATTER_KEYS:
            problem(ln, f"{key or raw.strip()}: unknown key (allowed: {', '.join(FRONTMATTER_KEYS)})")
        elif key in seen:
            problem(ln, f"{key}: duplicate key")
        else:
            seen[key] = ln
            setattr(frag, key, value.strip())
    for key in ("slug", "kind", "date"):
        if key not in seen:
            problem(None, f"{key}: missing")
    for key, ln in seen.items():
        reason = _bad_value(key, getattr(frag, key), stem)
        if reason:
            problem(ln, f"{key}: {reason}")
    return end + 1


def _bad_value(key: str, value: str, stem: str | None) -> str | None:
    """Why ``value`` is wrong for frontmatter ``key``, or None when it is fine."""
    if key == "slug":
        if not _SLUG.match(value):
            return "must match [a-z0-9-]+"
        if value in RESERVED_SLUGS:
            return f"{value} is reserved for the compile branch"
        if stem is not None and value != stem:
            return f"must equal the file stem '{stem}'"
    elif key == "kind":
        if value not in KINDS:
            return f"must be one of {', '.join(KINDS)}"
    elif not _real_date(value):
        return "must be a real YYYY-MM-DD date"
    return None


class _Body:
    """Line-at-a-time reader of the sections after the frontmatter."""

    def __init__(self, frag: Fragment):
        self.frag = frag
        self.name: str | None = None   # current ``## `` heading text; None before the first
        self.keep = False              # False for an unknown or duplicate section: lines are skipped
        self.block: Block | None = None
        self.fence: int | None = None  # line of the opening ``` while inside a fenced block

    def problem(self, line: int, reason: str, section: str | None = None) -> None:
        self.frag.problems.append(Problem(section or self.name or "preamble", line, reason))

    def feed(self, ln: int, line: str) -> None:
        if self.fence is None and line.startswith("## "):
            self.close()
            self.open(line[3:].strip(), ln)
            return
        if self.name is None:
            if line.strip():
                self.problem(ln, "text outside any ## section")
            return
        if not self.keep:
            return
        if self.name in _VERBATIM:
            self._track_fence(ln, line)
        handler = {"Roadmap": self._ops_line, "Architecture": self._ops_line,
                   "Known issues — add": self._add_line, "Known issues — resolve": self._resolve_line,
                   "Vision": self._vision_line}[self.name]
        handler(ln, line)

    def open(self, name: str, ln: int) -> None:
        self.name, self.block = name, None
        error = (f"unknown section (allowed: {', '.join(SECTIONS)})" if name not in SECTIONS
                 else "duplicate section" if name in self.frag.sections else None)
        self.keep = error is None
        if error:
            self.problem(ln, error)
        else:
            self.frag.sections[name] = []

    def close(self) -> None:
        if self.fence is not None:
            self.problem(self.fence, "unclosed code fence")
            self.fence = None
        if self.name in self.frag.sections and self.keep:
            for block in self.frag.sections[self.name]:
                while block.body and not block.body[-1].strip():
                    block.body.pop()

    def _track_fence(self, ln: int, line: str) -> None:
        if line.lstrip().startswith("```"):
            self.fence = None if self.fence else ln

    def _ops_line(self, ln: int, line: str) -> None:
        if not line.strip():
            return
        if line.startswith("### "):
            heading = line[4:].strip()
            self.block = Block(heading, ln)
            if heading:
                self.frag.sections[self.name].append(self.block)
            else:
                self.problem(ln, "empty ### heading")  # the throwaway block swallows its ops
        elif line[:2] in ("+ ", "- "):
            if self.block is None:
                self.problem(ln, "+ / - line before any ### heading")
            else:
                self.block.ops.append(Op(line[0], line[2:], ln))
        else:
            self.problem(ln, "line must start with '### ', '+ ' or '- '")

    def _add_line(self, ln: int, line: str) -> None:
        if self.fence is None and line.startswith("### "):
            self.block = Block(line[4:].strip(), ln)
            if DEFINED.match(line):
                self.frag.sections[self.name].append(self.block)
            else:
                self.problem(ln, "heading must be a placeholder: ### <H|M|L>-new-<slug>: title")
            return
        if self.block is None:
            if line.strip():
                self.problem(ln, "text before the first ### block")
            return
        self.block.body.append(line)

    def _resolve_line(self, ln: int, line: str) -> None:
        if not line.strip():
            return
        match = _RESOLVE.match(line)
        if not match:
            self.problem(ln, "line must be '- <ID>: <note>' with a numbered ID (H|M|L plus digits)")
            return
        note = match.group(2).rstrip()
        self.frag.sections[self.name].append(Block(match.group(1), ln, body=[note] if note else []))

    def _vision_line(self, ln: int, line: str) -> None:
        if self.block is None:
            if not line.strip():
                return
            self.block = Block("", ln)
            self.frag.sections[self.name].append(self.block)
        self.block.body.append(line)


def parse(text: str, *, stem: str | None = None) -> Fragment:
    """Parse fragment ``text``; ``stem`` (the file name without ``.md``) must equal ``slug`` when given."""
    lines = text.splitlines()
    frag = Fragment()
    start = _parse_frontmatter(lines, frag, stem)
    body = _Body(frag)
    for ln, line in enumerate(lines[start:], start + 1):
        body.feed(ln, line)
    body.close()
    return frag


def _check_targets(fragment: Fragment, root: Path, overlay: dict | None = None) -> list[Problem]:
    problems: list[Problem] = []
    for section, rel in TARGET_DOCS.items():
        blocks = fragment.sections.get(section)
        if not blocks:
            continue
        try:
            text = overlay[rel] if overlay and rel in overlay else (root / rel).read_text(encoding="utf-8")
            doc_lines = text.splitlines()
        except (OSError, UnicodeDecodeError):
            problems.append(Problem(section, None, f"target doc is missing or unreadable: {rel}"))
            continue
        headings = {m.group(1) for m in map(_HEADING.match, doc_lines) if m}
        present = set(doc_lines)
        for block in blocks:
            if block.heading not in headings:
                problems.append(Problem(section, block.line, f"no heading '{block.heading}' in {rel}"))
            for op in block.ops:
                if op.kind == "-" and op.text not in present:
                    problems.append(Problem(section, op.line, f"no line in {rel} matches '{op.text}'"))
    return problems


def validate(fragment: Fragment, *, repo_root=None, require_learned: bool = False) -> list[Problem]:
    """Every problem with ``fragment``: its grammar, then (with ``repo_root``) its targets in the live docs."""
    problems = list(fragment.problems)
    for block in fragment.sections.get("Roadmap", []):
        if block.heading == "Recent completions":
            problems += [Problem("Roadmap", op.line, "Recent completions uses 'Done — {pr}'")
                         for op in block.ops if op.kind == "+" and "Completion PR pending" in op.text]
    if repo_root is not None:
        import pending_changes  # lazy: it imports this module

        problems += _check_targets(fragment, Path(repo_root), pending_changes.folded_before(repo_root, fragment))
    if require_learned and fragment.learned is None:
        problems.append(Problem("learned", None, "missing"))
    return problems


def _problems_for_path(path: Path, repo_root, require_learned: bool) -> list[Problem]:
    if not path.is_file():
        return [Problem("file", None, "missing")]
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [Problem("file", None, "not valid UTF-8")]
    except OSError as exc:
        return [Problem("file", None, f"unreadable: {exc.strerror}")]
    fragment = parse(text, stem=path.stem)
    return validate(fragment, repo_root=repo_root, require_learned=require_learned)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="changes_fragment.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("validate", help="check one fragment file against the grammar")
    check.add_argument("path", help="three-pillars-docs/changes/<slug>.md")
    check.add_argument("--repo-root", help="also check each ### heading and - line against the live docs")
    check.add_argument("--json", action="store_true", help="print {ok, problems} as JSON")
    check.add_argument("--require-learned", action="store_true", help="a missing `learned:` key is a problem")
    return parser


def main(argv=None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.repo_root is not None and not Path(args.repo_root).is_dir():
        print(f"changes_fragment: --repo-root is not a directory: {args.repo_root}", file=sys.stderr)
        return 2
    problems = _problems_for_path(Path(args.path), args.repo_root, args.require_learned)
    if args.json:
        print(json.dumps({"ok": not problems, "problems": [asdict(p) for p in problems]}))
    else:
        for problem in problems:
            print(format_problem(problem))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # section names hold an em dash
    sys.exit(main())
