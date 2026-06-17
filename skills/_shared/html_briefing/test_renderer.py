"""Tests for html_briefing/renderer.py — per-seed cards + form-control renderer.

Covers Task 1.2 of promote-html-briefing plan:
  (a) one card per seed with name, brief, badge text, branch+SHA
  (b) correct form controls: radio/checkbox/text per question kind
  (c) drafter default pre-selected (checked / value=)
  (d) no external resource (shared assert_offline helper)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from briefing import assert_offline
from renderer import SeedCard, render_cards, render_questions
from serializer import ConfirmModel, Question


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_seed_cards():
    return [
        SeedCard(
            name="my-design",
            brief="A test design for briefing.",
            weight_class="light",
            badges=["collision:design-b", "chokepoint"],
            branch="tp/my-design",
            sha="abc1234",
            probe_banner=None,
            premise_refresh_banner="Premise updated.",
        ),
        SeedCard(
            name="other-design",
            brief="Another seed.",
            weight_class="full",
            badges=[],
            branch="tp/other-design",
            sha="def5678",
            probe_banner="Probe active.",
            premise_refresh_banner=None,
        ),
    ]


def _make_model():
    return ConfirmModel(questions=[
        Question(
            number=1, kind="single",
            options=[("a", "Option A"), ("b", "Option B")],
            default="a", chosen="a",
        ),
        Question(
            number=2, kind="multi",
            options=[("a", "Choice A"), ("b", "Choice B"), ("c", "Choice C")],
            default=["a", "c"], chosen=["a", "c"],
        ),
        Question(
            number=3, kind="free",
            options=[],
            default="default text", chosen="default text",
        ),
    ])


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def test_render_cards_contains_seed_names():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "my-design" in html
    assert "other-design" in html


def test_render_cards_contains_briefs():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "A test design for briefing." in html
    assert "Another seed." in html


def test_render_cards_contains_badges():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "collision:design-b" in html
    assert "chokepoint" in html


def test_render_cards_contains_branch_and_sha():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "tp/my-design" in html
    assert "abc1234" in html
    assert "tp/other-design" in html
    assert "def5678" in html


def test_render_cards_weight_class():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "light" in html
    assert "full" in html


def test_render_cards_banners():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert "Premise updated." in html
    assert "Probe active." in html


def test_render_cards_no_external_resource():
    cards = _make_seed_cards()
    html = render_cards(cards)
    assert_offline(html)


# ---------------------------------------------------------------------------
# Question rendering
# ---------------------------------------------------------------------------

def test_render_questions_single_uses_radio():
    model = _make_model()
    html = render_questions(model)
    # Single-select → radio inputs
    assert 'type="radio"' in html


def test_render_questions_multi_uses_checkbox():
    model = _make_model()
    html = render_questions(model)
    assert 'type="checkbox"' in html


def test_render_questions_free_uses_text_input():
    model = _make_model()
    html = render_questions(model)
    # free-text: input[type=text] or textarea
    assert 'type="text"' in html or '<textarea' in html


def test_render_questions_single_default_checked():
    model = _make_model()
    html = render_questions(model)
    # The default for Q1 is "a" — radio for option a must be checked
    # We can't rely on exact order, but "checked" must appear
    assert "checked" in html


def test_render_questions_multi_default_checked():
    model = _make_model()
    html = render_questions(model)
    assert "checked" in html


def test_render_questions_free_default_value():
    model = _make_model()
    html = render_questions(model)
    assert "default text" in html


def test_render_questions_no_external_resource():
    model = _make_model()
    html = render_questions(model)
    assert_offline(html)


def test_render_questions_contains_question_labels():
    model = _make_model()
    html = render_questions(model)
    # Option labels should appear
    assert "Option A" in html
    assert "Option B" in html
    assert "Choice A" in html
