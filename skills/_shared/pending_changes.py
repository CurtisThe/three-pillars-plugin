"""pending_changes.py — the one reader helper for living-doc fragments.

design: living-doc-fragments, Task 1.2. Readers of the living docs (``/tp-guide``, session-restore,
design-learn's sibling scan) call ``summary`` so a merged design whose fragment is not yet compiled
into the docs still reads as done. Sits on ``changes_fragment.parse``; never raises on a bad file.

``list_fragments(root)`` -> ``Fragment`` list sorted by ``(date, slug)`` (an invalid fragment sorts
last and keeps its problems); ``pending_slugs`` -> slugs in that order; ``summary`` -> text, one line
per slug ``<slug> — merged, docs pending compile`` (or ``— in flight`` for the slug of the current
``tp/<slug>`` branch, or ``— invalid: <reason>``) followed by the ``+`` lines of its ``## Roadmap``
block and, for a Vision section, ``vision change awaiting operator``. CLI
``summary [--repo-root R] [--json]`` always exits 0; ``check [--repo-root R]`` prints one
``conflict: <slug>: <reason>`` line per unappliable fragment and exits 1 (0 when all fold). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import low_doc_parts  # noqa: E402
from changes_fragment import Fragment, format_problem, parse  # noqa: E402

CHANGES_DIR = "three-pillars-docs/changes"


def _read(path: Path) -> Fragment:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        frag = parse("", stem=path.stem)
        frag.slug = frag.slug or path.stem
        frag.problems.append(type(frag.problems[0])("file", None, f"unreadable: {exc}"))
        return frag
    frag = parse(text, stem=path.stem)
    if frag.slug is None:
        frag.slug = path.stem
    return frag


def list_fragments(repo_root) -> list[Fragment]:
    """Every fragment under ``changes/``, sorted by ``(date, slug)``; invalid ones are kept, not raised."""
    folder = Path(repo_root) / CHANGES_DIR
    if not folder.is_dir():
        return []
    frags = [_read(p) for p in sorted(folder.glob("*.md"))]
    return sorted(frags, key=lambda f: (f.date or "9999-99-99", f.slug or ""))


def pending_slugs(repo_root) -> list[str]:
    return [f.slug for f in list_fragments(repo_root)]


def without_compile_owned(repo_root, cites) -> list:
    """``cites`` minus the living-doc dead cites of a slug with a pending fragment.

    The post-merge docs compile repoints those (``reconcile_slug`` after the fold), and a design
    branch never edits a shared living doc, so the archive guards treat them as resolved.
    """
    pending = set(pending_slugs(repo_root))
    return [c for c in cites if not (c.kind == "living-doc" and c.slug in pending)]


def _current_slug(repo_root) -> str | None:
    """The ``<slug>`` of a checked-out ``tp/<slug>`` branch, else None (also outside git)."""
    try:
        out = subprocess.run(["git", "-C", str(repo_root), "symbolic-ref", "--short", "HEAD"],
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    branch = out.stdout.strip() if out.returncode == 0 else ""
    return branch[3:] if branch.startswith("tp/") else None


def _status(frag: Fragment, current: str | None) -> str:
    if frag.problems:
        return f"invalid: {format_problem(frag.problems[0])}"
    if frag.slug == current:
        return "in flight"
    return "merged, docs pending compile"


_DOCS = ("three-pillars-docs/product_roadmap.md", "three-pillars-docs/architecture.md",
         "three-pillars-docs/known_issues.md", "three-pillars-docs/known_issues_resolved.md")


def _dry_fold(repo_root, stop=None, docs=None):
    """(conflicts {slug: reason}) from folding the pending fragments in order onto the docs on disk.

    ``stop`` is a fragment: only the others sorting before it fold, and the docs so far are returned too.
    ``docs`` (rel path -> text), when given, replaces the on-disk doc texts.
    """
    import docs_fold  # lazy: it imports changes_fragment, which lazily imports this module

    rels = (*_DOCS, *low_doc_parts.parts_on_disk(Path(repo_root)))  # the Low parts, as the compile loads them
    if docs is None:
        docs = {rel: (Path(repo_root) / rel).read_text(encoding="utf-8")
                for rel in rels if (Path(repo_root) / rel).is_file()}
    else:
        docs = dict(docs)
    key = (stop.date or "9999-99-99", stop.slug or "") if stop is not None else None
    conflicts: dict[str, str] = {}
    for frag in list_fragments(repo_root):
        if key is not None and (frag.slug == stop.slug or (frag.date or "9999-99-99", frag.slug or "") >= key):
            continue
        if frag.problems or set(frag.sections) == {"Vision"}:
            continue
        try:
            docs = docs_fold.fold(docs, frag, pr=None, root=repo_root).docs
        except docs_fold.FoldError as exc:
            conflicts[frag.slug] = str(exc)
    return docs, conflicts


def unappliable(repo_root, *, docs=None) -> dict:
    """{slug: reason} for each pending fragment whose ``-``/``~`` anchor is gone from the docs."""
    return _dry_fold(repo_root, docs=docs)[1]


def folded_before(repo_root, fragment) -> dict:
    """The living docs with every pending fragment sorting before ``fragment`` folded in."""
    return _dry_fold(repo_root, stop=fragment)[0]


def _lines(frag: Fragment, current: str | None) -> list[str]:
    out = [f"{frag.slug} — {_status(frag, current)}"]
    if frag.problems:
        return out
    for block in frag.sections.get("Roadmap", []):
        out += [f"  + {op.text}" for op in block.ops if op.kind == "+"]
    if set(frag.sections) == {"Vision"}:
        out.append("  vision change awaiting operator")
    return out


def summary(repo_root) -> str:
    current = _current_slug(repo_root)
    conflicts = _dry_fold(repo_root)[1]
    lines: list[str] = []
    for frag in list_fragments(repo_root):
        lines += _lines(frag, current)
        if frag.slug in conflicts:
            lines.append(f"  conflict: {conflicts[frag.slug]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pending_changes.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("summary", help="print one line per pending fragment")
    cmd.add_argument("--repo-root", default=".")
    cmd.add_argument("--json", action="store_true")
    chk = sub.add_parser("check", help="exit 1 with a conflict line per fragment that no longer folds")
    chk.add_argument("--repo-root", default=".")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.cmd == "check":
        bad = unappliable(args.repo_root)
        for slug, reason in bad.items():
            print(f"conflict: {slug}: {reason}")
        return 1 if bad else 0
    if args.json:
        current = _current_slug(args.repo_root)
        rows = [{"slug": f.slug, "date": f.date, "status": _status(f, current)}
                for f in list_fragments(args.repo_root)]
        print(json.dumps({"fragments": rows}))
    else:
        text = summary(args.repo_root)
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
