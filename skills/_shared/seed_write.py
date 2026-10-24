#!/usr/bin/env python3
"""seed_write.py — the one writer for a new ``seed.md`` (design: weight-class-lean-default).

A seed is ``<repo>/three-pillars-docs/tp-designs/<slug>/seed.md``: a flat frontmatter block
(``slug``, ``weight-class``, the four axes, ``status: seed``, ``seeded``, ``source``) and the
sections ``## Problem``, ``## Direction``, ``## Open questions``, ``## Consumer-repo behaviour``.
``/tp-seed`` and ``run_retro_file.write_seed`` both build the frontmatter with ``frontmatter``,
so every seed carries a ``weight-class``.

* ``write_new`` writes a seed; it refuses an existing slug (``FileExistsError``) and any bad
  slug, class or axis value (``ValueError``) before a byte is written.
* ``estimated-lines`` (optional, ``--estimated-lines N``) is a positive integer line estimate.
* ``amend`` appends ``## Part N`` to an existing seed and returns N (2 or more).
* ``similar`` lists up to 3 open seeds (``status: seed``) ranked by word overlap between the
  query and each seed's slug plus its ``## Problem`` text; a directory name that is not a safe
  slug is skipped.

CLI: ``new``, ``amend`` and ``similar`` (see ``--help``). Each text can come inline or from a
file read verbatim (``--problem-file``, ``--direction-file``, ``--open-questions-file``,
``--consumer-file`` on ``new``; ``--text-file`` on ``amend`` and ``similar``); giving both forms
of one field is refused. Exit 1 and one stderr line on a refusal. Stdlib only, plus the sibling ``weight_class`` module.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

from weight_class import VALID_CLASSES, parse_frontmatter  # noqa: E402

SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # a slug is a directory name: no path chars
AXIS_KEYS = ("risk", "blast-radius", "reversibility", "novelty")
AXIS_LEVELS = ("low", "medium", "high")
SECTIONS = ("Problem", "Direction", "Open questions", "Consumer-repo behaviour")
DESIGNS, ARCHIVE = "tp-designs", "completed-tp-designs"
LIMIT = 3
_PART = re.compile(r"^## Part (\d+)\b", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the and for with that this from are was not but you all can has have its "
                  "into when then than also any one use used new".split())


def _line(value) -> str:
    """A frontmatter value is one line: newlines fold to spaces."""
    return re.sub(r"\s*\n\s*", " ", str(value))


def frontmatter(*, weight_class="light", slug=None, axes=None, status="seed", seeded=None,
                source=None, extra=None) -> str:
    """The fenced frontmatter block, keys in a fixed order: ``slug``, ``weight-class``, the
    axes present, ``status``, ``seeded``, ``source``, then ``extra`` in the caller's order.
    A ``None`` value is skipped. Pure: it validates nothing and writes nothing."""
    pairs = [("slug", slug), ("weight-class", weight_class)]
    pairs += [(key, (axes or {}).get(key)) for key in AXIS_KEYS]
    pairs += [("status", status), ("seeded", seeded), ("source", source)]
    pairs += list((extra or {}).items())
    body = "".join(f"{key}: {_line(value)}\n" for key, value in pairs if value is not None)
    return f"---\n{body}---\n"


def seed_path(repo, slug: str) -> Path:
    return Path(repo) / "three-pillars-docs" / DESIGNS / slug / "seed.md"


def _check_slug(slug) -> None:
    if not SAFE_SLUG.fullmatch(slug or ""):
        raise ValueError(f"unsafe slug {slug!r}: use lowercase words joined by hyphens")


def _check_estimate(value) -> int:
    ok = (isinstance(value, int) and not isinstance(value, bool)) or (
        isinstance(value, str) and value.isascii() and value.isdigit())
    if not ok or int(value) <= 0:
        raise ValueError(f"estimated-lines must be a positive integer, got {value!r}")
    return int(value)


def _check(slug: str, weight_class: str, axes) -> None:
    _check_slug(slug)
    if weight_class not in VALID_CLASSES:
        raise ValueError(f"invalid weight class {weight_class!r}; expected one of {VALID_CLASSES}")
    if axes:
        if set(axes) != set(AXIS_KEYS):
            raise ValueError(f"give all four axes ({', '.join(AXIS_KEYS)}) or none")
        for key, value in axes.items():
            if value not in AXIS_LEVELS:
                raise ValueError(f"bad axis {key}: {value!r}; expected one of {AXIS_LEVELS}")


def write_new(slug: str, *, repo, weight_class: str, source: str, axes=None, title=None,
              problem="", direction="", open_questions="", consumer="", seeded=None,
              estimated_lines=None) -> Path:
    """Write ``seed.md`` for ``slug`` under ``repo`` and return its path. Refuses a slug that is
    already a seed, an active design or an archived design."""
    estimate = None if estimated_lines is None else _check_estimate(estimated_lines)
    _check(slug, weight_class, axes)
    path = seed_path(repo, slug)
    docs = Path(repo) / "three-pillars-docs"
    taken = (path, docs / DESIGNS / slug / "design.md", docs / ARCHIVE / slug)
    if any(p.exists() for p in taken):
        raise FileExistsError(f"slug {slug!r} is taken: {next(p for p in taken if p.exists())}")
    head = frontmatter(weight_class=weight_class, slug=slug, axes=axes or None,
                       seeded=seeded or datetime.date.today().isoformat(), source=source,
                       extra=None if estimate is None else {"estimated-lines": estimate})
    texts = (problem, direction, open_questions, consumer)
    body = "".join(f"## {name}\n\n" + (f"{str(text).strip()}\n\n" if str(text).strip() else "")
                   for name, text in zip(SECTIONS, texts))
    heading = title or f"Seed: {slug.replace('-', ' ')}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{head}# {heading}\n\n{body}".rstrip("\n") + "\n", encoding="utf-8")
    return path


def amend(slug: str, text: str, *, repo) -> int:
    """Append ``## Part N`` with ``text`` to the existing seed and return N (the original seed
    is Part 1, so the first amendment is Part 2)."""
    _check_slug(slug)
    path = seed_path(repo, slug)
    if not path.is_file():
        raise FileNotFoundError(f"no seed for {slug!r}: {path}")
    old = path.read_text(encoding="utf-8")
    part = max([int(n) for n in _PART.findall(old)] + [1]) + 1
    path.write_text(f"{old.rstrip()}\n\n## Part {part}\n\n{str(text).strip()}\n", encoding="utf-8")
    return part


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def _problem(text: str) -> str:
    match = re.search(r"^## Problem\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def similar(text: str, *, repo, limit: int = LIMIT) -> list:
    """Up to ``limit`` ``(slug, shared word count)`` pairs for open seeds that share words with
    ``text``, best first (ties by slug). A closed seed (``status`` other than ``seed``) is skipped."""
    query = _words(text)
    found = []
    for seed in sorted((Path(repo) / "three-pillars-docs" / DESIGNS).glob("*/seed.md")):
        if not SAFE_SLUG.fullmatch(seed.parent.name):
            continue
        try:
            body = seed.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if parse_frontmatter(body).get("status") != "seed":
            continue
        score = len(query & (_words(seed.parent.name) | _words(_problem(body))))
        if score:
            found.append((seed.parent.name, score))
    return sorted(found, key=lambda pair: (-pair[1], pair[0]))[:limit]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seed_write.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="write a new seed.md")
    new.add_argument("slug")
    new.add_argument("--class", dest="weight_class", default="light")
    for key in AXIS_KEYS:
        new.add_argument(f"--{key}", choices=AXIS_LEVELS)
    new.add_argument("--source", required=True)
    new.add_argument("--title")
    new.add_argument("--problem")
    new.add_argument("--direction")
    new.add_argument("--open-questions")
    new.add_argument("--consumer")
    for name in ("problem", "direction", "open-questions", "consumer"):
        new.add_argument(f"--{name}-file", dest=f"{name.replace('-', '_')}_file")
    new.add_argument("--seeded")
    new.add_argument("--estimated-lines", dest="estimated_lines", default=None)
    amd = sub.add_parser("amend", help="append a ## Part N to an existing seed")
    amd.add_argument("slug")
    amd.add_argument("text", nargs="?")
    amd.add_argument("--text-file", dest="text_file")
    sim = sub.add_parser("similar", help="list up to 3 open seeds close to the text")
    sim.add_argument("text", nargs="?")
    sim.add_argument("--text-file", dest="text_file")
    for sp in (new, amd, sim):
        sp.add_argument("--repo", default=".")
    return parser


def _text(inline, path, name) -> str:
    """The text for ``--name``: inline, or the verbatim contents of ``--name-file``."""
    if inline is not None and path:
        raise ValueError(f"give --{name} or --{name}-file, not both")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return inline or ""


def _required_text(args) -> str:
    if not (args.text or args.text_file):
        raise ValueError("give the text or --text-file")
    return _text(args.text, args.text_file, "text")


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "new":
            texts = {n: _text(getattr(args, n.replace("-", "_")),
                              getattr(args, n.replace("-", "_") + "_file"), n)
                     for n in ("problem", "direction", "open-questions", "consumer")}
            axes = {k: getattr(args, k.replace("-", "_")) for k in AXIS_KEYS}
            path = write_new(
                args.slug, repo=args.repo, weight_class=args.weight_class, source=args.source,
                axes=axes if any(axes.values()) else None, title=args.title,
                problem=texts["problem"], direction=texts["direction"],
                open_questions=texts["open-questions"], consumer=texts["consumer"],
                seeded=args.seeded,
                estimated_lines=args.estimated_lines)
            print(path)
        elif args.command == "amend":
            print(f"amended {args.slug}: Part {amend(args.slug, _required_text(args), repo=args.repo)}")
        else:
            for slug, score in similar(_required_text(args), repo=args.repo):
                print(f"{slug} {score}")
    except (OSError, ValueError) as exc:
        print(f"seed_write: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
