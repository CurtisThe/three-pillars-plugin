#!/usr/bin/env python3
"""Round-2 short-circuit helper for `/tp-plan-audit --auto`.

When all three Round-1 council outputs flag the same highest-severity
finding, Round 2 cross-examination is unlikely to add information; skip
it and surface the converged topic to the caller. The caller writes the
decisions.md entry — this module is pure (no I/O).

See detailed-design.md §round2_short_circuit.py and §Decisions OQ5.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

_SEVERITY_RE = re.compile(
    r"\b(MISSING|INCONSISTENT|ORDERING|INCOMPLETE|MISALIGNMENT)\b"
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "the", "is", "are", "was", "were", "be", "been",
        "being", "of", "in", "on", "at", "to", "for", "with", "from", "by",
        "as", "or", "but", "not", "no", "this", "that", "these", "those",
        "it", "its", "if", "then", "so", "do", "does", "did", "has", "have",
        "had", "will", "would", "could", "should", "may", "might", "can",
        "i", "we", "you", "they", "he", "she",
    }
)
_NOUN_PHRASE_LEN = 6


def _extract_topic_bag(text: str) -> set[str] | None:
    """Return a token bag for the first highest-severity finding in text.

    Returns None when no severity keyword is found (e.g. "no issues").
    """
    match = _SEVERITY_RE.search(text)
    if match is None:
        return None
    category = match.group(1).lower()
    tail = text[match.end():]
    raw_tokens = _TOKEN_RE.findall(tail)
    phrase_tokens: list[str] = []
    for tok in raw_tokens:
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        phrase_tokens.append(low)
        if len(phrase_tokens) >= _NOUN_PHRASE_LEN:
            break
    bag = {category} | set(phrase_tokens)
    return bag


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def should_short_circuit(round1_outputs: Iterable[str]) -> dict:
    """Decide whether Round 2 is redundant.

    Returns a dict `{short_circuit: bool, converged_topic: str|None, evidence: dict}`.
    Pure function — no file I/O.
    """
    outputs = list(round1_outputs)
    bags: list[set[str] | None] = [_extract_topic_bag(o) for o in outputs]
    evidence: dict = {
        "bag_count": sum(1 for b in bags if b is not None),
        "total_outputs": len(outputs),
        "pairwise_jaccard": [],
    }

    # Per detailed-design §round2_short_circuit and SKILL.md Step 3.5,
    # the heuristic is defined over the three Round-1 council outputs.
    # Refuse to short-circuit on fewer inputs — a 2-of-2 unanimity is
    # not the same statistical signal as 3-of-3.
    if any(b is None for b in bags) or len(bags) < 3:
        evidence["reason"] = (
            "fewer-than-3-outputs" if len(bags) < 3 else "missing-or-empty-finding"
        )
        return {"short_circuit": False, "converged_topic": None, "evidence": evidence}

    # Pairwise Jaccard ≥ 0.5 across all pairs.
    threshold = 0.5
    pairs = []
    for i in range(len(bags)):
        for j in range(i + 1, len(bags)):
            score = _jaccard(bags[i], bags[j])
            pairs.append(score)
    evidence["pairwise_jaccard"] = pairs

    if all(score >= threshold for score in pairs):
        joined = [" ".join(sorted(b)) for b in bags]
        topic = min(joined)
        evidence["reason"] = "all-pairs-above-threshold"
        return {"short_circuit": True, "converged_topic": topic, "evidence": evidence}

    evidence["reason"] = "below-threshold"
    return {"short_circuit": False, "converged_topic": None, "evidence": evidence}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for round2_short_circuit.

    Usage: round2_short_circuit.py <file1> <file2> [<file3> ...]

    Reads each file, calls should_short_circuit(texts), prints the verdict
    dict as JSON to stdout. Exit 0 (verdict computed), 2 (usage/unreadable).
    """
    parser = argparse.ArgumentParser(
        prog="round2_short_circuit.py",
        description=(
            "Round-2 short-circuit helper: reads round-1 council outputs "
            "and decides whether Round 2 is redundant."
        ),
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="Paths to round-1 output files (at least 2 required).",
    )
    args = parser.parse_args(argv)

    if len(args.files) < 2:
        parser.error("At least 2 FILE arguments are required.")

    texts: list[str] = []
    for path_str in args.files:
        p = Path(path_str)
        try:
            texts.append(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            parser.error(f"Cannot read file {path_str!r}: {exc}")

    verdict = should_short_circuit(texts)
    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
