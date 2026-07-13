"""Unit tests for converge.py's run_round stdin payload + digest plumbing.

Phase 1 (Tasks 1.1–1.2): the trap-(b) PosixPath→str stdin boundary and the
trap-(c) label-count list[tuple] digest mechanics, unit-tested in isolation
before the ordered orchestration (Phase 2) wires them together. Hermetic — no
live gh, no network, no subprocess.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import converge  # noqa: E402
import review_proof  # noqa: E402


# ============================================================
# Task 1.1 — build_run_round_stdin: PosixPath → str, decisions_path omitted
# ============================================================


def test_build_run_round_stdin_json_safe_and_str_paths(tmp_path):
    """review_proof_root (a PosixPath) is str()-ed so json.dumps never raises."""
    payload = converge.build_run_round_stdin(
        state_path=tmp_path / "state.json",
        head_sha="deadbeefcafe",
        codereview_findings=[],
        review_proof_root=tmp_path / "proof",  # a real PosixPath
        review_base="base000",
        config={"review": {"expects_copilot": False}},
        pr_url="https://github.com/o/r/pull/1",
    )
    # The exact live failure guarded: json.dumps of the built payload must not raise.
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded == payload

    assert isinstance(payload["review_proof_root"], str)
    assert isinstance(payload["state_path"], str)


def test_build_run_round_stdin_required_keys_and_omissions(tmp_path):
    payload = converge.build_run_round_stdin(
        state_path=str(tmp_path / "state.json"),
        head_sha="deadbeefcafe",
        codereview_findings=[],
        review_proof_root=str(tmp_path / "proof"),
        review_base="base000",
        config={"review": {"expects_copilot": False}},
        pr_url="https://github.com/o/r/pull/1",
    )
    for key in (
        "state_path", "head_sha", "codereview_findings", "reviewed",
        "unresolved_actionable", "ci_rollup", "config", "review_proof_root",
        "review_base", "pr_url",
    ):
        assert key in payload, key
    # decisions_path is OMITTED entirely (its readiness write dirties the tree).
    assert "decisions_path" not in payload
    assert payload["unresolved_actionable"] == 0
    assert payload["ci_rollup"] == []
    # reviewed null is OK on expects_copilot=false.
    assert payload["reviewed"] is None
    assert payload["codereview_findings"] == []


def test_raw_posixpath_payload_would_raise_regression(tmp_path):
    """Guards the exact live failure: a raw PosixPath on the stdin JSON raises."""
    bad = {"review_proof_root": tmp_path / "proof"}
    raised = False
    try:
        json.dumps(bad)
    except TypeError:
        raised = True
    assert raised, "expected TypeError: PosixPath is not JSON serializable"


# ============================================================
# Task 1.2 — label-count parse → list[tuple]; digest carries full head SHA
# ============================================================


_FULL_HEAD = "0123456789abcdef0123456789abcdef01234567"


def _nondegraded_meta(head=_FULL_HEAD) -> dict:
    return {
        "base": "base0000000", "head": head, "files_changed": 3,
        "insertions": 5, "deletions": 1, "degraded": False, "reason": None,
    }


def test_parse_label_counts_returns_list_of_tuples():
    parsed = converge.parse_label_counts(["correctness:0", "edge:2"])
    assert parsed == [("correctness", 0), ("edge", 2)]
    assert isinstance(parsed, list)
    for item in parsed:
        assert isinstance(item, tuple)
        label, count = item
        assert isinstance(label, str)
        assert isinstance(count, int)


def test_parse_label_counts_empty_and_none():
    assert converge.parse_label_counts([]) == []
    assert converge.parse_label_counts(None) == []


def test_digest_carries_full_head_and_verbatim_angles_fragment():
    label_counts = converge.parse_label_counts(["correctness:0", "edge:2"])
    digest = review_proof.format_proof_digest(_nondegraded_meta(), label_counts)
    # FULL head SHA (a 7-hex prefix fails closed at the gate).
    assert f"head `{_FULL_HEAD}`" in digest
    # verbatim label:count fragment, tuple order preserved.
    assert "angles [correctness:0, edge:2]" in digest


def test_parse_label_counts_rejects_malformed():
    for bad in ["nocolon", "edge:notint", "edge:", ":3"]:
        raised = False
        try:
            converge.parse_label_counts([bad])
        except ValueError:
            raised = True
        assert raised, f"expected ValueError for {bad!r}"


def test_label_counts_json_round_trip_reconstructs_tuples():
    counts = converge.parse_label_counts(["correctness:0", "edge:2"])
    # tuples do not survive a raw JSON round-trip (become lists) — the helper
    # serializes as lists and reconstructs equal tuples on read.
    encoded = json.dumps(converge.label_counts_to_json(counts))
    restored = converge.label_counts_from_json(json.loads(encoded))
    assert restored == counts
    for item in restored:
        assert isinstance(item, tuple)


def test_coerce_label_counts_normalizes_dict():
    """A dict of counts is normalized to a list of tuples (never passed raw to
    format_proof_digest, which unpacks (label, count) pairs)."""
    normalized = converge.label_counts_from_json({"correctness": 0, "edge": 2})
    assert isinstance(normalized, list)
    assert ("correctness", 0) in normalized
    assert ("edge", 2) in normalized
    for item in normalized:
        assert isinstance(item, tuple)
