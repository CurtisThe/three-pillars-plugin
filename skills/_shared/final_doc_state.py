"""final_doc_state — close a completed design's living-doc state, and check it.

`close(repo_root, slug)` is `/tp-design-complete` step 6f: it moves the slug's
Design Inventory rows to the roadmap archive (`inventory_archive.move_completed`),
then flips the slug's canonical `Completion PR pending` tokens to the number-free
`Done (completion PR)` (`pending_flip.flip`) across the living docs and their
archives. Mover first, so the archived copy of the row is flipped too. Both steps
are idempotent, and `close` touches only the six living-doc files.

`check(repo_root, slug)` is the read-only self-check (6f after the commit, and
`/tp-post-merge` step 6): it reports what is still unfinished as `rows` (live
inventory rows), `pending` (tokens `pending_flip.scan` still finds), `cites`
(dead `tp-designs/{slug}/` cites in living docs, exactly the scope of
`reconcile_docs.py --archive-cites`) and the `fix` lines that clear them. A
legacy-form token, an unattributable one, two tokens on one line, or an
undecodable living doc (`<file>:0`) cannot be fixed by a tool, so they get a
`hand-edit <file>:<line>` line.

CLI: `close|check --slug S [--repo-root R] [--json]`. Exit 0 clean, 1 on a
mover-verifier refusal (`close`) or drift (`check`), 2 on usage error.

design: design-complete-final-doc-state
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import citation_liveness
import inventory_archive
import living_doc_archive
import living_doc_guard
import low_doc_parts
import pending_changes
import pending_flip

TOOLS = 'python3 "$TP_ROOT"/skills/_shared'


def fragment_mode(repo_root, slug: str) -> bool:
    """True when `three-pillars-docs/changes/<slug>.md` exists: the docs compile owns the close."""
    return slug in pending_changes.pending_slugs(repo_root)


def close(repo_root, slug: str, *, fragment_aware: bool = True) -> dict:
    """Move the slug's inventory rows, then flip its pending tokens, in one call.

    Returns `{moved, flipped, skipped, paths, refused}`: `skipped` is
    `pending_flip.flip`'s list verbatim, `paths` the files written, `refused` the
    mover verifier's problem text (then nothing is written and nothing flips).
    `fragment_aware` (design: living-doc-fragments): with a fragment for `slug` and
    `fragment_aware` true, nothing is written and the result is `{mode: "fragment", ...}`; the
    compile passes False because it is the one writer that closes a folded fragment's slug.
    """
    root = Path(repo_root)
    if fragment_aware and fragment_mode(root, slug):
        return {"mode": "fragment", "moved": 0, "flipped": 0, "skipped": [], "paths": [], "refused": None}
    moved = inventory_archive.move_completed(root, slug, apply=True)
    if moved.reason and moved.reason.startswith("verifier:"):
        return {"moved": 0, "flipped": 0, "skipped": [], "paths": [], "refused": moved.reason}
    edits, skipped = pending_flip.flip(root, slug, None, apply=True)
    paths = {e.path for e in edits}
    if moved.moved:
        paths |= {inventory_archive.LIVE_REL,
                  living_doc_archive.archive_for(inventory_archive.LIVE_REL)}
    return {"moved": moved.moved, "flipped": len(edits), "skipped": skipped,
            "paths": sorted(paths), "refused": None}


def _cites(root: Path, slug: str) -> list[dict]:
    """Dead living-doc cites of `slug`: `reconcile_docs.py --archive-cites`' own detector."""
    found: dict[tuple[str, int], dict] = {}
    for c in citation_liveness.dead_design_cites(root):
        if c.slug == slug and c.kind == "living-doc" and (c.path, c.line) not in found:
            lines = (root / c.path).read_text(encoding="utf-8", errors="replace").splitlines()
            found[(c.path, c.line)] = {"file": c.path, "line": c.line, "text": lines[c.line - 1]}
    return list(found.values())


def _fix_lines(root: Path, slug: str, rows, pending, cites) -> list[str]:
    """The commands (and hand edits) that clear `rows`, `pending` and `cites`."""
    per_line = Counter((p["file"], p["line"]) for p in pending)
    _, blocked = pending_flip.flip(root, slug, None, apply=False)  # tokens flip would skip
    blocked_lines = {(s["file"], s["line_no"]) for s in blocked}
    mechanical = any(
        p["form"] == "canonical" and p["owner"] == slug and per_line[(p["file"], p["line"])] == 1
        and (p["file"], p["line"]) not in blocked_lines for p in pending)
    fix = []
    if rows:
        fix.append(f"{TOOLS}/inventory_archive.py --slug {slug} --apply --json")
    if mechanical:
        fix.append(f"{TOOLS}/reconcile_docs.py --slug {slug} --pre-merge --apply --json")
    if cites:
        fix.append(f"{TOOLS}/reconcile_docs.py --archive-cites --slug {slug} --apply --json")
    by_hand = sorted({(p["file"], p["line"]) for p in pending
                      if p["form"] != "canonical" or p["owner"] != slug
                      or per_line[(p["file"], p["line"])] > 1
                      or (p["file"], p["line"]) in blocked_lines})
    return fix + [f"hand-edit {file}:{line}" for file, line in by_hand]


def _docs_at(root: Path, base: str) -> dict:
    """The fold's living docs (rel path -> text) as of git ref `base`; a path absent there is skipped."""
    rels = (*pending_changes._DOCS, *low_doc_parts.parts_on_disk(root))
    docs = {}
    for rel in rels:
        res = subprocess.run(["git", "-C", str(root), "show", f"{base}:{rel}"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if res.returncode == 0:
            docs[rel] = res.stdout
    return docs


def _apply_pending_conflicts(root: Path, out: dict, base: str | None) -> None:
    """Fold-check the pending fragments (task 1.11): with `base`, a fragment that folded on the base
    docs but not on these is drift (a `re-anchor` fix line); without, a non-blocking `pending_conflicts` note."""
    if not pending_changes.pending_slugs(root):
        return
    try:
        head = pending_changes.unappliable(root)
    except (OSError, UnicodeDecodeError):  # an unreadable living doc: the other checks own that
        return
    if not head:
        return
    if not base:
        out["pending_conflicts"] = head
        return
    on_base = pending_changes.unappliable(root, docs=_docs_at(root, base))
    for slug in (s for s in head if s not in on_base):
        out["fix"].append(f"re-anchor {pending_changes.CHANGES_DIR}/{slug}.md: {head[slug]}")
        out["verdict"] = "drift"


def check(repo_root, slug: str, *, base: str | None = None) -> dict:
    """Read-only: `{verdict, rows, pending, cites, fix}`, `verified` or `drift`.

    With a fragment for `slug` the verdict is `pending-compile` (the docs fold later), and a
    `base` ref also runs `living_doc_guard.check`, reported as `guard`.
    """
    root = Path(repo_root)
    if fragment_mode(root, slug):
        out = {"verdict": "pending-compile", "rows": [], "pending": [], "cites": [], "fix": []}
        if base:
            res = living_doc_guard.check(root, base_ref=base)
            out["guard"] = {"verdict": res.verdict, "paths": res.paths, "fix": res.fix}
        _apply_pending_conflicts(root, out, base)
        return out
    moved = inventory_archive.move_completed(root, slug, apply=False)
    rows = [r for r in (moved.rows or []) if r.lstrip().startswith("|")]  # drops RC bullets
    pending = pending_flip.scan(root, slug)
    cites = _cites(root, slug)
    fix = _fix_lines(root, slug, rows, pending, cites)
    verdict = "drift" if rows or pending or cites else "verified"
    out = {"verdict": verdict, "rows": rows, "pending": pending, "cites": cites, "fix": fix}
    _apply_pending_conflicts(root, out, base)
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Close a completed design's living-doc state, or check that it is closed.")
    parser.add_argument("command", choices=("close", "check"))
    parser.add_argument("--slug", required=True, metavar="S", help="the completed design's slug")
    parser.add_argument("--repo-root", default=".", metavar="R", help="repo root (default: .)")
    parser.add_argument("--base", metavar="REF", help="check: run the living-doc guard against REF")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser


def _print_close(slug: str, out: dict) -> None:
    if out["refused"]:
        print(f"final_doc_state: refused for '{slug}' — {out['refused']}")
        return
    print(f"final_doc_state: closed '{slug}': moved {out['moved']}, flipped {out['flipped']}")
    for path in out["paths"]:
        print(f"  wrote {path}")
    for s in out["skipped"]:
        print(f"  skipped {s['reason']}  {s['file']}:{s['line_no']}")


def _print_check(slug: str, out: dict) -> None:
    print(f"final_doc_state: {out['verdict']} for '{slug}'")
    if out.get("guard", {}).get("verdict") == "refused":
        print(f"  guard refused: {', '.join(out['guard']['paths'])}\n  fix: {out['guard']['fix']}")
    for row in out["rows"]:
        print(f"  live row: {row}")
    for p in out["pending"]:
        print(f"  pending ({p['form']}, owner {p['owner']}): {p['file']}:{p['line']}")
    for c in out["cites"]:
        print(f"  dead cite: {c['file']}:{c['line']}")
    for slug, reason in out.get("pending_conflicts", {}).items():
        print(f"  pending conflict (non-blocking): {slug}: {reason}")
    for line in out["fix"]:
        print(f"  fix: {line}")


def main(argv=None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse: 2 on usage error, 0 for --help
        return int(exc.code or 0)
    if args.command == "close":
        out = close(args.repo_root, args.slug)
    else:
        try:
            out = check(args.repo_root, args.slug, base=args.base)
        except living_doc_guard.GuardGitError as exc:
            print(f"final_doc_state: guard git error: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        (_print_close if args.command == "close" else _print_check)(args.slug, out)
    if args.command == "close":
        return 1 if out["refused"] else 0
    return 1 if out["verdict"] == "drift" or out.get("guard", {}).get("verdict") == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
