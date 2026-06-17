"""citation_liveness — dead-cite detector and stale-row scanner.

Reporter only: always exits 0, never a gate.
Two public pure functions (W6 / invariant-citation-coherence surface):
  dead_design_cites(repo_root) -> list[DeadCite]
  stale_status_rows(repo_root, live_branches) -> list[StaleRow]

Plus the live-branch query helper and a CLI.

stdlib-only: re, pathlib, subprocess, json, argparse, dataclasses.

design: post-merge-doc-reconcile
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure _shared/ is on path for sibling imports
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from citation_rows import (  # noqa: E402
    _quoted_spans,
    _is_in_quoted_span,
    _strip_markup,
    _SLUG_RE,
    _BULLET_LEAD_RE,
    _split_table_cells,
    owner_slug_of_row,
)

# ------------------------------------------------------------------ #
# Regex constants
# ------------------------------------------------------------------ #

# Matches tp-designs/{slug} but NOT completed-tp-designs/{slug} or superseded-tp-designs/{slug}
DESIGN_CITE_RE = re.compile(r"(?<!completed-)(?<!superseded-)tp-designs/([a-z0-9][a-z0-9-]*)")

# Matches "Completion PR pending" or "completion PR pending" variants
STALE_STATUS_RE = re.compile(r"[Cc]ompletion PR pending(?:\s*\(Tier 6\))?")

# Excluded path segments for code-scan scope
_CODE_EXCLUDED_SEGMENTS = frozenset({"fixtures", "eval", "__pycache__"})


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #


@dataclass
class DeadCite:
    path: str    # repo-relative
    line: int    # 1-based
    slug: str
    kind: str    # "code" | "living-doc"


@dataclass
class StaleRow:
    path: str
    line: int
    slug: str    # owning design inferred from nearest slug mention on the line


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #


def _is_excluded_code_path(path: Path) -> bool:
    """True if any path segment is in the excluded set."""
    return any(part in _CODE_EXCLUDED_SEGMENTS for part in path.parts)


def _iter_scan_lines(path: Path):
    """Yield (line_number, line_text) for a file; skip on error."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for i, line in enumerate(text.splitlines(), start=1):
        yield i, line


def _in_history(heading_text: str) -> bool:
    """True if this ## heading title contains 'History'."""
    return "History" in heading_text


# ------------------------------------------------------------------ #
# Public API — pure functions (W6 surface)
# ------------------------------------------------------------------ #


def dead_design_cites(repo_root) -> list[DeadCite]:
    """Scan two scopes for dead tp-designs/* citations.

    A cite is dead iff:
      - tp-designs/{slug}/ does NOT exist, AND
      - completed-tp-designs/{slug}/ DOES exist.

    Code scope: *.py, *.sh, *.md under skills/ (rglob), excluding
                __pycache__/, fixtures/, eval/ segments.
    Living-doc scope: three-pillars-docs/*.md (non-recursive).

    History sections in living docs are excluded (append-only truth).
    Fenced code blocks are excluded (example content, never live).
    completed-tp-designs/** and tp-designs/** are never scanned.
    """
    root = Path(repo_root)
    tp_designs = root / "three-pillars-docs" / "tp-designs"
    completed = root / "three-pillars-docs" / "completed-tp-designs"
    results: list[DeadCite] = []

    def _is_dead(slug: str) -> bool:
        return (
            not (tp_designs / slug).is_dir()
            and (completed / slug).is_dir()
        )

    # --- Code scope ---
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for ext in ("*.py", "*.sh", "*.md"):
            for fpath in skills_dir.rglob(ext):
                # Only check relative path segments under skills/
                try:
                    rel_parts = fpath.relative_to(root).parts
                except ValueError:
                    continue
                if any(seg in _CODE_EXCLUDED_SEGMENTS for seg in rel_parts):
                    continue
                try:
                    rel_str = str(fpath.relative_to(root))
                except ValueError:
                    rel_str = str(fpath)
                in_fence = False
                for lineno, line in _iter_scan_lines(fpath):
                    if line.startswith("```"):
                        in_fence = not in_fence
                        continue
                    if in_fence:
                        continue
                    for m in DESIGN_CITE_RE.finditer(line):
                        slug = m.group(1)
                        if _is_dead(slug):
                            results.append(
                                DeadCite(
                                    path=rel_str,
                                    line=lineno,
                                    slug=slug,
                                    kind="code",
                                )
                            )

    # --- Living-doc scope ---
    living_docs_dir = root / "three-pillars-docs"
    if living_docs_dir.is_dir():
        for fpath in living_docs_dir.glob("*.md"):
            try:
                rel_str = str(fpath.relative_to(root))
            except ValueError:
                rel_str = str(fpath)
            in_history = False
            in_fence = False
            for lineno, line in _iter_scan_lines(fpath):
                # Track fenced code block state
                if line.startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                # Track History section state.
                # H1 (# ) that is NOT H2 (## ) exits history scope.
                if line.startswith("# ") and not line.startswith("## "):
                    in_history = False
                    # Fall through: still scan H1 heading for dead cites
                if line.startswith("## "):
                    heading_title = line[3:].strip()
                    in_history = _in_history(heading_title)
                    # Fall through: still scan H2 heading lines for dead cites
                if in_history:
                    continue
                for m in DESIGN_CITE_RE.finditer(line):
                    slug = m.group(1)
                    if _is_dead(slug):
                        results.append(
                            DeadCite(
                                path=rel_str,
                                line=lineno,
                                slug=slug,
                                kind="living-doc",
                            )
                        )

    return results


def live_remote_branches(repo_root, ls_remote_fn=None) -> set[str] | None:
    """Query origin for live tp/* branches via a single batched ls-remote.

    Returns:
      set[str]  — the set of branch names (e.g. {"tp/foo", "tp/bar"})
                  when the query succeeds (including empty set for zero branches).
      None      — when the query fails (non-zero exit, offline, etc.).
                  None means "can't know" — distinct from empty set.
    """
    if ls_remote_fn is None:
        def ls_remote_fn(*args, **kwargs):
            return subprocess.run(*args, **kwargs)

    try:
        result = ls_remote_fn(
            ["git", "-C", str(repo_root), "ls-remote", "--heads", "origin",
             "refs/heads/tp/*"],
            capture_output=True,
            text=True,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    branches: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: "<sha>\trefs/heads/<branch>"
        parts = line.split("\t", 1)
        if len(parts) == 2:
            ref = parts[1].strip()
            if ref.startswith("refs/heads/"):
                branch = ref[len("refs/heads/"):]
                branches.add(branch)
    return branches


def stale_status_rows(repo_root, live_branches: set | None) -> list[StaleRow]:
    """Scan product_roadmap.md for merge-confirmed stale status rows.

    A row is stale iff:
      - It matches STALE_STATUS_RE, AND
      - It is outside ## History / ## Roadmap History, AND
      - It is outside fenced code blocks, AND
      - The slug resolves to an archived design, AND
      - tp/{slug} is NOT in live_branches.

    When live_branches is None (offline / ls-remote failed), returns []
    (fail-open — can't confirm merge).
    """
    if live_branches is None:
        return []

    root = Path(repo_root)
    roadmap = root / "three-pillars-docs" / "product_roadmap.md"
    if not roadmap.is_file():
        return []

    completed = root / "three-pillars-docs" / "completed-tp-designs"
    results: list[StaleRow] = []

    try:
        rel_str = str(roadmap.relative_to(root))
    except ValueError:
        rel_str = str(roadmap)

    in_history = False
    in_fence = False
    for lineno, line in _iter_scan_lines(roadmap):
        # Track fenced code block state (skip content inside fences)
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # H1 (# ) that is NOT H2 (## ) exits history scope.
        if line.startswith("# ") and not line.startswith("## "):
            in_history = False
        if line.startswith("## "):
            heading_title = line[3:].strip()
            in_history = _in_history(heading_title)
            continue
        if in_history:
            continue
        if not STALE_STATUS_RE.search(line):
            continue
        # Quote-aware suppression: skip rows whose ONLY stale-status mention is
        # inside double-quote or backtick pairs (those are prose, never edited by
        # the writer — reporting them creates a permanent detector/writer divergence).
        # Bullet rows treat '|' as prose; table rows reset pairing at cell boundaries.
        _is_table_row = not bool(re.match(r"^\s*[-*]\s", line))
        quoted_spans = _quoted_spans(line, is_table_row=_is_table_row)
        all_matches = list(STALE_STATUS_RE.finditer(line))
        unquoted = [
            m for m in all_matches
            if not _is_in_quoted_span(m.start(), m.end(), quoted_spans)
        ]
        if len(unquoted) == 0:
            # All status mentions are prose/quoted — no stale row to report
            continue
        # Attribute by the row's OWN slug using directory-resolving cell scan.
        # owner_slug_of_row handles both table rows (cell-order precedence) and
        # bullet rows (leading-marker only). Returns None if unattributable.
        found_slug = owner_slug_of_row(line, root)
        if found_slug is None:
            continue
        # Confirm this slug names an archived design (completed only — in-flight
        # tp-designs rows are not stale even if the branch is absent; they are
        # still active by definition of being in tp-designs/).
        if not (completed / found_slug).is_dir():
            continue
        # Check branch absence
        branch_name = f"tp/{found_slug}"
        if branch_name in live_branches:
            continue
        results.append(StaleRow(path=rel_str, line=lineno, slug=found_slug))

    return results


# ------------------------------------------------------------------ #
# Aggregation — run_citation_checks + CitationReport
# ------------------------------------------------------------------ #


@dataclass
class Violation:
    """A single citation violation from any mechanically-checkable class."""
    path: str       # repo-relative
    line: int       # 1-based
    cls: str        # "number-cite" | "count-cite" | "dangling-path"
    cited_n: int    # the cited integer (for number-cite / count-cite) or 0
    detail: str     # human-readable context


@dataclass
class CitationReport:
    """Aggregated result from run_citation_checks."""
    violations: list[Violation]
    ok: bool


def run_citation_checks(repo_root) -> CitationReport:
    """Aggregate mechanically-checkable citation classes into CitationReport.

    Classes: number-cite (out-of-range/retired), count-cite (allowlist),
    dangling-path (dead tp-designs/* cites). Does NOT run a skill-name grep
    (inv 21/22 owns that — reminder (b)).

    Raises: OSError / ValueError if framework-check.sh is missing or unparseable
    (fail-closed: the caller should treat this as an internal error, exit 2).
    Individual sub-scan errors are swallowed (fail-open).
    """
    import citation_scan as _scan
    import invariant_map as _imap

    root = Path(repo_root)
    violations: list[Violation] = []

    # Parse framework-check.sh upfront — propagate on failure (fail-closed).
    fc = root / "framework-check.sh"
    _m = _imap.parse_invariant_map(fc)  # raises OSError/ValueError if corrupt
    _valid = _imap.valid_numbers(_m)
    _active = _imap.active_count(_m)

    try:
        for c in _scan.scan_number_cites(root):
            violations.append(Violation(
                path=c.path, line=c.line, cls="number-cite",
                cited_n=c.cited_n, detail=c.context,
            ))
    except Exception:
        pass

    try:
        for cc in _scan.scan_count_cites(root):
            violations.append(Violation(
                path=cc.path, line=cc.line, cls="count-cite",
                cited_n=cc.cited_n,
                detail=f"cited {cc.cited_n}, expected {cc.expected}",
            ))
    except Exception:
        pass

    try:
        for dc in dead_design_cites(root):
            violations.append(Violation(
                path=dc.path, line=dc.line, cls="dangling-path",
                cited_n=0, detail=f"slug={dc.slug} ({dc.kind})",
            ))
    except Exception:
        pass

    report = CitationReport(violations=violations, ok=len(violations) == 0)
    report._valid_numbers = _valid       # type: ignore[attr-defined]
    report._active_count = _active       # type: ignore[attr-defined]
    return report


def format_violations(report: CitationReport) -> list[str]:
    """Format CitationReport violations as repair lines.

    Format: ``file:line: <class>: <cited> (valid: <range-or-count>)``
    """
    lines = []
    valid = getattr(report, "_valid_numbers", set())
    active = getattr(report, "_active_count", 0)

    for v in report.violations:
        if v.cls == "number-cite":
            if valid:
                vrange = f"1-{max(valid)}"
            else:
                vrange = "unknown"
            lines.append(
                f"{v.path}:{v.line}: number-cite: #{v.cited_n} (valid: {vrange})"
            )
        elif v.cls == "count-cite":
            lines.append(
                f"{v.path}:{v.line}: count-cite: {v.cited_n} (valid: {active})"
            )
        else:
            lines.append(
                f"{v.path}:{v.line}: dangling-path: {v.detail}"
            )
    return lines


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #


def main(argv) -> int:
    """CLI: --repo --json [--remote]. ALWAYS returns 0."""
    parser = argparse.ArgumentParser(
        prog="citation_liveness.py",
        description="Report dead design cites and stale roadmap rows.",
    )
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Query origin for live branches (stale-row check)",
    )

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        return 0

    try:
        repo_root = Path(args.repo)
        dead_cites = dead_design_cites(repo_root)
    except Exception:
        dead_cites = []

    stale_rows: list[StaleRow] = []
    if args.remote:
        try:
            branches = live_remote_branches(repo_root)
            stale_rows = stale_status_rows(repo_root, branches)
        except Exception:
            stale_rows = []

    if args.json:
        data = {
            "dead_cites": [dataclasses.asdict(c) for c in dead_cites],
            "stale_rows": [dataclasses.asdict(r) for r in stale_rows],
        }
        print(json.dumps(data, indent=2))
    else:
        for c in dead_cites:
            print(f"dead-cite  {c.path}:{c.line}  slug={c.slug}  ({c.kind})")
        for r in stale_rows:
            print(f"stale-row  {r.path}:{r.line}  slug={r.slug}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
