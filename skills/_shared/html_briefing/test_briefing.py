"""Tests for html_briefing/briefing.py — public entry build_briefing_html.

Covers Task 1.4 of promote-html-briefing plan:
  (a) starts <!DOCTYPE html>, contains <style> and <script> (inline — no external)
  (b) embeds per-seed cards and SVG visuals
  (c) lockstep — embedded JS map equals Python serializer letter map;
      golden data-attribute equals serialize_answers(default_model)
  (d) assert_offline passes on the full document
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from briefing import assert_offline, build_briefing_html
from renderer import SeedCard
from serializer import ConfirmModel, Question, serialize_answers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_wave_model():
    return SimpleNamespace(
        seeds=["design-a", "design-b"],
        waves=[["design-a"], ["design-b"]],
        collisions=[frozenset(["design-a", "design-b"])],
        done=1,
        total=2,
    )


def _make_confirm_model():
    return ConfirmModel(questions=[
        Question(
            number=1, kind="single",
            options=[("a", "Option A"), ("b", "Option B")],
            default="a", chosen="a",
        ),
        Question(
            number=2, kind="multi",
            options=[("a", "Check A"), ("b", "Check B")],
            default=["a"], chosen=["a"],
        ),
        Question(
            number=3, kind="free",
            options=[],
            default="my default", chosen="my default",
        ),
    ])


def _make_seeds():
    return [
        SeedCard(
            name="design-a",
            brief="First seed.",
            weight_class="light",
            badges=["chokepoint"],
            branch="tp/design-a",
            sha="aaa1111",
            probe_banner=None,
            premise_refresh_banner=None,
        ),
        SeedCard(
            name="design-b",
            brief="Second seed.",
            weight_class="full",
            badges=[],
            branch="tp/design-b",
            sha="bbb2222",
            probe_banner="Probe active.",
            premise_refresh_banner=None,
        ),
    ]


def _make_model():
    confirm = _make_confirm_model()
    return SimpleNamespace(
        seeds=_make_seeds(),
        questions=confirm,
        wave_model=_make_wave_model(),
    )


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_doctype():
    html = build_briefing_html(_make_model())
    assert html.startswith("<!DOCTYPE html>")


def test_has_inline_style():
    html = build_briefing_html(_make_model())
    assert "<style>" in html


def test_has_inline_script():
    html = build_briefing_html(_make_model())
    assert "<script>" in html


def test_no_external_css_or_js():
    html = build_briefing_html(_make_model())
    # No link[rel=stylesheet] with external href, no <script src=...>
    assert 'rel="stylesheet"' not in html
    assert '<script src=' not in html


# ---------------------------------------------------------------------------
# Content tests
# ---------------------------------------------------------------------------

def test_embeds_seed_cards():
    html = build_briefing_html(_make_model())
    assert "design-a" in html
    assert "design-b" in html
    assert "First seed." in html
    assert "Second seed." in html


def test_embeds_svg_visuals():
    html = build_briefing_html(_make_model())
    assert "<svg" in html


def test_embeds_form_controls():
    html = build_briefing_html(_make_model())
    assert 'type="radio"' in html
    assert 'type="checkbox"' in html
    assert 'type="text"' in html


def test_has_assemble_button():
    html = build_briefing_html(_make_model())
    assert "assemble-btn" in html or "Assemble answers" in html


# ---------------------------------------------------------------------------
# Lockstep: embedded JS map == Python serializer letter map
# ---------------------------------------------------------------------------

def test_embedded_q_map_equals_python_letter_map():
    """The data-q-map JSON in the button must match Python's question letters."""
    model = _make_model()
    html = build_briefing_html(model)

    # Extract data-q-map value from the HTML
    import re
    m = re.search(r"data-q-map='([^']*)'", html)
    assert m, "data-q-map attribute not found in HTML"
    embedded_map = json.loads(m.group(1))

    # Build expected map from the Python model
    expected = {}
    for q in model.questions.questions:
        if q.kind != "free":
            expected[str(q.number)] = [opt[0] for opt in q.options]
        else:
            expected[str(q.number)] = []

    assert embedded_map == expected


def test_golden_defaults_attribute_equals_python_serialize():
    """data-golden attribute must equal serialize_answers(default_model)."""
    import html as html_mod
    model = _make_model()
    doc = build_briefing_html(model)

    # Build default model (all chosen == default)
    import copy
    qs = []
    for q in model.questions.questions:
        q2 = copy.copy(q)
        if q.kind == "multi":
            q2.chosen = list(q.default)
        else:
            q2.chosen = q.default
        qs.append(q2)
    default_cm = ConfirmModel(questions=qs)
    expected_golden = serialize_answers(default_cm)

    # Extract data-golden from HTML (it's HTML-escaped)
    import re
    m = re.search(r'data-golden="([^"]*)"', doc)
    assert m, "data-golden attribute not found in HTML"
    actual_golden = html_mod.unescape(m.group(1))
    assert actual_golden == expected_golden


# ---------------------------------------------------------------------------
# Offline-first
# ---------------------------------------------------------------------------

def test_assert_offline_passes():
    html = build_briefing_html(_make_model())
    assert_offline(html)


# ---------------------------------------------------------------------------
# Fix 3: assert_offline negative tests (known-bad inputs must be detected)
# ---------------------------------------------------------------------------

def test_offline_detects_http_href():
    """href with http:// URL is an external reference."""
    import pytest
    with pytest.raises(AssertionError):
        assert_offline('<a href="http://evil.example/x">')


def test_offline_detects_protocol_relative_script():
    """script src with protocol-relative URL is external."""
    import pytest
    with pytest.raises(AssertionError):
        assert_offline('<script src="//cdn.example/x"></script>')


def test_offline_detects_css_import():
    """@import in a style block is an external reference."""
    import pytest
    with pytest.raises(AssertionError):
        assert_offline('<style>@import url(http://evil.example/x);</style>')


def test_offline_detects_fetch():
    """Inline JS fetch() call is an external reference."""
    import pytest
    with pytest.raises(AssertionError):
        assert_offline("fetch('http://evil.example/x')")


def test_offline_detects_non_w3c_xmlns():
    """xmlns with non-w3.org host must NOT be stripped and must be caught."""
    import pytest
    with pytest.raises(AssertionError):
        assert_offline('<svg xmlns="https://attacker.example/x">')


def test_offline_positive_full_document():
    """A real build_briefing_html document passes assert_offline."""
    html = build_briefing_html(_make_model())
    assert_offline(html)  # must not raise


# ---------------------------------------------------------------------------
# pytest collection: flat imports, no __init__.py
# ---------------------------------------------------------------------------

def test_flat_import_works():
    """Verify the package is importable with flat sys.path (no __init__.py)."""
    # If this file ran at all, flat import succeeded.
    from briefing import build_briefing_html as _bh  # noqa: F401
    assert _bh is not None
