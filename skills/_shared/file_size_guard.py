#!/usr/bin/env python3
"""file_size_guard.py — enforced file-size cap predicate (single source of truth).

Design: file-size-limits (light class). One shared implementation consumed by
BOTH the pre-commit hook (explicit staged paths) and framework-check.sh
invariant #34 (``--all-tracked``, dev-repo only) so local and CI verdicts never disagree.

Decision table (a file violates if it exceeds EITHER axis):

  class      lines soft/hard    chars soft/hard
  code       350 / 500          35,000 / 50,000   (.py .sh .js .ts)
  markdown   300 / 500          35,000 / 50,000   (.md incl. SKILL.md)
  tests      300 / 500          35,000 / 50,000   (test_*.py)
  (other extensions are uncapped; suffix-based — extensionless scripts
  are out of scope by design)

Per-path char caps (skill-context-diet D5) replace the 35k/50k char pair for
these paths; the lines axis is unchanged. ``char_caps(rel, framework_tree)``:

  path                                chars soft/hard   applies in
  three-pillars-docs/vision.md         8,000 / 12,000   any repo
  three-pillars-docs/architecture.md  15,000 / 25,000   any repo
  three-pillars-docs/product_roadmap.md 10,000 / 15,000 any repo
  three-pillars-docs/known_issues.md  12,000 / 20,000   any repo
  skills/*/SKILL.md                   20,000 / 35,000   framework tree only
  skills/_shared/*.md                 15,000 / 25,000   framework tree only
  anything else                       35,000 / 50,000

``is_framework_tree(root)`` is true iff the repo carries the plugin
release-tiers manifest (``.claude-plugin/release-tiers.json``).

Postures:
  - over hard, NOT on grandfather list  → BLOCK (exit 1)
  - over hard, on grandfather list      → WARN  (warn even when touched)
  - over hard, a LIVING DOC on a staged
    surface (hook paths, ``commit_guard.file_size``)
                                    → WARN … ``rollover-due`` (exit 0) — never
      a block, in any repo: the next framework writer rolls the doc over, so
      an existing repo is not hard-blocked on day one (skill-context-diet D8)
  - over soft only                      → WARN
  - exempt paths                        → silent: completed-tp-designs/**,
    known_issues_resolved.md + product_roadmap_archive.md +
    architecture_archive.md (append-only archives), and in-flight
    three-pillars-docs/tp-designs/** (design artifacts — append-only
    decisions.md logs can never split; mirrors inv #30's exemption)

Grandfather lifecycle (the list serves TWO consumers — this size guard and
framework-check inv #30's long-line guard, dev-repo only — so both criteria govern it):
  - a file QUALIFIES for the list iff it hard-violates the size caps OR it is
    a top-level three-pillars-docs/*.md carrying a >800 non-ws-char line
    outside code fences (the inv #30 predicate);
  - ``--emit-grandfather`` prints current qualifiers (allowlist ignored);
  - ``--all-tracked`` additionally prints ``STALE <entry> …`` and exits 1 for
    any listed entry that no longer qualifies — the list only shrinks, and
    that is enforced mechanically, not by convention.

Output: one machine-greppable line per finding:
  ``BLOCK <relpath> lines=N chars=M cap=<class>:<hard_lines>l/<hard_chars>c``
  ``STALE <relpath> — no longer violates any grandfathered cap; remove it``

Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

LINE_CAPS: dict[str, tuple[int, int]] = {
    # class -> (soft, hard)
    "code": (350, 500),
    "markdown": (300, 500),
    "tests": (300, 500),
}
CHARS_SOFT = 35_000  # default row; per-path rows below override it
CHARS_HARD = 50_000
DOC_CHAR_CAPS: dict[str, tuple[int, int]] = {
    # living docs (apply in any repo) -> (soft, hard) chars
    "three-pillars-docs/vision.md": (8_000, 12_000),
    "three-pillars-docs/architecture.md": (15_000, 25_000),
    "three-pillars-docs/product_roadmap.md": (10_000, 15_000),
    "three-pillars-docs/known_issues.md": (12_000, 20_000),
}
SKILL_MD_CHAR_CAPS = (20_000, 35_000)   # skills/*/SKILL.md, framework tree only
SHARED_MD_CHAR_CAPS = (15_000, 25_000)  # skills/_shared/*.md, framework tree only
FRAMEWORK_MANIFEST_REL = ".claude-plugin/release-tiers.json"
LONG_LINE_THRESHOLD = 800  # non-ws chars/line; mirrors framework-check inv #30

CODE_SUFFIXES = {".py", ".sh", ".js", ".ts"}
GRANDFATHER_REL = ".three-pillars/file-size-grandfather.txt"
EXEMPT_PREFIXES = (
    "three-pillars-docs/completed-tp-designs/",
    "three-pillars-docs/tp-designs/",
)
EXEMPT_FILES = frozenset({
    "three-pillars-docs/known_issues_resolved.md",
    "three-pillars-docs/product_roadmap_archive.md",
    "three-pillars-docs/architecture_archive.md",
    "three-pillars-docs/known_issues_low.md",
    "three-pillars-docs/vision_archive.md",
})
ARCHIVE_GLOB = "three-pillars-docs/*_archive.md"


def classify(relpath: str) -> str | None:
    """Map a path to its cap class, or None when uncapped."""
    name = Path(relpath).name
    suffix = Path(relpath).suffix
    if name.startswith("test_") and suffix == ".py":
        return "tests"
    if suffix in CODE_SUFFIXES:
        return "code"
    if suffix == ".md":
        return "markdown"
    return None


def is_framework_tree(root: Path) -> bool:
    """True iff the repo carries the plugin release-tiers manifest."""
    return (Path(root) / FRAMEWORK_MANIFEST_REL).is_file()


def char_caps(relpath: str, framework_tree: bool) -> tuple[int, int]:
    """(soft, hard) char caps for a path; 35k/50k when it has no per-doc row."""
    norm = relpath.replace("\\", "/")
    if norm in DOC_CHAR_CAPS:
        return DOC_CHAR_CAPS[norm]
    if framework_tree:
        parts = norm.split("/")
        if len(parts) == 3 and parts[0] == "skills" and parts[2] == "SKILL.md":
            return SKILL_MD_CHAR_CAPS
        if len(parts) == 3 and parts[:2] == ["skills", "_shared"] and parts[2].endswith(".md"):
            return SHARED_MD_CHAR_CAPS
    return CHARS_SOFT, CHARS_HARD


def is_living_doc(relpath: str) -> bool:
    """The four living docs — the paths carrying a ``DOC_CHAR_CAPS`` row. They
    alone get the staged posture below; cold files and archives never do."""
    return relpath.replace("\\", "/") in DOC_CHAR_CAPS


def is_exempt(relpath: str) -> bool:
    """Frozen path classes: archives + in-flight design artifacts."""
    norm = relpath.replace("\\", "/")
    if norm in EXEMPT_FILES or any(norm.startswith(p) for p in EXEMPT_PREFIXES):
        return True
    # Top-level *_archive.md only: fnmatch's `*` crosses `/`, so check depth.
    return fnmatch.fnmatchcase(norm, ARCHIVE_GLOB) and norm.count("/") == 1


def measure(path: Path) -> tuple[int, int, str]:
    """Return (lines, chars, text) for a file; decoded utf-8 with replacement."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    return len(text.splitlines()), len(text), text


def in_inv30_scope(relpath: str) -> bool:
    """Top-level three-pillars-docs/*.md — the files inv #30 walks."""
    norm = relpath.replace("\\", "/")
    prefix = "three-pillars-docs/"
    return (
        norm.startswith(prefix)
        and "/" not in norm[len(prefix):]
        and norm.endswith(".md")
    )


def has_long_lines(text: str) -> bool:
    """inv #30's predicate: any line > LONG_LINE_THRESHOLD non-ws chars
    outside ``` fences (same simple fence toggle as the awk)."""
    fence = False
    for line in text.splitlines():
        if re.match(r"^\s*```", line):
            fence = not fence
            continue
        if not fence and len(re.sub(r"\s", "", line)) > LONG_LINE_THRESHOLD:
            return True
    return False


def load_grandfather(repo_root: Path) -> frozenset[str]:
    """Read the committed allowlist; missing file = empty. '#' lines are comments."""
    gf = repo_root / GRANDFATHER_REL
    if not gf.is_file():
        return frozenset()
    entries = set()
    for raw in gf.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            entries.add(line)
    return frozenset(entries)


def evaluate(
    relpath: str, lines: int, chars: int, *, grandfathered: bool,
    framework_tree: bool = False, staged: bool = False,
) -> tuple[str, str] | None:
    """Apply the size decision table. Returns (severity, finding-line) or None.

    ``staged`` is the surface, not the repo: True for the explicit-path
    (pre-commit / ``commit_guard.file_size``) run, False for ``--all-tracked``
    and ``--emit-grandfather``, where an unlisted over-cap living doc still
    BLOCKs. Only a staged living doc over its hard cap softens, to
    ``WARN … rollover-due``."""
    cls = classify(relpath)
    if cls is None or is_exempt(relpath):
        return None
    soft, hard = LINE_CAPS[cls]
    chars_soft, chars_hard = char_caps(relpath, framework_tree)
    over_hard = lines > hard or chars > chars_hard
    over_soft = lines > soft or chars > chars_soft
    if not over_soft and not over_hard:
        return None
    rollover = staged and is_living_doc(relpath) and over_hard and not grandfathered
    severity = "WARN" if (rollover or not over_hard or grandfathered) else "BLOCK"
    detail = f"{severity} {relpath} lines={lines} chars={chars} cap={cls}:{hard}l/{chars_hard}c"
    if rollover:
        detail += " rollover-due"
    return severity, detail


def qualifies_for_grandfather(
    relpath: str, lines: int, chars: int, text: str, *, framework_tree: bool = False
) -> bool:
    """True iff the file may legitimately sit on the grandfather list:
    hard size violation OR an inv-#30-scope doc with long lines. Exempt
    paths never qualify (they need no grandfathering)."""
    if is_exempt(relpath):
        return False
    unlisted = evaluate(relpath, lines, chars, grandfathered=False,
                        framework_tree=framework_tree)
    if unlisted is not None and unlisted[0] == "BLOCK":
        return True
    return in_inv30_scope(relpath) and has_long_lines(text)


def iter_tracked(repo_root: Path) -> list[str]:
    """All git-tracked paths, repo-root-relative. NUL-delimited (-z) so
    non-ASCII / quoted paths come back verbatim, never C-escaped."""
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    )
    return [p for p in out.stdout.split("\0") if p]


def _relpath_for(path: Path, repo_root: Path) -> str:
    """Repo-relative path when inside the root; otherwise the path as given
    (with a loud NOTE — exempt/grandfather matching cannot apply to it)."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        print(
            f"NOTE {path} is outside --repo-root {repo_root} — "
            "exempt/grandfather matching disabled for it",
            file=sys.stderr,
        )
        return path.as_posix()


def _default_repo_root() -> Path:
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return Path(probe.stdout.strip())
    return Path.cwd()


def _measurable(path: Path) -> bool:
    """Regular files only — symlinks are skipped (git's blob is the link
    text, not the target; a loop/EPERM target must not crash the guard)."""
    return path.is_file() and not path.is_symlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="explicit files to check (hook mode)")
    parser.add_argument("--all-tracked", action="store_true",
                        help="check every git-tracked file + grandfather staleness")
    parser.add_argument("--emit-grandfather", action="store_true",
                        help="print current qualifiers (allowlist ignored), sorted")
    parser.add_argument("--repo-root", type=Path, default=None,
                        help="repo root for allowlist/exempt resolution (default: git toplevel)")
    args = parser.parse_args(argv)

    repo_root = args.repo_root if args.repo_root is not None else _default_repo_root()
    fw = is_framework_tree(repo_root)

    if args.all_tracked or args.emit_grandfather:
        rels = iter_tracked(repo_root)
        targets = [(repo_root / r, r) for r in rels]
    else:
        targets = [(Path(p), _relpath_for(Path(p), repo_root)) for p in args.paths]

    if args.emit_grandfather:
        existing = load_grandfather(repo_root)
        violators = []
        skipped: set[str] = set()
        for path, rel in targets:
            if not _measurable(path):
                skipped.add(rel)
                continue
            try:
                lines, chars, text = measure(path)
            except OSError:
                skipped.add(rel)
                continue
            if qualifies_for_grandfather(rel, lines, chars, text, framework_tree=fw):
                violators.append(rel)
        # Unmeasurable ≠ compliant: a previously-listed entry we could not read
        # (perms, symlink swap) is preserved, never silently dropped.
        for rel in sorted(existing & skipped):
            print(f"NOTE {rel} unmeasurable — preserved on the list, verify by hand",
                  file=sys.stderr)
            violators.append(rel)
        print("# generated by file_size_guard.py --emit-grandfather; shrink as files split")
        print("# entries qualify by hard size caps OR (top-level docs) inv-#30 long lines")
        for rel in sorted(violators):
            print(rel)
        return 0

    grandfather = load_grandfather(repo_root)
    # The sweep modes (inv #34, grandfather emission) keep the hard posture;
    # only the explicit-path hook run softens a living doc.
    staged = not (args.all_tracked or args.emit_grandfather)
    blocked = False
    qualifying: set[str] = set()
    unmeasured: set[str] = set()
    for path, rel in targets:
        if not _measurable(path):
            unmeasured.add(rel)
            continue
        try:
            lines, chars, text = measure(path)
        except OSError:
            unmeasured.add(rel)
            continue
        if qualifies_for_grandfather(rel, lines, chars, text, framework_tree=fw):
            qualifying.add(rel)
        verdict = evaluate(rel, lines, chars, grandfathered=rel in grandfather,
                           framework_tree=fw, staged=staged)
        if verdict is None:
            continue
        severity, detail = verdict
        print(detail)
        blocked = blocked or severity == "BLOCK"

    if args.all_tracked:
        # Mechanical monotonic shrink: a listed entry that no longer qualifies
        # (or is untracked) is STALE and fails the run until removed.
        # Unmeasurable ≠ compliant: an entry we could not read (perms hiccup,
        # symlink swap) is NOTEd and kept — never declared STALE, never blocks.
        for entry in sorted(grandfather):
            if entry in unmeasured:
                print(f"NOTE {entry} unmeasurable — kept on the list, verify by hand",
                      file=sys.stderr)
                continue
            if entry not in qualifying:
                print(
                    f"STALE {entry} — no longer violates any grandfathered cap "
                    f"(size or doc long-line); remove it from {GRANDFATHER_REL}"
                )
                blocked = True
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
