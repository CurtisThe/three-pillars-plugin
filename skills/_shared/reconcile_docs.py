"""reconcile_docs — rewriter + sweep (the ONLY doc writer for this design).

Three CLI modes (mutually exclusive):
  --slug {name} [--pr NN] --apply   post-merge micro-step
  --archive-cites --slug {name}     archive-time cite rewrite (no status flip)
  --sweep                           one-time (or re-runnable) debt sweep

Reporter by default; --apply to write.
Always exits 0.
stdlib-only: re, pathlib, subprocess, json, argparse, dataclasses, datetime.

design: post-merge-doc-reconcile
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure _shared/ is on path for sibling import
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import citation_liveness
from citation_liveness import (
    DeadCite,
    STALE_STATUS_RE,
    dead_design_cites,
    live_remote_branches,
    owner_slug_of_row,
    stale_status_rows,
)


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #


@dataclass
class Edit:
    path: str
    line: int
    before: str
    after: str
    kind: str    # "repoint" | "status-flip"
    slug: str = ""


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #


def _today() -> str:
    return datetime.date.today().isoformat()


_LAST_UPDATED_RE = re.compile(
    r"(\*Last updated:\s*)\d{4}-\d{2}-\d{2}(.*\*)", re.IGNORECASE
)


def _bump_last_updated(content: str) -> str:
    """Replace the *Last updated: YYYY-MM-DD* date with today's date."""
    today = _today()

    def _replacer(m):
        return m.group(1) + today + m.group(2)

    new_content, count = _LAST_UPDATED_RE.subn(_replacer, content, count=1)
    return new_content


def _is_in_history(heading_text: str) -> bool:
    return "History" in heading_text


# _owner_slug_from_row is replaced by owner_slug_of_row imported from
# citation_liveness (single shared implementation — ONE definition total).
# _compute_history_state was dead code (zero call sites); deleted here.
# History tracking is handled inline in flip_status below.


# ------------------------------------------------------------------ #
# repoint_cites
# ------------------------------------------------------------------ #


def _repoint_line(line: str, slug: str) -> str:
    """Rewrite dead tp-designs/{slug} cites to completed-tp-designs/{slug}.

    Uses a boundary-aware anchored regex:
    - (?<!completed-)(?<!superseded-)  lookbehinds prevent double-prefix on
      already-correct cites and suppress superseded- prefixed paths
    - (?![a-z0-9-])                    lookahead prevents clobbering prefix-sharing
                                        slugs (e.g. archived 'foo' must not mangle
                                        'foo-bar' cites)

    Idempotent: already-correct completed- cites are never touched.
    """
    pattern = re.compile(
        r"(?<!completed-)(?<!superseded-)tp-designs/" + re.escape(slug) + r"(?![a-z0-9-])"
    )
    return pattern.sub(f"completed-tp-designs/{slug}", line)


def repoint_cites_with_skipped(
    repo_root, slugs: set | None = None, *, apply: bool
) -> tuple[list[Edit], list[dict]]:
    """Rewrite dead tp-designs/{slug} cites to completed-tp-designs/{slug}.

    Uses dead_design_cites as the detector; writes are line-local boundary-aware
    regex substitutions. History lines and archived/inflight dirs are excluded
    (inherited from the detector's scope rules).

    slugs=None means all archived slugs.
    apply=False returns the plan without writing.

    Returns (edits, skipped) where skipped is a list of dicts:
      {file: str, line_no: int, reason: "decode-failure"}

    Files with undecodable bytes are skipped in both plan and apply modes — the
    plan is a faithful preview of apply (no silent decode-skip discrepancy).
    """
    root = Path(repo_root)
    findings = dead_design_cites(root)

    # Filter by slug if specified
    if slugs is not None:
        findings = [f for f in findings if f.slug in slugs]

    if not findings:
        return [], []

    # Group findings by file path
    from collections import defaultdict
    by_file: dict[str, list[DeadCite]] = defaultdict(list)
    for f in findings:
        by_file[f.path].append(f)

    edits: list[Edit] = []
    skipped: list[dict] = []

    for rel_path, file_findings in by_file.items():
        abs_path = root / rel_path
        # Strict-UTF8 probe in BOTH plan and apply modes so that plan is a faithful
        # preview of apply: skip files with undecodable bytes and emit a skipped
        # entry rather than rewriting U+FFFD-corrupted content silently.
        _, had_error = _read_strict_utf8(abs_path)
        if had_error:
            # Skip this file in both modes — emit skipped entry (not silent)
            skipped.append({
                "file": rel_path,
                "line_no": 0,
                "reason": "decode-failure",
            })
            continue
        try:
            original = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        lines = original.splitlines(keepends=True)
        new_lines = list(lines)
        file_edits: list[Edit] = []

        # Deduplicate findings per line: multiple same-slug findings on the same
        # line (the detector may emit one per cite occurrence) should be processed
        # exactly once — the regex replaces ALL occurrences on the line in one pass.
        seen_line_slug: set[tuple[int, str]] = set()

        for finding in file_findings:
            lineno = finding.line  # 1-based
            idx = lineno - 1
            if idx >= len(new_lines):
                continue
            key = (lineno, finding.slug)
            if key in seen_line_slug:
                continue
            seen_line_slug.add(key)

            old_line = new_lines[idx]
            new_line = _repoint_line(old_line, finding.slug)
            if new_line == old_line:
                # Boundary-aware sub found nothing to change (already correct or
                # false-positive from detector after a prior pass on the same line)
                continue
            file_edits.append(
                Edit(
                    path=rel_path,
                    line=lineno,
                    before=old_line.rstrip("\n"),
                    after=new_line.rstrip("\n"),
                    kind="repoint",
                    slug=finding.slug,
                )
            )
            new_lines[idx] = new_line

        if not file_edits:
            continue

        if apply:
            new_content = "".join(new_lines)
            # Bump Last updated if it's a living doc
            if rel_path.startswith("three-pillars-docs/") and rel_path.endswith(".md"):
                new_content = _bump_last_updated(new_content)
            abs_path.write_text(new_content, encoding="utf-8")

        edits.extend(file_edits)

    return edits, skipped


def repoint_cites(repo_root, slugs: set | None = None, *, apply: bool) -> list[Edit]:
    """Rewrite dead tp-designs/{slug} cites to completed-tp-designs/{slug}.

    Backward-compatible wrapper around repoint_cites_with_skipped.
    Returns only the edits list; skipped entries are discarded.
    Callers that need the skipped list should call repoint_cites_with_skipped directly.
    """
    edits, _skipped = repoint_cites_with_skipped(repo_root, slugs=slugs, apply=apply)
    return edits


# ------------------------------------------------------------------ #
# flip_status
# ------------------------------------------------------------------ #


def _quoted_spans(line: str, *, is_table_row: bool = True) -> list[tuple[int, int]]:
    """Return list of (start, end) spans that are inside double-quote or backtick pairs.

    A match whose span falls entirely within one of these spans is prose — skip it.
    Handles non-overlapping pairs left-to-right.

    is_table_row=True (default): quote pairing is reset at unescaped cell separators
    ('|') so a stray unbalanced quote in one cell cannot swallow content in a
    subsequent cell.

    is_table_row=False (bullet rows): '|' is ordinary prose — quote pairing is NOT
    reset at '|', so a quoted fragment containing a pipe retains its full span.
    Callers that process bullet rows must pass is_table_row=False to avoid treating
    prose pipes as cell boundaries.
    """
    spans = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in ('"', "`"):
            close = -1
            j = i + 1
            while j < n:
                if line[j] == ch:
                    close = j
                    break
                # Cell separator terminates quote search ONLY on table rows
                if is_table_row and line[j] == "|" and (j == 0 or line[j - 1] != "\\"):
                    # Unescaped cell separator — quote doesn't close across cells
                    break
                j += 1
            if close != -1:
                spans.append((i, close + 1))
                i = close + 1
            else:
                i += 1
        else:
            i += 1
    return spans


def _is_in_quoted_span(start: int, end: int, quoted_spans: list[tuple[int, int]]) -> bool:
    """Return True if the match [start, end) falls entirely within any quoted span."""
    for qs, qe in quoted_spans:
        if start >= qs and end <= qe:
            return True
    return False


def _read_strict_utf8(path: Path) -> tuple[str | None, bool]:
    """Read a file strictly as UTF-8 without replacement characters.

    Returns (content, had_decode_error):
      - (text, False) on clean read
      - (None, True) when the file contains bytes that errors='replace' would
        introduce U+FFFD (i.e. genuine decode failures)

    The detector path uses errors='replace' for leniency; the WRITE path must
    refuse to rewrite a file whose content would be corrupted.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None, False  # OSError — not a decode failure per se
    try:
        text = raw.decode("utf-8")
        return text, False
    except UnicodeDecodeError:
        return None, True


def flip_status_with_skipped(
    repo_root, slug: str, pr_number: int | None, *, apply: bool
) -> tuple[list[Edit], list[dict]]:
    """Rewrite STALE_STATUS_RE rows naming {slug} to the merged label.

    Returns (edits, skipped) where skipped is a list of dicts:
      {file: str, line_no: int, reason: "ambiguous-multi-match"|"decode-failure"|"unattributable"}

    Only touches rows outside ## History sections and outside fenced code blocks.
    After applying, bumps *Last updated:* date.
    Does NOT append a History line (that's the calling SKILL's job).

    Attribution: uses owner_slug_of_row (directory-resolving, shared with
    citation_liveness). A row is attributed to {slug} only when owner_slug_of_row
    returns exactly {slug}.

    Status-flip anchoring (quote-aware): scans for STALE_STATUS_RE matches that
    are NOT inside double-quote or backtick pairs (those are prose mentions, never
    flipped). If exactly one unquoted match -> flip it. If zero -> no edit.
    If >1 unquoted matches -> skip + add to skipped list with reason
    'ambiguous-multi-match' (loud, not silent).

    Write path safety: if the file contains bytes that would introduce U+FFFD on
    decode-then-encode, the file is skipped entirely with reason 'decode-failure'.
    """
    root = Path(repo_root)
    roadmap = root / "three-pillars-docs" / "product_roadmap.md"
    skipped: list[dict] = []

    if not roadmap.is_file():
        return [], skipped

    try:
        rel_str = str(roadmap.relative_to(root))
    except ValueError:
        rel_str = str(roadmap)

    # Read with replacement for detection pass (lenient)
    try:
        original = roadmap.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], skipped

    # Safety: check for undecodable bytes in BOTH plan and apply modes so that
    # plan is a faithful preview of what --apply will do (finding 4 fix).
    _, had_error = _read_strict_utf8(roadmap)
    if had_error:
        skipped.append({
            "file": rel_str,
            "line_no": 0,
            "reason": "decode-failure",
        })
        return [], skipped

    lines = original.splitlines(keepends=True)
    new_lines = list(lines)
    edits: list[Edit] = []

    if pr_number is not None:
        replacement = f"merged PR #{pr_number}"
    else:
        replacement = "merged"

    in_history = False
    in_fence = False
    for idx, line in enumerate(lines):
        stripped = line.rstrip("\n")
        # Track fenced code block state
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## "):
            in_history = _is_in_history(stripped[3:].strip())
            continue
        if stripped.startswith("# "):
            # H1 heading also exits any history scope
            in_history = False
            continue
        if in_history:
            continue
        if not STALE_STATUS_RE.search(line):
            continue
        # Quote-aware status-flip: collect STALE_STATUS_RE matches that are
        # NOT inside double-quote or backtick pairs.
        # Bullet rows treat '|' as prose — pipe-reset applies to table rows only.
        # IMPORTANT: check zero-unquoted-matches BEFORE attribution so that
        # fully-quoted prose mentions are consistently suppressed regardless of
        # whether the line is attributable (avoids eternal 'unattributable' noise
        # for quoted-only status mentions on non-attributable lines).
        _is_table_row = not bool(re.match(r"^\s*[-*]\s", stripped))
        quoted_spans = _quoted_spans(line, is_table_row=_is_table_row)
        all_matches = list(STALE_STATUS_RE.finditer(line))
        unquoted = [
            m for m in all_matches
            if not _is_in_quoted_span(m.start(), m.end(), quoted_spans)
        ]
        if len(unquoted) == 0:
            # All matches are prose/quoted — no edit (suppress before attribution)
            continue
        # Attribute by the row's OWN slug using directory-resolving logic
        # (single shared implementation imported from citation_liveness).
        # NO whole-line fallback — a row whose owner cannot be directory-resolved
        # is unattributable and added to skipped (loud, per docstring contract).
        row_slug = owner_slug_of_row(line, root)
        if row_slug is None:
            skipped.append({
                "file": rel_str,
                "line_no": idx + 1,
                "reason": "unattributable",
            })
            continue
        if row_slug != slug:
            continue
        if len(unquoted) > 1:
            # Ambiguous: >1 unquoted match — skip with loud reporting
            skipped.append({
                "file": rel_str,
                "line_no": idx + 1,
                "reason": "ambiguous-multi-match",
            })
            continue
        # Exactly one unquoted match — flip it
        m = unquoted[0]
        new_line = line[:m.start()] + replacement + line[m.end():]
        if new_line == line:
            continue
        edits.append(
            Edit(
                path=rel_str,
                line=idx + 1,
                before=stripped,
                after=new_line.rstrip("\n"),
                kind="status-flip",
                slug=slug,
            )
        )
        new_lines[idx] = new_line

    if edits and apply:
        new_content = "".join(new_lines)
        new_content = _bump_last_updated(new_content)
        roadmap.write_text(new_content, encoding="utf-8")

    return edits, skipped


def flip_status(
    repo_root, slug: str, pr_number: int | None, *, apply: bool
) -> list[Edit]:
    """Backward-compatible wrapper around flip_status_with_skipped.

    Returns only the edits list; skipped entries are discarded.
    Callers that need the skipped list should call flip_status_with_skipped directly.
    """
    edits, _skipped = flip_status_with_skipped(repo_root, slug, pr_number, apply=apply)
    return edits


# ------------------------------------------------------------------ #
# merged_pr_number
# ------------------------------------------------------------------ #


def merged_pr_number(repo_root, slug: str, gh_fn=None) -> int | None:
    """Query gh for the max merged PR number for tp/{slug}.

    Returns max number, or None on failure (fail-open).
    """
    if gh_fn is None:
        def gh_fn(*args, **kwargs):
            return subprocess.run(*args, **kwargs)

    try:
        result = gh_fn(
            ["gh", "pr", "list", "--state", "merged",
             "--head", f"tp/{slug}", "--json", "number"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        numbers = [item["number"] for item in data if isinstance(item.get("number"), int)]
        if not numbers:
            return None
        return max(numbers)
    except Exception:
        return None


# ------------------------------------------------------------------ #
# archive_cites (--archive-cites mode)
# ------------------------------------------------------------------ #


def archive_cites_with_skipped(
    repo_root, slug: str, *, apply: bool
) -> tuple[list[Edit], list[dict]]:
    """Repoint cites for {slug} only. No status flip.

    Returns (edits, skipped). See repoint_cites_with_skipped for skipped semantics.
    Used at archive time (design-complete step 6f).
    """
    return repoint_cites_with_skipped(repo_root, slugs={slug}, apply=apply)


def archive_cites(repo_root, slug: str, *, apply: bool) -> list[Edit]:
    """Repoint cites for {slug} only. No status flip.

    Backward-compatible wrapper around archive_cites_with_skipped.
    Used at archive time (design-complete step 6f).
    """
    edits, _skipped = archive_cites_with_skipped(repo_root, slug, apply=apply)
    return edits


# ------------------------------------------------------------------ #
# reconcile_slug (--slug mode)
# ------------------------------------------------------------------ #


def reconcile_slug_with_skipped(
    repo_root, slug: str, pr_number: int | None = None, *, apply: bool
) -> tuple[list[Edit], list[dict]]:
    """Post-merge micro-step: repoint cites + flip roadmap status.

    Returns (edits, skipped). See flip_status_with_skipped and
    repoint_cites_with_skipped for skipped semantics (decode-failure entries from
    both sub-steps are surfaced here).

    Skipped entries are deduplicated on (file, line_no, reason) so a file that
    both has a dead cite AND an undecodable byte sequence produces exactly one
    decode-failure entry rather than two.
    """
    root = Path(repo_root)
    edits: list[Edit] = []
    all_skipped: list[dict] = []

    # Repoint cites — collect skipped (decode-failure) entries too
    repoint_edits, repoint_skipped = repoint_cites_with_skipped(root, slugs={slug}, apply=apply)
    edits.extend(repoint_edits)
    all_skipped.extend(repoint_skipped)

    # Resolve PR number if not given — in BOTH plan and apply mode so that the
    # plan accurately previews the replacement text (finding 7 fix)
    if pr_number is None:
        pr_number = merged_pr_number(root, slug)

    # Flip status
    flip_edits, flip_skipped = flip_status_with_skipped(root, slug, pr_number, apply=apply)
    edits.extend(flip_edits)
    all_skipped.extend(flip_skipped)

    # Deduplicate skipped entries on (file, line_no, reason)
    seen: set[tuple[str, int, str]] = set()
    deduped: list[dict] = []
    for entry in all_skipped:
        key = (entry.get("file", ""), entry.get("line_no", 0), entry.get("reason", ""))
        if key not in seen:
            seen.add(key)
            deduped.append(entry)
    all_skipped = deduped

    return edits, all_skipped


def reconcile_slug(
    repo_root, slug: str, pr_number: int | None = None, *, apply: bool
) -> list[Edit]:
    """Post-merge micro-step: repoint cites + flip roadmap status.

    PR number self-resolved via merged_pr_number when not passed — both in plan
    and apply modes, so the dry-run plan is a faithful preview of what --apply
    will write (not a generic 'merged' while --apply writes 'merged PR #NN').
    """
    edits, _skipped = reconcile_slug_with_skipped(repo_root, slug, pr_number, apply=apply)
    return edits


# ------------------------------------------------------------------ #
# sweep (--sweep mode)
# ------------------------------------------------------------------ #


def sweep_with_skipped(
    repo_root,
    *,
    apply: bool,
    remote: bool = True,
    _live_branches_fn=None,
) -> tuple[list[Edit], list[dict]]:
    """One-time (re-runnable) debt sweep.

    For every archived slug: repoint_cites (fixes dead code + living-doc cites).
    Then flip_status for slugs whose tp/{slug} is confirmed absent from live_branches.
    When live_branches is None (offline): flip nothing.

    Returns (edits, skipped). See flip_status_with_skipped for skipped semantics.
    """
    root = Path(repo_root)
    edits: list[Edit] = []
    all_skipped: list[dict] = []

    # Discover all archived slugs
    completed_dir = root / "three-pillars-docs" / "completed-tp-designs"
    if not completed_dir.is_dir():
        return [], []
    archived_slugs = {d.name for d in completed_dir.iterdir() if d.is_dir()}

    if not archived_slugs:
        return [], []

    # Repoint all archived slugs — collect skipped (decode-failure) entries too
    repoint_edits, repoint_skipped = repoint_cites_with_skipped(
        root, slugs=archived_slugs, apply=apply
    )
    edits.extend(repoint_edits)
    all_skipped.extend(repoint_skipped)

    # Status flips — only for merge-confirmed absent slugs
    live_branches: set | None = None
    if remote:
        if _live_branches_fn is not None:
            live_branches = _live_branches_fn(root)
        else:
            live_branches = live_remote_branches(root)
        # None => can't know => flip nothing

    if live_branches is not None:
        for slug in archived_slugs:
            branch_name = f"tp/{slug}"
            if branch_name not in live_branches:
                flip_edits, flip_skipped = flip_status_with_skipped(
                    root, slug, pr_number=None, apply=apply
                )
                edits.extend(flip_edits)
                all_skipped.extend(flip_skipped)

    # Deduplicate skipped entries by (file, line_no, reason) — the per-slug flip
    # loop can emit identical unattributable entries for the same row once per
    # absent slug, producing N-fold duplicates for N archived slugs.
    seen_skipped: set[tuple] = set()
    deduped_skipped: list[dict] = []
    for entry in all_skipped:
        key = (entry.get("file", ""), entry.get("line_no", 0), entry.get("reason", ""))
        if key not in seen_skipped:
            seen_skipped.add(key)
            deduped_skipped.append(entry)

    return edits, deduped_skipped


def sweep(
    repo_root,
    *,
    apply: bool,
    remote: bool = True,
    _live_branches_fn=None,
) -> list[Edit]:
    """One-time (re-runnable) debt sweep. Backward-compatible wrapper."""
    edits, _skipped = sweep_with_skipped(
        repo_root, apply=apply, remote=remote, _live_branches_fn=_live_branches_fn
    )
    return edits


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #


def main(argv) -> int:
    """CLI: three mutually-exclusive modes. ALWAYS returns 0."""
    parser = argparse.ArgumentParser(
        prog="reconcile_docs.py",
        description="Reconcile design cites and roadmap statuses.",
    )
    parser.add_argument("--repo", default=".", help="Path to repo root")
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--slug", help="Post-merge or archive-cites slug")
    mode_group.add_argument("--sweep", action="store_true", help="One-time sweep")

    parser.add_argument("--pr", type=int, help="PR number (--slug mode)")
    parser.add_argument(
        "--archive-cites",
        action="store_true",
        dest="archive_cites",
        help="Archive-time mode (repoint only, no flip); requires --slug, conflicts with --sweep",
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        default=True,
        help="Query remote for live branches (sweep mode)",
    )
    parser.add_argument(
        "--no-remote",
        action="store_false",
        dest="remote",
        help="Skip remote branch query",
    )

    try:
        args = parser.parse_args(argv[1:])
    except SystemExit:
        return 0

    # Validate: --archive-cites conflicts with --sweep (check before requires-slug
    # so that --sweep --archive-cites hits this path, not the requires-slug path)
    if args.archive_cites and args.sweep:
        msg = "--archive-cites and --sweep are mutually exclusive"
        if args.json:
            print(json.dumps({"error": msg, "edits": [], "skipped": []}))
        else:
            print(f"error: {msg}")
        return 0

    # Validate: --archive-cites requires --slug
    if args.archive_cites and not args.slug:
        msg = "--archive-cites requires --slug"
        if args.json:
            print(json.dumps({"error": msg, "edits": [], "skipped": []}))
        else:
            print(f"error: {msg}")
        return 0

    repo_root = Path(args.repo)
    edits: list[Edit] = []
    all_skipped: list[dict] = []
    error_msg: str | None = None

    try:
        if args.sweep:
            edits, all_skipped = sweep_with_skipped(
                repo_root, apply=args.apply, remote=args.remote
            )
        elif args.slug and args.archive_cites:
            arc_edits, arc_skipped = archive_cites_with_skipped(
                repo_root, args.slug, apply=args.apply
            )
            edits.extend(arc_edits)
            all_skipped.extend(arc_skipped)
        elif args.slug:
            # Run slug steps incrementally so partial results survive an exception.
            # repoint_cites_with_skipped runs first; if flip_status subsequently raises,
            # the repoint edits are preserved in the output payload.
            repoint_edits, repoint_skipped = repoint_cites_with_skipped(
                repo_root, slugs={args.slug}, apply=args.apply
            )
            edits.extend(repoint_edits)
            all_skipped.extend(repoint_skipped)
            pr_number = args.pr
            if pr_number is None:
                pr_number = merged_pr_number(repo_root, args.slug)
            flip_edits, flip_skipped = flip_status_with_skipped(
                repo_root, args.slug, pr_number, apply=args.apply
            )
            edits.extend(flip_edits)
            all_skipped.extend(flip_skipped)
            # Deduplicate skipped entries on (file, line_no, reason) — a file with
            # both a dead cite and an undecodable byte sequence must not emit two
            # identical decode-failure entries.
            seen_keys: set[tuple[str, int, str]] = set()
            deduped_skipped: list[dict] = []
            for entry in all_skipped:
                key = (entry.get("file", ""), entry.get("line_no", 0), entry.get("reason", ""))
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped_skipped.append(entry)
            all_skipped = deduped_skipped
        # else: no mode specified — no-op
    except Exception as exc:
        # Preserve already-accumulated edits (callers key on edit list for commits)
        error_msg = str(exc) or repr(exc)

    if args.json:
        payload: dict = {
            "edits": [dataclasses.asdict(e) for e in edits],
            "skipped": all_skipped,
        }
        if error_msg is not None:
            payload["error"] = error_msg
        print(json.dumps(payload, indent=2))
    else:
        if error_msg is not None:
            print(f"error: {error_msg}")
        for e in edits:
            marker = "[applied]" if args.apply else "[plan]"
            print(f"{marker} {e.kind}  {e.path}:{e.line}  slug={e.slug}")
        for s in all_skipped:
            print(f"[skipped] {s['reason']}  {s['file']}:{s['line_no']}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
