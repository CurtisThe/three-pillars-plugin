"""Tests for html_briefing/svg.py — inline SVG visuals.

Covers Task 1.3 of promote-html-briefing plan:
  (a) each helper returns a well-formed <svg>…</svg> (ElementTree parseable)
  (b) wave_topology_svg: one node per seed, edges for serial pairs
  (c) collision_matrix_svg: cell per seed-pair, colliding pairs distinct
  (d) progress_bar_svg: fill width proportional to done/total
  (e) no external references (assert_offline)
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from briefing import assert_offline
from svg import collision_matrix_svg, progress_bar_svg, wave_topology_svg


# ---------------------------------------------------------------------------
# Wave topology
# ---------------------------------------------------------------------------

def _wave_model(seeds, waves, collisions=None, done=0, total=None):
    return SimpleNamespace(
        seeds=seeds,
        waves=waves,
        collisions=collisions or [],
        done=done,
        total=total if total is not None else len(seeds),
    )


class TestWaveTopologySvg:
    def _model(self):
        # Two waves: first has A/B in parallel, second has C serial after
        return _wave_model(
            seeds=["A", "B", "C"],
            waves=[["A", "B"], ["C"]],
        )

    def test_returns_svg_element(self):
        svg = wave_topology_svg(self._model())
        assert svg.strip().startswith("<svg")

    def test_parseable_by_element_tree(self):
        svg = wave_topology_svg(self._model())
        # Must not raise — svg is our own generated output, not untrusted input
        root = ET.fromstring(svg)  # nosec B314
        assert root.tag in ("svg", "{http://www.w3.org/2000/svg}svg")

    def test_contains_one_node_per_seed(self):
        svg = wave_topology_svg(self._model())
        # Each seed name should appear in the SVG text
        for name in ["A", "B", "C"]:
            assert name in svg

    def test_contains_serial_edges(self):
        svg = wave_topology_svg(self._model())
        # Serial connection implies <line> elements between waves
        assert "<line" in svg

    def test_no_external_resource(self):
        svg = wave_topology_svg(self._model())
        assert_offline(svg)

    def test_empty_seeds_returns_valid_svg(self):
        model = _wave_model(seeds=[], waves=[])
        svg = wave_topology_svg(model)
        ET.fromstring(svg)  # nosec B314

    def test_single_wave_no_edges(self):
        model = _wave_model(seeds=["X", "Y"], waves=[["X", "Y"]])
        svg = wave_topology_svg(model)
        # No serial edges expected (all in same wave)
        assert "<line" not in svg


class TestCollisionMatrixSvg:
    def _model_with_collision(self):
        return _wave_model(
            seeds=["alpha", "beta", "gamma"],
            waves=[["alpha"], ["beta", "gamma"]],
            collisions=[frozenset(["alpha", "beta"])],
        )

    def test_returns_svg_element(self):
        svg = collision_matrix_svg(self._model_with_collision())
        assert svg.strip().startswith("<svg")

    def test_parseable_by_element_tree(self):
        svg = collision_matrix_svg(self._model_with_collision())
        root = ET.fromstring(svg)  # nosec B314
        assert root.tag in ("svg", "{http://www.w3.org/2000/svg}svg")

    def test_seed_labels_appear(self):
        svg = collision_matrix_svg(self._model_with_collision())
        assert "alpha" in svg
        assert "beta" in svg

    def test_collision_pairs_marked_distinctly(self):
        svg = collision_matrix_svg(self._model_with_collision())
        # Collision cells use a different fill colour
        assert "#e84e4e" in svg   # collision colour from _PALETTE

    def test_no_collision_cells_use_green(self):
        svg = collision_matrix_svg(self._model_with_collision())
        assert "#d4edda" in svg   # no_collision colour

    def test_no_external_resource(self):
        svg = collision_matrix_svg(self._model_with_collision())
        assert_offline(svg)

    def test_empty_seeds_returns_valid_svg(self):
        model = _wave_model(seeds=[], waves=[])
        svg = collision_matrix_svg(model)
        ET.fromstring(svg)  # nosec B314


class TestProgressBarSvg:
    def test_returns_svg_element(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        assert svg.strip().startswith("<svg")

    def test_parseable_by_element_tree(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        ET.fromstring(svg)  # nosec B314

    def test_shows_done_and_total(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        assert "1/2" in svg or ("1" in svg and "2" in svg)

    def test_fill_width_proportional_half(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        # 1/2 => fill_w = 200 (400 * 0.5)
        assert 'width="200"' in svg

    def test_fill_width_proportional_zero(self):
        model = _wave_model(seeds=["A"], waves=[["A"]], done=0, total=4)
        svg = progress_bar_svg(model)
        # 0/4 => fill_w = 0, no fill rect
        assert '0%' in svg or "0/4" in svg

    def test_fill_width_proportional_full(self):
        model = _wave_model(seeds=["A"], waves=[["A"]], done=3, total=3)
        svg = progress_bar_svg(model)
        assert '400"' in svg or "100%" in svg

    def test_no_external_resource(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        assert_offline(svg)

    def test_aria_label_present(self):
        model = _wave_model(seeds=["A", "B"], waves=[["A"], ["B"]], done=1, total=2)
        svg = progress_bar_svg(model)
        assert "aria-label" in svg
