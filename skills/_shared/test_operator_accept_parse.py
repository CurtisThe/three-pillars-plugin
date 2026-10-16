"""test_operator_accept_parse.py — the `tp-accept: <full-40-hex-sha> <reason>` line (E3).

The accept token is ONLY parseable from a full 40-hex head sha: a 7-char prefix,
a truncated sha, a missing reason, a missing sha or prose slop all fold to None.
The full sha is what binds the accept to a specific head (Behavior 16) — a prefix
would let an accept written for one head be read onto another.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import operator_accept  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


def test_accept_re_is_the_module_constant():
    assert operator_accept.ACCEPT_RE.pattern == (
        r"^tp-accept:\s+([0-9a-fA-F]{40})\s+(\S.*)$")


def test_full_sha_with_reason_parses():
    assert operator_accept.parse_accept(f"tp-accept: {SHA} ship it") == (SHA, "ship it")


def test_full_sha_is_case_insensitive_on_hex():
    upper = SHA.upper()
    assert operator_accept.parse_accept(f"tp-accept: {upper} ok") == (upper, "ok")


def test_reason_keeps_trailing_words_and_inner_spaces():
    body = f"tp-accept: {SHA} gate lows are fine, ship"
    assert operator_accept.parse_accept(body) == (SHA, "gate lows are fine, ship")


def test_accept_line_inside_a_larger_body():
    body = f"review notes here\n\ntp-accept: {SHA} yes\n\nmore prose"
    assert operator_accept.parse_accept(body) == (SHA, "yes")


def test_seven_char_prefix_is_not_an_accept():
    assert operator_accept.parse_accept("tp-accept: 0123456 ship it") is None


def test_truncated_sha_is_not_an_accept():
    assert operator_accept.parse_accept(f"tp-accept: {SHA[:39]} why") is None
    assert operator_accept.parse_accept(f"tp-accept: {SHA}0 why") is None


def test_non_hex_sha_is_not_an_accept():
    assert operator_accept.parse_accept("tp-accept: " + "g" * 40 + " why") is None


def test_sha_with_no_reason_is_not_an_accept():
    assert operator_accept.parse_accept(f"tp-accept: {SHA}") is None
    assert operator_accept.parse_accept(f"tp-accept: {SHA} ") is None


def test_missing_sha_is_not_an_accept():
    assert operator_accept.parse_accept("tp-accept: ship it") is None


def test_indented_line_is_not_an_accept():
    assert operator_accept.parse_accept(f"  tp-accept: {SHA} why") is None


def test_empty_and_none_bodies():
    assert operator_accept.parse_accept("") is None
    assert operator_accept.parse_accept(None) is None
    assert operator_accept.parse_accept(42) is None
