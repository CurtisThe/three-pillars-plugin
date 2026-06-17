"""Tests for orchestrator_identity.py — same_actor and display_label predicates.

Run with: python -m pytest skills/_shared/test_orchestrator_identity.py -q
"""

import pytest

from orchestrator_identity import same_actor, display_label


# --------------------------------------------------------------------------- #
# same_actor cases
# --------------------------------------------------------------------------- #


def test_same_actor_bare_prefixed_same_email():
    """Prefixed owner matches bare owner with the same email."""
    assert same_actor("orchestrator:e@x", "e@x") is True


def test_same_actor_reverse():
    """Bare owner matches prefixed owner — symmetric."""
    assert same_actor("e@x", "orchestrator:e@x") is True


def test_same_actor_case_normalize():
    """Case variants of the same email are the same actor."""
    assert same_actor("Curtis.Theoret@gmail.com", "curtis.theoret@gmail.com") is True


def test_same_actor_prefix_collapse_both_sides():
    """Two prefixed owners with the same email are the same actor."""
    assert same_actor("orchestrator:e@x", "orchestrator:e@x") is True


def test_same_actor_distinct_emails_bare():
    """Two distinct bare emails are NOT the same actor."""
    assert same_actor("a@x", "b@x") is False


def test_same_actor_distinct_emails_prefixed():
    """Prefixed owner vs distinct bare email is NOT the same actor."""
    assert same_actor("orchestrator:a@x", "b@x") is False


def test_same_actor_none_both():
    """Two None owners are NOT the same actor (released-lock guard)."""
    assert same_actor(None, None) is False


def test_same_actor_none_one_side():
    """None on one side is NOT the same actor as a real email."""
    assert same_actor(None, "e@x") is False


def test_same_actor_empty_both():
    """Two empty strings are NOT the same actor."""
    assert same_actor("", "") is False


# --------------------------------------------------------------------------- #
# display_label cases
# --------------------------------------------------------------------------- #


def test_display_label_marker():
    """Prefixed owner renders as '<email> (orchestrator)'."""
    assert display_label("orchestrator:e@x") == "e@x (orchestrator)"


def test_display_label_bare():
    """Bare owner renders verbatim with no marker."""
    assert display_label("e@x") == "e@x"


def test_display_label_released():
    """None owner (released/clean) renders as '-'."""
    assert display_label(None) == "-"


def test_display_label_case_preserved():
    """Prefixed owner preserves the original email case in the label."""
    assert (
        display_label("orchestrator:Curtis.Theoret@gmail.com")
        == "Curtis.Theoret@gmail.com (orchestrator)"
    )


# --------------------------------------------------------------------------- #
# Non-str owner robustness (Fix 3)
# --------------------------------------------------------------------------- #


def test_same_actor_nonstr_left_is_false():
    """Non-str owner on the left is NOT the same actor as any email — fail-closed."""
    assert same_actor(42, "x@y.com") is False


def test_same_actor_nonstr_right_is_false():
    """Non-str owner on the right is NOT the same actor as any email — fail-closed."""
    assert same_actor("x@y.com", 42) is False


def test_same_actor_nonstr_both_is_false():
    """Two non-str owners are NOT the same actor — no spurious adoption."""
    assert same_actor(42, 42) is False


def test_display_label_nonstr_does_not_raise():
    """Non-str, non-None owner is rendered via str() without raising AttributeError."""
    result = display_label(42)
    assert result == "42"


def test_display_label_nonstr_list_does_not_raise():
    """List owner is rendered via str() without raising."""
    result = display_label(["a@b.com"])
    assert isinstance(result, str)
    assert "AttributeError" not in result
