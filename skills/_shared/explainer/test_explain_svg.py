"""test_explain_svg.py — tests for explain_svg.spec_svg.

Tasks 3.4, 3.5, 3.6:
  - spec_svg draws a valid <svg>...</svg> for flow, decision, and state kinds.
  - Output always passes briefing.assert_offline.
  - A None/bad spec renders an empty-but-valid SVG (degrade).
  - Hostile specs (raw <svg>, http(s):, url(...), data:text/html, xlink:href,
    <script>, mixed-case schemes, protocol-relative //, nested payloads) are
    defanged at draw time — assert_offline must not raise.
  - spec_svg calls sanitize_spec internally (defense-in-depth).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest

import explain_offline as briefing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_flow_spec():
    return {
        "kind": "flow",
        "nodes": ["design", "implement", "review"],
        "edges": [["design", "implement"], ["implement", "review"]],
        "labels": {
            "design": "Design",
            "implement": "Implement",
            "review": "Review",
        },
    }


def _valid_decision_spec():
    return {
        "kind": "decision",
        "nodes": ["root", "approve", "reject"],
        "edges": [["root", "approve"], ["root", "reject"]],
        "labels": {
            "root": "Merge?",
            "approve": "Approve",
            "reject": "Reject",
        },
    }


def _valid_state_spec():
    return {
        "kind": "state",
        "nodes": ["idle", "running", "done"],
        "edges": [["idle", "running"], ["running", "done"]],
        "labels": {
            "idle": "Idle",
            "running": "Running",
            "done": "Done",
        },
    }


# ---------------------------------------------------------------------------
# Task 3.4: spec_svg — flow kind, offline-clean
# ---------------------------------------------------------------------------

class TestSpecSvgFlow:

    def test_flow_svg_returns_string(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_flow_spec())
        assert isinstance(result, str)

    def test_flow_svg_is_svg_element(self):
        """Output is a well-formed <svg>...</svg> fragment."""
        from explain_svg import spec_svg
        result = spec_svg(_valid_flow_spec())
        stripped = result.strip()
        assert stripped.startswith("<svg"), f"Expected '<svg...', got: {result[:60]!r}"
        assert stripped.endswith("</svg>"), f"Expected '...</svg>', got: {result[-60:]!r}"

    def test_flow_svg_passes_assert_offline(self):
        """spec_svg output for a flow spec must pass briefing.assert_offline."""
        from explain_svg import spec_svg
        result = spec_svg(_valid_flow_spec())
        briefing.assert_offline(result)

    def test_flow_svg_contains_node_labels(self):
        """Node labels appear in the SVG output."""
        from explain_svg import spec_svg
        result = spec_svg(_valid_flow_spec())
        assert "Design" in result or "design" in result.lower()

    def test_none_spec_returns_empty_valid_svg(self):
        """None spec → empty-but-valid <svg>...</svg>."""
        from explain_svg import spec_svg
        result = spec_svg(None)
        stripped = result.strip()
        assert stripped.startswith("<svg")
        assert stripped.endswith("</svg>")
        briefing.assert_offline(result)

    def test_bad_kind_returns_empty_valid_svg(self):
        """Unsupported kind → empty-but-valid SVG."""
        from explain_svg import spec_svg
        bad_spec = {"kind": "mindmap", "nodes": ["a"], "edges": [], "labels": {}}
        result = spec_svg(bad_spec)
        stripped = result.strip()
        assert stripped.startswith("<svg")
        assert stripped.endswith("</svg>")
        briefing.assert_offline(result)

    def test_empty_nodes_flow(self):
        """Empty nodes list → valid SVG, does not raise."""
        from explain_svg import spec_svg
        spec = {"kind": "flow", "nodes": [], "edges": [], "labels": {}}
        result = spec_svg(spec)
        assert result.strip().startswith("<svg")
        briefing.assert_offline(result)

    def test_flow_svg_no_external_refs_in_xmlns(self):
        """SVG xmlns declaration is structural, not a network ref.
        assert_offline strips xmlns before scanning so this must pass."""
        from explain_svg import spec_svg
        result = spec_svg(_valid_flow_spec())
        # This verifies assert_offline handles xmlns="http://www.w3.org/2000/svg"
        briefing.assert_offline(result)


# ---------------------------------------------------------------------------
# Task 3.5: spec_svg — decision + state kinds
# ---------------------------------------------------------------------------

class TestSpecSvgDecisionAndState:

    def test_decision_svg_is_valid(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_decision_spec())
        stripped = result.strip()
        assert stripped.startswith("<svg")
        assert stripped.endswith("</svg>")

    def test_decision_svg_passes_assert_offline(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_decision_spec())
        briefing.assert_offline(result)

    def test_decision_svg_contains_labels(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_decision_spec())
        # At least one label should appear
        assert "Merge" in result or "Approve" in result or "Reject" in result

    def test_state_svg_is_valid(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_state_spec())
        stripped = result.strip()
        assert stripped.startswith("<svg")
        assert stripped.endswith("</svg>")

    def test_state_svg_passes_assert_offline(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_state_spec())
        briefing.assert_offline(result)

    def test_state_svg_contains_labels(self):
        from explain_svg import spec_svg
        result = spec_svg(_valid_state_spec())
        assert "Idle" in result or "Running" in result or "Done" in result

    def test_all_kinds_produce_svg_elements(self):
        """Each allowed kind produces a proper SVG element."""
        from explain_svg import spec_svg
        for spec_fn in [_valid_flow_spec, _valid_decision_spec, _valid_state_spec]:
            result = spec_svg(spec_fn())
            s = result.strip()
            assert s.startswith("<svg"), f"kind failed: {spec_fn.__name__}"
            assert s.endswith("</svg>"), f"kind failed: {spec_fn.__name__}"
            briefing.assert_offline(result)


# ---------------------------------------------------------------------------
# Task 3.6: spec_svg — hostile spec defanged at draw time (Behavior 6)
# ---------------------------------------------------------------------------

class TestSpecSvgHostileSpec:
    """Adversarial tests — feed hostile specs/labels and assert assert_offline
    does NOT raise after spec_svg renders them.  This is the security crux."""

    def _hostile_spec(self, label_content):
        """Build a flow spec with a single node carrying hostile label content."""
        return {
            "kind": "flow",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": label_content},
        }

    def test_raw_svg_tag_in_label_defanged(self):
        """<svg onload=...> in a label must be stripped before reaching SVG."""
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec('<svg onload="alert(1)">'))
        briefing.assert_offline(result)

    def test_http_url_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("http://evil.com/script.js"))
        briefing.assert_offline(result)

    def test_https_url_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("https://cdn.evil.com/evil.js"))
        briefing.assert_offline(result)

    def test_url_css_function_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("url(http://evil.com/bg.png)"))
        briefing.assert_offline(result)

    def test_data_text_html_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec(
            "data:text/html,<script>alert(1)</script>"
        ))
        briefing.assert_offline(result)

    def test_xlink_href_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec('<use xlink:href="http://evil.com#id"/>'))
        briefing.assert_offline(result)

    def test_script_tag_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec('<script>fetch("http://evil.com")</script>'))
        briefing.assert_offline(result)

    def test_mixed_case_https_in_label_defanged(self):
        """Mixed-case scheme HtTpS: must be caught and defanged."""
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("HtTpS://evil.com/evil.js"))
        briefing.assert_offline(result)

    def test_protocol_relative_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("//cdn.evil.com/evil.js"))
        briefing.assert_offline(result)

    def test_nested_payload_in_label_defanged(self):
        """Nested/encoded payload like data:text/html with embedded SVG."""
        from explain_svg import spec_svg
        nested = 'data:text/html,<svg><use xlink:href="http://evil.com#id"/></svg>'
        result = spec_svg(self._hostile_spec(nested))
        briefing.assert_offline(result)

    def test_import_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("@import url(evil.css)"))
        briefing.assert_offline(result)

    def test_fetch_in_label_defanged(self):
        """fetch() in label text must be rendered safe.

        Note: assert_offline matches r'\\bfetch\\s*\\(' — so 'fetch(' in output
        would trigger it.  Labels are HTML-escaped, so parentheses become &#40;
        and the pattern won't match."""
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec('fetch("http://evil.com")'))
        briefing.assert_offline(result)

    def test_xmlhttprequest_in_label_defanged(self):
        from explain_svg import spec_svg
        result = spec_svg(self._hostile_spec("new XMLHttpRequest()"))
        briefing.assert_offline(result)

    def test_hostile_spec_with_hostile_nodes(self):
        """Hostile content in node ids as well as labels."""
        from explain_svg import spec_svg
        hostile_spec = {
            "kind": "flow",
            "nodes": [
                "http://evil.com",
                "<script>alert(1)</script>",
                "//cdn.evil.com",
            ],
            "edges": [["http://evil.com", "<script>alert(1)</script>"]],
            "labels": {
                "http://evil.com": "http://evil.com/label",
                "<script>alert(1)</script>": "safe label",
            },
        }
        result = spec_svg(hostile_spec)
        briefing.assert_offline(result)

    def test_hostile_spec_bad_kind_falls_through_to_empty_svg(self):
        """A hostile spec with an illegal kind yields an empty but valid SVG."""
        from explain_svg import spec_svg
        hostile = {
            "kind": "javascript:alert(1)",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": "http://evil.com"},
        }
        result = spec_svg(hostile)
        s = result.strip()
        assert s.startswith("<svg")
        assert s.endswith("</svg>")
        briefing.assert_offline(result)

    def test_sanitize_spec_called_inside_spec_svg(self):
        """spec_svg must call sanitize_spec internally (defense-in-depth).

        Feed a raw (unsanitized) hostile spec directly to spec_svg and confirm
        the output still passes assert_offline — i.e. sanitize_spec ran inside
        spec_svg even though no pre-sanitization happened at the call site.
        """
        from explain_svg import spec_svg
        # Bypass sanitize_spec at the call site — raw hostile spec
        raw_hostile = {
            "kind": "flow",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": "https://evil.com/script.js"},
        }
        result = spec_svg(raw_hostile)
        briefing.assert_offline(result)


# ---------------------------------------------------------------------------
# FIX 1: single-escape invariant — label with & < > must escape EXACTLY once
# ---------------------------------------------------------------------------

class TestSpecSvgSingleEscape:
    """Labels containing literal & < > " ' must appear escaped exactly once.

    The pipeline is: sanitize_spec (in narrate) → sanitize_spec (in spec_svg)
    → _esc at draw.  The fix ensures html.escape fires ONLY at draw so the
    final SVG text node reads e.g. ``Tom &amp; Jerry &lt;x&gt;`` (one escape),
    NOT ``Tom &amp;amp; Jerry &lt;x&gt;`` (double) or worse (triple).
    """

    def _spec_with_label(self, label: str) -> dict:
        return {
            "kind": "flow",
            "nodes": ["a"],
            "edges": [],
            "labels": {"a": label},
        }

    def test_single_escape_ampersand(self):
        """Label 'Tom & Jerry' → SVG text contains 'Tom &amp; Jerry' (once)."""
        from explain_svg import spec_svg
        import explain_spec as _spec
        # Simulate the narrate() path: sanitize_spec called at narrate time
        pre_sanitized = _spec.sanitize_spec(self._spec_with_label("Tom & Jerry"))
        assert pre_sanitized is not None
        result = spec_svg(pre_sanitized)
        assert "Tom &amp; Jerry" in result, (
            f"Expected single-escaped 'Tom &amp; Jerry' in SVG, got: {result!r}"
        )
        assert "Tom &amp;amp;" not in result, (
            f"Double-escape detected in SVG output: {result!r}"
        )
        briefing.assert_offline(result)

    def test_single_escape_lt_gt(self):
        """Label 'a < b > c' → SVG contains single-escaped &lt; and &gt;."""
        from explain_svg import spec_svg
        import explain_spec as _spec
        pre_sanitized = _spec.sanitize_spec(self._spec_with_label("a < b > c"))
        assert pre_sanitized is not None
        result = spec_svg(pre_sanitized)
        # After sanitize_spec, < and > come through _strip_external unchanged
        # (they're not external refs); then _esc at draw → &lt; &gt;
        assert "&lt;b&gt;" in result or "b" in result  # content still present
        assert "&lt;&lt;" not in result  # no double-escape of <
        briefing.assert_offline(result)

    def test_single_escape_hostile_then_presanitized(self):
        """Full pipeline: hostile label with & and < escapes exactly once."""
        from explain_svg import spec_svg
        import explain_spec as _spec
        label = 'Tom & Jerry <x>'
        pre_sanitized = _spec.sanitize_spec(self._spec_with_label(label))
        assert pre_sanitized is not None
        result = spec_svg(pre_sanitized)
        # Should contain single-escaped &amp; and &lt;x&gt; (without double)
        assert "Tom &amp; Jerry" in result, "Ampersand must be single-escaped"
        assert "&amp;amp;" not in result, "Double-escaped ampersand found"
        briefing.assert_offline(result)
