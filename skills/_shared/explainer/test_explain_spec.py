"""test_explain_spec.py — tests for explain_spec.sanitize_spec + _strip_external.

Tasks 3.2 and 3.3:
  - Grammar validation: kind ∈ {flow, decision, state}; bad kind → None.
  - Hostile labels are stripped: <svg>, http(s):, url(), @import,
    protocol-relative //host, data:text/html, xlink, <script>, mixed-case,
    nested payloads.
  - data: allowlist: base64 image/audio/video survive; text/html,
    application/*, non-base64 stripped.
  - Node/edge counts capped; dangling edges dropped.
  - Output passes briefing.assert_offline.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

import explain_offline as briefing


# ---------------------------------------------------------------------------
# Task 3.2: grammar + hostile label sanitization
# ---------------------------------------------------------------------------

class TestSanitizeSpecGrammar:
    """Valid specs normalize; invalid kind → None."""

    def test_flow_kind_normalizes(self):
        from explain_spec import sanitize_spec
        spec = {
            "kind": "flow",
            "nodes": ["a", "b", "c"],
            "edges": [["a", "b"], ["b", "c"]],
            "labels": {"a": "Start", "b": "Middle", "c": "End"},
        }
        result = sanitize_spec(spec)
        assert result is not None
        assert result["kind"] == "flow"
        assert "nodes" in result
        assert "edges" in result
        assert "labels" in result

    def test_decision_kind_normalizes(self):
        from explain_spec import sanitize_spec
        spec = {
            "kind": "decision",
            "nodes": ["root", "yes", "no"],
            "edges": [["root", "yes"], ["root", "no"]],
            "labels": {"root": "Merge?", "yes": "Approve", "no": "Reject"},
        }
        result = sanitize_spec(spec)
        assert result is not None
        assert result["kind"] == "decision"

    def test_state_kind_normalizes(self):
        from explain_spec import sanitize_spec
        spec = {
            "kind": "state",
            "nodes": ["idle", "running", "done"],
            "edges": [["idle", "running"], ["running", "done"]],
            "labels": {"idle": "Idle", "running": "Running", "done": "Done"},
        }
        result = sanitize_spec(spec)
        assert result is not None
        assert result["kind"] == "state"

    def test_bad_kind_returns_none(self):
        from explain_spec import sanitize_spec
        spec = {"kind": "graph", "nodes": ["a"], "edges": [], "labels": {}}
        assert sanitize_spec(spec) is None

    def test_missing_kind_returns_none(self):
        from explain_spec import sanitize_spec
        spec = {"nodes": ["a"], "edges": [], "labels": {}}
        assert sanitize_spec(spec) is None

    def test_none_spec_returns_none(self):
        from explain_spec import sanitize_spec
        assert sanitize_spec(None) is None

    def test_non_dict_spec_returns_none(self):
        from explain_spec import sanitize_spec
        assert sanitize_spec("bad") is None
        assert sanitize_spec(42) is None
        assert sanitize_spec([]) is None

    def test_empty_spec_returns_none(self):
        from explain_spec import sanitize_spec
        assert sanitize_spec({}) is None

    def test_nodes_coerced_to_list(self):
        from explain_spec import sanitize_spec
        spec = {"kind": "flow", "nodes": "a,b", "edges": [], "labels": {}}
        # If nodes is not a list, should either coerce or return None
        result = sanitize_spec(spec)
        # If it returns something, nodes must be a list
        if result is not None:
            assert isinstance(result["nodes"], list)

    def test_edges_dangling_nodes_dropped(self):
        """Edges referencing unknown nodes are dropped."""
        from explain_spec import sanitize_spec
        spec = {
            "kind": "flow",
            "nodes": ["a", "b"],
            "edges": [["a", "b"], ["a", "c"], ["x", "b"]],  # c, x unknown
            "labels": {"a": "A", "b": "B"},
        }
        result = sanitize_spec(spec)
        assert result is not None
        # Only ["a", "b"] edge should survive
        for edge in result["edges"]:
            assert edge[0] in result["nodes"]
            assert edge[1] in result["nodes"]

    def test_node_count_capped(self):
        """Node list is capped at a max."""
        from explain_spec import sanitize_spec, MAX_NODES
        big_nodes = [f"n{i}" for i in range(MAX_NODES + 20)]
        spec = {
            "kind": "flow",
            "nodes": big_nodes,
            "edges": [["n0", "n1"]],
            "labels": {},
        }
        result = sanitize_spec(spec)
        if result is not None:
            assert len(result["nodes"]) <= MAX_NODES

    def test_edge_count_capped(self):
        """Edge list is capped at a max."""
        from explain_spec import sanitize_spec, MAX_EDGES
        nodes = ["a", "b"]
        big_edges = [["a", "b"]] * (MAX_EDGES + 20)
        spec = {
            "kind": "flow",
            "nodes": nodes,
            "edges": big_edges,
            "labels": {"a": "A", "b": "B"},
        }
        result = sanitize_spec(spec)
        if result is not None:
            assert len(result["edges"]) <= MAX_EDGES


class TestSanitizeSpecHostileLabels:
    """Hostile labels are stripped before reaching the SVG renderer."""

    def _sanitize_with_label(self, label_text):
        from explain_spec import sanitize_spec
        spec = {
            "kind": "flow",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": label_text},
        }
        return sanitize_spec(spec)

    def test_svg_tag_in_label_stripped(self):
        from explain_spec import sanitize_spec
        result = self._sanitize_with_label("<svg onload=alert(1)>")
        assert result is not None
        label = result["labels"].get("a", "")
        assert "<svg" not in label

    def test_script_tag_in_label_stripped(self):
        result = self._sanitize_with_label("<script>evil()</script>")
        assert result is not None
        label = result["labels"].get("a", "")
        assert "<script" not in label.lower()

    def test_http_url_in_label_stripped(self):
        result = self._sanitize_with_label("go to http://evil.com")
        assert result is not None
        label = result["labels"].get("a", "")
        # http: should be stripped or result passes assert_offline
        briefing.assert_offline(f'<span>{label}</span>')

    def test_https_url_in_label_stripped(self):
        result = self._sanitize_with_label("see https://cdn.evil.com/script.js")
        assert result is not None
        label = result["labels"].get("a", "")
        briefing.assert_offline(f'<span>{label}</span>')

    def test_url_css_function_in_label_stripped(self):
        result = self._sanitize_with_label("background: url(http://evil.com/img.png)")
        assert result is not None
        label = result["labels"].get("a", "")
        # url( with http should be stripped
        assert "url(" not in label.lower() or "http" not in label.lower()
        briefing.assert_offline(f'<span>{label}</span>')

    def test_protocol_relative_in_label_stripped(self):
        result = self._sanitize_with_label("ref //cdn.example.com/evil.js")
        assert result is not None
        label = result["labels"].get("a", "")
        briefing.assert_offline(f'<span>{label}</span>')

    def test_data_text_html_in_label_stripped(self):
        result = self._sanitize_with_label("data:text/html,<script>alert(1)</script>")
        assert result is not None
        label = result["labels"].get("a", "")
        # data:text/html should be stripped
        assert "data:text" not in label.lower()

    def test_xlink_href_in_label_stripped(self):
        result = self._sanitize_with_label('<use xlink:href="#evil"/>')
        assert result is not None
        label = result["labels"].get("a", "")
        assert "xlink" not in label.lower()

    def test_import_in_label_stripped(self):
        result = self._sanitize_with_label("@import url(evil.css)")
        assert result is not None
        label = result["labels"].get("a", "")
        assert "@import" not in label.lower()

    def test_mixed_case_https_in_label_stripped(self):
        """Mixed-case scheme like HtTpS: must also be stripped."""
        result = self._sanitize_with_label("HtTpS://evil.com/script.js")
        assert result is not None
        label = result["labels"].get("a", "")
        briefing.assert_offline(f'<span>{label}</span>')

    def test_encoded_url_in_label_stripped(self):
        """URL-encoded or embedded attacks are stripped."""
        result = self._sanitize_with_label("http&#58;//evil.com")
        assert result is not None
        # After HTML escape, still safe
        label = result["labels"].get("a", "")
        briefing.assert_offline(f'<span>{label}</span>')


# ---------------------------------------------------------------------------
# Task 3.3: data: allowlist in _strip_external
# ---------------------------------------------------------------------------

class TestDataURIAllowlist:
    """Only base64 image/audio/video data: URIs survive _strip_external."""

    def test_data_image_png_base64_survives(self):
        from explain_spec import _strip_external
        uri = "data:image/png;base64,iVBORw0KGgo="
        result = _strip_external(uri)
        assert "data:image/png;base64," in result

    def test_data_image_jpeg_base64_survives(self):
        from explain_spec import _strip_external
        uri = "data:image/jpeg;base64,/9j/4AAQ="
        result = _strip_external(uri)
        assert "data:image/jpeg;base64," in result

    def test_data_audio_base64_survives(self):
        from explain_spec import _strip_external
        uri = "data:audio/mpeg;base64,SUQzBAAA"
        result = _strip_external(uri)
        assert "data:audio/mpeg;base64," in result

    def test_data_video_base64_survives(self):
        from explain_spec import _strip_external
        uri = "data:video/mp4;base64,AAAAIGZ0"
        result = _strip_external(uri)
        assert "data:video/mp4;base64," in result

    def test_data_text_html_stripped(self):
        from explain_spec import _strip_external
        uri = "data:text/html,<script>alert(1)</script>"
        result = _strip_external(uri)
        assert "data:text" not in result.lower()

    def test_data_application_javascript_stripped(self):
        from explain_spec import _strip_external
        uri = "data:application/javascript,alert(1)"
        result = _strip_external(uri)
        assert "data:application" not in result.lower()

    def test_data_text_plain_stripped(self):
        from explain_spec import _strip_external
        uri = "data:text/plain,hello world"
        result = _strip_external(uri)
        assert "data:text" not in result.lower()

    def test_data_image_non_base64_stripped(self):
        """Non-base64 data: URI (URL-encoded) must be stripped."""
        from explain_spec import _strip_external
        uri = "data:image/svg+xml,%3Csvg%3E%3C/svg%3E"
        result = _strip_external(uri)
        # data:image without base64 encoding should be stripped
        assert "data:image/svg" not in result.lower()

    def test_data_application_json_stripped(self):
        from explain_spec import _strip_external
        uri = "data:application/json,{}"
        result = _strip_external(uri)
        assert "data:application" not in result.lower()

    def test_strip_external_plain_text_unchanged(self):
        """Safe plain text passes through without modification."""
        from explain_spec import _strip_external
        text = "simple label text"
        result = _strip_external(text)
        # No external refs to strip
        assert "simple" in result

    def test_strip_external_output_passes_assert_offline(self):
        """Any text processed by _strip_external passes assert_offline."""
        from explain_spec import _strip_external
        hostile_inputs = [
            "http://evil.com/script.js",
            "https://cdn.example.com",
            "url(http://evil.com/bg.png)",
            "//protocol-relative.com",
            "data:text/html,<script>",
            "@import url(evil.css)",
            '<svg xmlns="http://www.w3.org/2000/svg">',
            "xlink:href='evil'",
        ]
        for hostile in hostile_inputs:
            result = _strip_external(hostile)
            # Wrap in basic HTML context to test with assert_offline
            try:
                briefing.assert_offline(f"<p>{result}</p>")
            except AssertionError as e:
                pytest.fail(
                    f"_strip_external({hostile!r}) still fails assert_offline: "
                    f"result={result!r}, error={e}"
                )


# ---------------------------------------------------------------------------
# Finding 2: _strip_external adversarial reconstitution (anti-single-pass)
# These tests FAIL on the unpatched code — they prove the bypass is real.
# ---------------------------------------------------------------------------

class TestStripExternalFixedPoint:
    """_strip_external must reach a fixed point: reconstituted schemes must
    not survive into the SVG text context and trip assert_offline."""

    def _assert_passes_offline(self, label: str) -> None:
        from explain_spec import _strip_external
        result = _strip_external(label)
        try:
            briefing.assert_offline(f"<text>{result}</text>")
        except AssertionError as e:
            pytest.fail(
                f"_strip_external({label!r}) reconstituted a forbidden pattern: "
                f"result={result!r}, error={e}"
            )

    def test_reconstitution_htHTTP_tp(self):
        """htHTTP:tp:/ → strip HTTP: → http:/ must be re-stripped."""
        self._assert_passes_offline("htHTTP:tp:/X/")

    def test_reconstitution_h_slashslash_ttp(self):
        """h//ttp:s://evil → strip // → http:s:evil → http: must be re-stripped."""
        self._assert_passes_offline("h//ttp:s://evil")

    def test_reconstitution_nested_https(self):
        """htHTTPS:tps://x → single pass leaves https:, fixed-point must catch it."""
        self._assert_passes_offline("htHTTPS:tps://evil.example")

    def test_reconstitution_via_spec_svg(self):
        """Reconstitution attack via a label fed to spec_svg passes assert_offline."""
        from explain_svg import spec_svg
        spec = {
            "kind": "flow",
            "nodes": ["htHTTP:tp:/X/"],
            "edges": [],
            "labels": {},
        }
        result = spec_svg(spec)
        try:
            briefing.assert_offline(result)
        except AssertionError as e:
            pytest.fail(
                f"spec_svg with reconstitution label failed assert_offline: {e}"
            )


# ---------------------------------------------------------------------------
# Pathological cap-bypass inputs — must FAIL on cap-only strip, PASS after fix
# ---------------------------------------------------------------------------

class TestPathologicalCapBypass:
    """Long inputs that reconstitute a forbidden token on EVERY strip iteration,
    exhausting _MAX_STRIP_ROUNDS=20 and leaving residual http: tokens.

    These tests FAIL on the current capped-strip-only code and MUST pass after
    the unconditional token-neutralization fix.
    """

    def _spec(self, label: str) -> dict:
        return {
            "kind": "flow",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": label},
        }

    def _assert_spec_svg_offline(self, label: str, name: str) -> None:
        from explain_svg import spec_svg
        result = spec_svg(self._spec(label))
        try:
            briefing.assert_offline(result)
        except AssertionError as e:
            pytest.fail(
                f"spec_svg({name!r}) leaked past assert_offline: {e}\n"
                f"SVG tail: {result[-120:]!r}"
            )

    def test_pathological_http_cap_bypass(self):
        """'h'*25+'ttp:'*25 exhausts strip rounds, reconstitutes http: tokens."""
        self._assert_spec_svg_offline("h" * 25 + "ttp:" * 25, "h*25+ttp:*25")

    def test_pathological_https_cap_bypass(self):
        """'h'*30+'ttps:'*30 exhausts strip rounds, reconstitutes https: tokens."""
        self._assert_spec_svg_offline("h" * 30 + "ttps:" * 30, "h*30+ttps:*30")

    def test_pathological_url_func_cap_bypass(self):
        """('ur'+'l(')*30 — url( reconstitution attempt."""
        self._assert_spec_svg_offline(("ur" + "l(") * 30, "url(*30")

    # The full-document checks (rendered through live_render.build_live_html) live
    # in html_briefing/test_explainer_path_shim.py: live_render is html_briefing's,
    # and the core explainer package never imports html_briefing.
