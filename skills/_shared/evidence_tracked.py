"""evidence_tracked.py — check that Demo Reference paths are git-tracked.

Given a spike design directory, parses spike-results.md's Demo Reference table
and reports any referenced path that is NOT git-tracked in the current tree.

Tracked-ness is current-tree tracked-ness: a path that was referenced and then
deleted from the repo (removed from git's index) is correctly flagged as untracked,
because durable-in-HEAD is the guarantee this check enforces.

Exit codes:
  0 — all referenced paths are git-tracked (or there is nothing to check)
  1 — one or more referenced paths are NOT git-tracked (prints repair lines)
  2 — unexpected crash (fail-closed; exception message printed)

Usage: python3 skills/_shared/evidence_tracked.py <design-dir>
"""

from __future__ import annotations

import itertools
import re
import subprocess
import sys
from pathlib import Path


# ── Path-fragment classifier helpers ─────────────────────────────────────────

_BARE_EXT_RE = re.compile(r"^\.[a-zA-Z0-9]+$")  # bare suffix like .txt, .md
_URL_RE = re.compile(r"^https?://")
_NA_VALUES = {"n/a", "none", "—", "-", ""}
_BRACE_RE = re.compile(r"\{[^}]+\}")
_GLOB_RE = re.compile(r"[*?]")


_PATH_EXTS = frozenset(
    ".md .py .sh .json .yml .yaml .txt .toml .tf .js .ts .png .mp4 .csv "
    ".log .html .xml .env .lock .cfg .ini .rb .go .rs .java .c .cpp .h "
    ".sql .gz .zip .tar .pdf .ipynb".split()
)


def _is_non_path(fragment: str) -> bool:
    """Return True if fragment should be dropped (not a repo path).

    A fragment is kept as a candidate path iff it looks like a repo path —
    it contains '/' OR ends in a recognisable file extension — AND is not a
    URL, not an n/a placeholder, and not a bare-suffix token like '.txt'.

    This replaces the old 'must start with demos/' gate, which silently passed
    any non-demos path (artifacts/, top-level scripts, etc.) as non-path.
    """
    f = fragment.strip()
    if not f:
        return True
    if _URL_RE.match(f):
        return True
    if f.lower() in _NA_VALUES:
        return True
    if _BARE_EXT_RE.match(f):
        return True
    # Keep if it contains a slash (directory-relative path) or has a known ext
    if "/" in f:
        return False
    suffix = Path(f).suffix.lower()
    if suffix and suffix in _PATH_EXTS:
        return False
    # Pure prose word with no slash and no recognised extension — drop it
    return True


def _split_fragments(cell: str) -> list[str]:
    """Split a File cell on '+' and whitespace; strip backticks and pipes."""
    # Remove backticks and leading/trailing pipe characters
    cell = cell.strip().strip("|").strip()
    cell = cell.replace("`", "")
    # Split on '+' or whitespace runs
    raw = re.split(r"\+|\s+", cell)
    return [f.strip() for f in raw if f.strip()]


def _expand_braces(pattern: str) -> list[str]:
    """Expand a single brace-expression like run-{1,2,3}/x.json into literal paths.

    Only handles a single {a,b,c} group. For more complex patterns falls back
    to returning the original pattern (the caller handles as DIR/PREFIX).
    """
    m = _BRACE_RE.search(pattern)
    if not m:
        return [pattern]
    pre = pattern[: m.start()]
    post = pattern[m.end() :]
    options = m.group(0)[1:-1].split(",")
    expanded = []
    for opt in options:
        suffix = f"{pre}{opt.strip()}{post}"
        # Recurse in case of nested braces (rare, but safe)
        expanded.extend(_expand_braces(suffix))
    return expanded


def _is_dir_or_prefix(fragment: str) -> bool:
    """Return True if fragment is a trailing-slash, glob, or brace expression."""
    return fragment.endswith("/") or bool(_GLOB_RE.search(fragment)) or bool(_BRACE_RE.search(fragment))


# ── Git tracking checks ───────────────────────────────────────────────────────

def _git_ls_files_nonempty(repo_root: Path, path_arg: str) -> bool:
    """Return True if `git ls-files -- <path_arg>` returns at least one line.

    path_arg must be relative to repo_root.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--", path_arg],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _exact_tracked(repo_root: Path, repo_rel_path: str) -> bool:
    """Return True iff the exact path is tracked.

    repo_rel_path must be relative to repo_root (NOT --error-unmatch on brace/globs).
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "--error-unmatch", repo_rel_path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _dir_or_prefix_tracked(
    repo_root: Path, repo_rel_fragment: str, original_fragment: str = ""
) -> bool:
    """Return True iff the dir/prefix/glob/brace fragment has tracked content.

    repo_rel_fragment must be relative to repo_root.
    original_fragment (the design-dir-relative form) is used for classification
    when needed (e.g. trailing-slash detection after path resolution stripped it).

    Strategy:
    - Brace fragment: expand to literals; require ALL individual expansions tracked
      (exact check per expansion). If any expansion contains a further glob/brace,
      fall back to parent-dir non-empty check.
    - Trailing-slash (in original or resolved form): check dir for any tracked content.
    - Glob: use git ls-files -- <fragment> (git expands simple globs in pathspecs).
    """
    frag = repo_rel_fragment
    orig = original_fragment or frag

    if _BRACE_RE.search(frag) and not _GLOB_RE.search(frag):
        # Pure brace fragment — expand to concrete literals first, then route
        # each expansion through the normal classifier. ALL must be tracked.
        expansions = _expand_braces(frag)
        for exp in expansions:
            if _is_dir_or_prefix(exp):
                # Expanded to a dir/glob — recurse with the concrete literal
                if not _dir_or_prefix_tracked(repo_root, exp, original_fragment=exp):
                    return False
            else:
                if not _exact_tracked(repo_root, exp):
                    return False
        return True

    # Trailing-slash: use original fragment to detect (resolution may strip it)
    if frag.endswith("/") or orig.endswith("/"):
        return _git_ls_files_nonempty(repo_root, frag.rstrip("/"))

    # Glob or mixed: pass directly to git ls-files (it handles simple globs)
    return _git_ls_files_nonempty(repo_root, frag)


def _resolve_to_repo_rel(repo_root: Path, design_dir: Path, fragment: str) -> str:
    """Resolve a design-dir-relative fragment to a repo-root-relative path string.

    If the fragment contains brace/glob characters, resolve the static directory
    prefix only (everything up to and including the last '/' before the first
    brace/glob), then re-attach the dynamic tail.
    """
    # Find the static prefix (up to first brace or glob char)
    static_end = len(fragment)
    for i, ch in enumerate(fragment):
        if ch in "{*?":
            static_end = i
            break

    static_part = fragment[:static_end]
    dynamic_part = fragment[static_end:]

    # For the static part: resolve the parent directory so we preserve any
    # trailing separator needed to re-attach the dynamic tail correctly.
    if dynamic_part:
        # static_part ends at a directory boundary (e.g. "demos/resolver/")
        # Use the parent directory to avoid resolve() stripping trailing slashes.
        dir_part = static_part  # may end with '/'
        dir_abs = (design_dir / dir_part).resolve() if dir_part.strip("/") else design_dir
        # If static_part had a trailing '/' we want to keep it in the output
        sep = "/" if static_part.endswith("/") and not str(dir_abs).endswith("/") else ""
        try:
            repo_rel_dir = dir_abs.relative_to(repo_root)
        except ValueError:
            return fragment
        return str(repo_rel_dir) + sep + dynamic_part

    # No dynamic part — resolve the full path normally
    full_abs = (design_dir / static_part).resolve()
    try:
        return str(full_abs.relative_to(repo_root))
    except ValueError:
        return fragment


def _is_tracked_via(repo_root: Path, repo_rel: str, original_fragment: str) -> bool:
    """Return True if repo_rel is tracked (dir/prefix or exact as appropriate)."""
    if _is_dir_or_prefix(original_fragment):
        return _dir_or_prefix_tracked(repo_root, repo_rel, original_fragment=original_fragment)
    return _exact_tracked(repo_root, repo_rel)


def _is_untracked(repo_root: Path, design_dir: Path, fragment: str) -> bool:
    """Return True if fragment is NOT git-tracked (should be reported as offender).

    Resolution strategy (first match wins — tracked):
    1. Resolve relative to design_dir and check via git.
    2. Resolve as repo-root-relative literal (fragment treated as path from root).
    3. Use the fragment AS a git pathspec against the repo root — git's own
       glob/brace expansion resolves relative patterns like run-{1,2,3}/artifacts/*
       anywhere in the tree (continuation-fragment fallback).

    The dir/prefix classification uses the ORIGINAL fragment so trailing slashes
    and glob chars are not lost by path resolution.
    """
    repo_rel_from_design = _resolve_to_repo_rel(repo_root, design_dir, fragment)
    if _is_tracked_via(repo_root, repo_rel_from_design, fragment):
        return False

    # Try the fragment as a repo-root-relative literal path
    static_end = len(fragment)
    for i, ch in enumerate(fragment):
        if ch in "{*?":
            static_end = i
            break
    static_part = fragment[:static_end]
    repo_root_abs = (repo_root / static_part).resolve()
    try:
        repo_rel_from_root = str(repo_root_abs.relative_to(repo_root)) + fragment[static_end:]
    except ValueError:
        repo_rel_from_root = None
    if repo_rel_from_root and repo_rel_from_root != repo_rel_from_design:
        if _is_tracked_via(repo_root, repo_rel_from_root, fragment):
            return False

    # Last resort: tier-3 continuation-fragment fallback.
    #
    # Handles fragments from line-wrapped markdown cells that lost their
    # directory prefix (e.g. "extract_fixtures.py" or "run-{1,2}/artifacts/*"
    # whose leading "demos/<exp>/" was split across a cell boundary).
    #
    # Anchoring rules (fail-safe toward MORE checking):
    #
    # • Multi-segment fragments (contain '/'):
    #   Search repo-wide. A fragment resolves iff every brace-expansion has at
    #   least one tracked path P where P == frag or P.endswith("/" + frag)
    #   (path-segment-boundary suffix match, not substring).
    #   For glob-last-segment expansions (e.g. run-1/artifacts/*), check that
    #   the parent dir appears as a segment-boundary sub-path in any tracked file.
    #
    # • Bare-leaf fragments (no '/'):
    #   Search ONLY within the design-dir subtree. A bare leaf like
    #   "extract_fixtures.py" must be tracked somewhere under the design directory
    #   (e.g. demos/extract_fixtures.py). This prevents a collision where an
    #   unrelated tracked file outside the design dir (e.g. ci/build.sh) would
    #   masquerade as the referenced build.sh.

    # Compute the design-dir path relative to repo_root (for bare-leaf scoping).
    try:
        design_dir_rel = str(design_dir.relative_to(repo_root))
    except ValueError:
        design_dir_rel = None  # design_dir is outside repo; no tier-3 for bare leaves

    # Enumerate all tracked paths once for efficiency across all expansion checks.
    _all_tracked_cache: list[str] | None = None

    def _all_tracked() -> list[str]:
        nonlocal _all_tracked_cache
        if _all_tracked_cache is None:
            r = subprocess.run(
                ["git", "-C", str(repo_root), "ls-files"],
                capture_output=True, text=True,
            )
            _all_tracked_cache = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
        return _all_tracked_cache

    def _anchored_suffix_tracked(frag: str) -> bool:
        """True iff the fragment resolves to at least one tracked path.

        For multi-segment fragments: repo-wide segment-boundary suffix check.
        For bare-leaf fragments: design-dir-scoped segment-boundary suffix check.
        """
        has_slash = "/" in frag
        last_seg = frag.rsplit("/", 1)[-1] if has_slash else frag

        if has_slash and (_GLOB_RE.search(last_seg) or _BRACE_RE.search(last_seg)):
            # Glob/brace last segment: check parent dir as a segment-anchored sub-path.
            parent = frag.rsplit("/", 1)[0]
            needle = "/" + parent + "/"
            return any(needle in ("/" + p) for p in _all_tracked())

        if has_slash:
            # Multi-segment exact suffix: P == frag or P ends with '/frag'.
            return any(p == frag or p.endswith("/" + frag) for p in _all_tracked())

        # Bare leaf (no '/'): restrict to design-dir subtree to prevent cross-design
        # collisions (e.g. ci/build.sh matching a referenced bare leaf build.sh).
        if design_dir_rel is None:
            return False
        design_prefix = design_dir_rel + "/"
        return any(
            p.startswith(design_prefix) and (p == frag or p.endswith("/" + frag))
            for p in _all_tracked()
        )

    leaf_fragments = _expand_braces(fragment)
    if all(_anchored_suffix_tracked(lf) for lf in leaf_fragments):
        return False

    return True


# ── Demo Reference table parser ───────────────────────────────────────────────

_DEMO_REF_SECTION_RE = re.compile(r"^##\s+Demo Reference", re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r"^##\s+", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_SEPARATOR_RE = re.compile(r"^\|[-|\s]+\|$")


def _extract_demo_ref_section(text: str) -> str | None:
    """Extract the text from '## Demo Reference' to the next ## section."""
    m = _DEMO_REF_SECTION_RE.search(text)
    if not m:
        return None
    start = m.end()
    rest = text[start:]
    next_m = _NEXT_SECTION_RE.search(rest)
    return rest[: next_m.start()] if next_m else rest


def find_referenced_paths(results_md_text: str) -> list[str]:
    """Return a list of path fragments referenced in the Demo Reference table.

    Parses the '## Demo Reference' section, skips the header row and |---| separator,
    and extracts the File column from each data row. Each cell is split into fragments
    on '+' and whitespace; non-path fragments (URLs, n/a, bare suffixes) are dropped.
    """
    section = _extract_demo_ref_section(results_md_text)
    if section is None:
        return []

    paths: list[str] = []
    rows = section.splitlines()
    header_seen = False
    separator_seen = False

    for row in rows:
        row = row.strip()
        if not _TABLE_ROW_RE.match(row):
            continue
        if _SEPARATOR_RE.match(row):
            separator_seen = True
            continue

        # Parse columns
        cols = [c.strip() for c in row.split("|")]
        # cols[0] is empty (before first |), cols[-1] is empty (after last |)
        cols = [c for c in cols if c != ""]
        if not cols:
            continue

        file_col = cols[0]

        # First non-separator row after the opening is the header row
        if not header_seen:
            header_seen = True
            # Skip header row (contains "File" or similar column names)
            continue

        # Data row — split the File cell into path fragments
        fragments = _split_fragments(file_col)
        for frag in fragments:
            if not _is_non_path(frag):
                paths.append(frag)

    return paths


# ── Main ──────────────────────────────────────────────────────────────────────

def _find_repo_root(start: Path) -> Path:
    """Walk up from start to find the git repo root."""
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Not inside a git repository: {start}")
    return Path(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 (clean), 1 (offenders), 2 (crash)."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: evidence_tracked.py <design-dir>", file=sys.stderr)
        return 2

    design_dir = Path(args[0]).resolve()
    results_path = design_dir / "spike-results.md"

    if not results_path.exists():
        return 0  # Nothing to check

    try:
        repo_root = _find_repo_root(design_dir)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        text = results_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read spike-results.md: {exc}", file=sys.stderr)
        return 2

    try:
        fragments = find_referenced_paths(text)
    except Exception as exc:  # noqa: BLE001
        print(f"error: failed to parse Demo Reference table: {exc}", file=sys.stderr)
        return 2

    if not fragments:
        return 0

    offenders: list[str] = []
    try:
        for frag in fragments:
            if _is_untracked(repo_root, design_dir, frag):
                offenders.append(frag)
    except Exception as exc:  # noqa: BLE001
        print(f"error: git check failed: {exc}", file=sys.stderr)
        return 2

    for path in offenders:
        print(
            f"repair: {path} referenced by spike-results.md is not git-tracked"
        )

    return 1 if offenders else 0


if __name__ == "__main__":
    sys.exit(main())
