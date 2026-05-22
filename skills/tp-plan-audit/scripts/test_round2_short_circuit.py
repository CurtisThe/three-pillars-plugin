#!/usr/bin/env python3
"""Tests for round2_short_circuit.py — Jaccard topic-match across Round-1 outputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import round2_short_circuit as rs


def test_unanimity_and_dissent():
    # (a) Three agents flag the same MISSING + same noun-phrase ⇒ short-circuit.
    # All three statements use the same `candidate-branch` hyphenation so they
    # tokenize identically per the [A-Za-z0-9_.-]+ token regex; if a future
    # change splits hyphens, this fixture will catch the drift.
    unanimous = [
        "MISSING: candidate-branch fork point is undocumented",
        "MISSING: candidate-branch fork point not specified",
        "MISSING: candidate-branch fork point is unclear",
    ]
    result = rs.should_short_circuit(unanimous)
    assert result["short_circuit"] is True, f"unanimity ⇒ short-circuit, got {result!r}"
    topic_tokens = set(result["converged_topic"].split())
    assert {"missing", "candidate-branch"}.issubset(topic_tokens), (
        f"converged_topic should contain {{missing, candidate-branch}} as bag-members; "
        f"got {topic_tokens!r}"
    )

    # (b) Two agree, one dissents on category ⇒ no short-circuit.
    dissent = [
        "MISSING: candidate-branch fork point is undocumented",
        "MISSING: candidate-branch fork point not specified",
        "INCONSISTENT: task ordering is wrong",
    ]
    result = rs.should_short_circuit(dissent)
    assert result["short_circuit"] is False, f"dissent ⇒ no short-circuit, got {result!r}"

    # (c) All three findings empty (no issues at all) ⇒ no short-circuit.
    empty = ["no issues found", "all checks pass", "looks good"]
    result = rs.should_short_circuit(empty)
    assert result["short_circuit"] is False, f"empty findings ⇒ no short-circuit, got {result!r}"

    # (d) Reordering preserves verdict (idempotency).
    reordered = list(reversed(unanimous))
    r1 = rs.should_short_circuit(unanimous)
    r2 = rs.should_short_circuit(reordered)
    assert r1["short_circuit"] == r2["short_circuit"], "reorder ⇒ same short_circuit"
    assert r1["converged_topic"] == r2["converged_topic"], "reorder ⇒ same converged_topic"


if __name__ == "__main__":
    test_unanimity_and_dissent()
    print("ALL PASSED")
