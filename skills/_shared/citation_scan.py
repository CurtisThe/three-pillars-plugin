"""citation_scan — number-cite and count-cite scans over live prose.

Number-cite check = a BROAD out-of-range scan: walk LIVE_GLOBS, skip frozen
lines (citation_frozen.is_frozen), and emit a Citation for every cited integer
that is not in valid_numbers() OR is retired. The regex is keyword-anchored on
`invariant`/`inv` so PR/issue refs (`PR #123`, `issue #45`) never match; it also
handles bold/decorated (`**#27**`, `` `#27` ``), number-first (`the #27
invariant`), and chained (`invariant #25/#26/#27`, `#31/#32`) forms —
establishing invariant-context BEFORE the `/`-split so each chained member is
flagged. Sub-clause cites (`33b`) key on the leading integer only and are not
treated as independent cites without invariant-context.

Count-cite check = ALLOWLIST-scoped: COUNT_CITE_RE is evaluated ONLY at the
explicit COUNT_ALLOWLIST sites (current-state count assertions), compared to
active_count(). A non-allowlisted `N invariants` string is never flagged; a
missing allowlist entry fails OPEN (under-checks — the safe direction).

stdlib-only: re, pathlib, dataclasses. Reuses citation_frozen + invariant_map.

design: invariant-citation-coherence
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure _shared/ is on path for sibling imports
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import invariant_map  # noqa: E402
from citation_frozen import LIVE_GLOBS, is_frozen  # noqa: E402
from citation_liveness import _in_history  # noqa: E402

__all__ = [
    "Citation",
    "CountCite",
    "COUNT_ALLOWLIST",
    "scan_number_cites",
    "scan_count_cites",
    "find_number_cites_in_line",
]


# ------------------------------------------------------------------ #
# Data classes
# ------------------------------------------------------------------ #


@dataclass
class Citation:
    path: str       # repo-relative
    line: int       # 1-based
    cited_n: int    # the cited integer
    context: str    # the source line (stripped), for the repair message


@dataclass
class CountCite:
    path: str
    line: int
    cited_n: int     # the count the prose asserts
    expected: int    # active_count()


# ------------------------------------------------------------------ #
# Number-cite regexes
# ------------------------------------------------------------------ #

# A "decoration run" that may sit between the keyword/`#` and the number, or
# wrap a number: bold (**), backticks (`), and the hash itself.
_DECOR = r"[`*]*"

# Keyword-led: `invariant`/`inv` (optionally pluralised) then optional
# decoration + optional `#`, then a run of one-or-more `/`-separated numbers.
# Captures the whole numeric run (e.g. "25/#26/#27" or "21") so the caller can
# split it AFTER invariant-context is established.
_KEYWORD_LED_RE = re.compile(
    r"\b(?:invariants?|inv)\b"
    r"\s*" + _DECOR + r"#?" + _DECOR +
    r"(?P<run>\d+" + _DECOR + r"(?:\s*/\s*" + _DECOR + r"#?" + _DECOR + r"\d+" + _DECOR + r")*)"
)

# Number-first: a `#N` (optionally bold/backtick wrapped) that is the GRAMMATICAL
# SUBJECT of `invariant`/`inv` — i.e. DIRECTLY followed (no intervening words) by
# an optional `-class` then the keyword. Catches `the #27 invariant`,
# `#27-class invariant`, `#27 invariant`. The adjacency requirement is what keeps
# PR/issue prose (`PR #88 which adds the invariant checker`) from matching: the
# keyword there is separated from `#88` by intervening words.
_NUMBER_FIRST_RE = re.compile(
    _DECOR + r"#" + _DECOR + r"(?P<n>\d+)" + _DECOR +
    r"(?:-class)?\s+\binv(?:ariants?)?\b"
)

# Defense-in-depth: a `#N` immediately preceded by a PR/issue marker is a
# reference, never an invariant subject. Matched on the slice ENDING at the `#`.
_PR_ISSUE_MARKER_RE = re.compile(
    r"(?:pull request|PR|issue|GH|gh-)\s*$",
    re.IGNORECASE,
)

# Split a captured numeric run into its member integers (handles `#`, decoration).
_RUN_MEMBER_RE = re.compile(r"\d+")


def find_number_cites_in_line(line: str) -> list[int]:
    """Return the list of cited invariant integers on a single line.

    Establishes invariant-context (keyword-led OR number-first) BEFORE splitting
    chained `/`-runs, so `invariant #25/#26/#27` yields [25, 26, 27] while a
    bare `#45/#46` (no keyword) yields []. Duplicates are preserved in order
    (each cite site is an independent finding); the caller decides reporting.
    """
    cited: list[int] = []
    seen_spans: list[tuple[int, int]] = []

    # Pass 1: keyword-led (and chained). Context is the keyword itself.
    for m in _KEYWORD_LED_RE.finditer(line):
        run = m.group("run")
        for nm in _RUN_MEMBER_RE.finditer(run):
            cited.append(int(nm.group()))
        seen_spans.append((m.start(), m.end()))

    # Pass 2: number-first (`the #27 invariant`, `#27-class invariant`). The
    # `#N` must be the grammatical subject (adjacent to the keyword). Skip any
    # `#N` already consumed by a keyword-led match to avoid double-count, and any
    # `#N` immediately preceded by a PR/issue marker (`PR #88`, `issue #45`).
    for m in _NUMBER_FIRST_RE.finditer(line):
        s, e = m.start(), m.start("n") + len(m.group("n"))
        if any(s >= qs and e <= qe for qs, qe in seen_spans):
            continue
        # `m.start()` may include leading decoration; the `#` is at-or-after it.
        hash_pos = line.find("#", m.start(), m.start("n"))
        prefix = line[:hash_pos] if hash_pos != -1 else line[: m.start()]
        if _PR_ISSUE_MARKER_RE.search(prefix):
            continue
        cited.append(int(m.group("n")))

    return cited


# ------------------------------------------------------------------ #
# Number-cite scan (broad, over LIVE_GLOBS, minus frozen lines)
# ------------------------------------------------------------------ #


# Path segments whose contents are NOT live prose: test fixtures and eval
# corpora deliberately plant synthetic/out-of-range numbers. Mirrors
# citation_liveness._CODE_EXCLUDED_SEGMENTS.
_EXCLUDED_SEGMENTS = frozenset({"fixtures", "eval", "__pycache__"})


def _is_excluded(rel: str) -> bool:
    """True for test modules and fixture/eval corpora (not live prose)."""
    parts = rel.replace("\\", "/").split("/")
    if any(seg in _EXCLUDED_SEGMENTS for seg in parts):
        return True
    # `test_*.py` modules plant synthetic out-of-range cites as fixtures.
    name = parts[-1]
    if name.startswith("test_") and name.endswith(".py"):
        return True
    return False


def _iter_glob_files(root: Path):
    """Yield (Path, rel_str) for every file matched by LIVE_GLOBS, de-duped.

    Test modules and fixture/eval corpora are skipped — they plant synthetic
    out-of-range numbers that are not live invariant assertions.
    """
    seen: set[Path] = set()
    for pattern in LIVE_GLOBS:
        for fpath in root.glob(pattern):
            if not fpath.is_file():
                continue
            rp = fpath.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                rel_check = str(fpath.relative_to(root))
            except ValueError:
                rel_check = str(fpath)
            if _is_excluded(rel_check):
                continue
            try:
                rel = str(fpath.relative_to(root))
            except ValueError:
                rel = str(fpath)
            yield fpath, rel


def scan_number_cites(repo_root) -> list[Citation]:
    """Emit a Citation for every out-of-range/retired invariant-number cite.

    Walks LIVE_GLOBS, tracks in_history/in_fence per file (the citation_liveness
    loop shape, reusing _in_history on each `## ` heading), skips frozen lines
    via citation_frozen.is_frozen, and flags any cited integer not in
    valid_numbers() OR whose header is retired.
    """
    root = Path(repo_root)
    fc = root / "framework-check.sh"
    m = invariant_map.parse_invariant_map(fc)
    valid = invariant_map.valid_numbers(m)
    retired = {n for n, inv in m.items() if inv.status == "retired"}

    results: list[Citation] = []
    for fpath, rel in _iter_glob_files(root):
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        in_history = False
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if line.startswith("# ") and not line.startswith("## "):
                in_history = False
            if line.startswith("## "):
                in_history = _in_history(line[3:].strip())
            if is_frozen(rel, line, in_history=in_history, in_fence=in_fence):
                continue
            for n in find_number_cites_in_line(line):
                if n not in valid or n in retired:
                    results.append(
                        Citation(
                            path=rel,
                            line=lineno,
                            cited_n=n,
                            context=line.strip(),
                        )
                    )
    return results


# ------------------------------------------------------------------ #
# Count-cite scan (allowlist-scoped)
# ------------------------------------------------------------------ #

# A current-state count assertion: "N invariant(s)".
COUNT_CITE_RE = re.compile(r"\b(\d+)\s+invariants?\b")

# Allowlist = the ONLY sites the count check evaluates. Each entry is
# (rel_path, line_matcher_regex): the matcher pins the exact assertion line so
# unrelated `N invariants` prose in the same file is never checked.
COUNT_ALLOWLIST: list[tuple[str, re.Pattern]] = [
    # SECURITY.md — the released, adopter-facing invariant-count line.
    ("SECURITY.md", re.compile(r"framework invariant checker.*\b\d+\s+invariants?\b")),
    # framework-check.sh — the runtime banner (structurally derived; the entry
    # guards against a future reintroduced literal).
    ("framework-check.sh", re.compile(r"all\s+\S+\s+invariants?\s+passed")),
]


def scan_count_cites(repo_root, allowlist=None) -> list[CountCite]:
    """Evaluate count-cites ONLY at the allowlisted sites.

    For each (rel_path, matcher) entry: find every matching line, extract the
    cited integer, and emit a CountCite when it differs from active_count(). A
    line that does not match the entry's matcher is not checked. A missing file
    or no matching line fails OPEN (nothing emitted) — the safe direction.
    """
    if allowlist is None:
        allowlist = COUNT_ALLOWLIST
    root = Path(repo_root)
    fc = root / "framework-check.sh"
    m = invariant_map.parse_invariant_map(fc)
    expected = invariant_map.active_count(m)

    results: list[CountCite] = []
    for rel, matcher in allowlist:
        fpath = root / rel
        if not fpath.is_file():
            continue  # fail-open: missing site is under-checked, not flagged
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not matcher.search(line):
                continue
            num = COUNT_CITE_RE.search(line)
            if not num:
                continue  # banner with derived `${_INV_N}` has no literal int
            cited = int(num.group(1))
            if cited != expected:
                results.append(
                    CountCite(
                        path=rel,
                        line=lineno,
                        cited_n=cited,
                        expected=expected,
                    )
                )
    return results
