"""test_tier_ladder_route.py — route_label with routed-only env binding.

design: hybrid-routing-hardening (detailed-design.md §Effective-tier seam)

Pure unit tests for ``tier_ladder.route_label`` only (Task 3.1). Every call
passes an explicit ``env`` dict — never ``os.environ`` — so the tests hold
regardless of what this session's own ``ANTHROPIC_BASE_URL`` is set to.
"""
from __future__ import annotations

import local_route_check
import local_route_log
import tier_ladder

LOOPBACK = "http://127.0.0.1:3457"
REMOTE = "http://example.com:9999"
LOOPBACK_REDACTED = local_route_check.redact_url(LOOPBACK)


def _result(state: str, reason: str, base_url: str | None) -> dict:
    return {
        "schema": "tp-local-route/v1", "state": state, "reason": reason,
        "base_url": base_url, "checked_at": "2026-09-27T00:00:00Z",
        "ollama": None, "detail": "",
    }


def _window(state: str, reason: str, base_url: str | None, *, frm: str = "none") -> str:
    """Decisions.md text with one open-window ``[routing]`` entry."""
    result = _result(state, reason, base_url)
    entry = local_route_log.render_entry(result, "run-start", frm)
    return "# Decisions log — schema v1\n\n" + entry + "\n"


def _closed_window() -> str:
    """A window whose only entry is followed by an ``end`` line — closed."""
    text = _window("routed", "ok", LOOPBACK_REDACTED)
    return text + "\n### [routing] end: routing: routed/ok\n"


# --- --route wins when given ----------------------------------------------

def test_valid_route_label_is_state_slash_reason():
    route = _result("router-down", "timeout", None)
    assert tier_ladder.route_label(route=route) == "router-down/timeout"


def test_valid_route_as_json_string():
    route = _result("unrouted", "no-base-url", None)
    import json
    assert tier_ladder.route_label(route=json.dumps(route)) == "unrouted/no-base-url"


def test_invalid_route_is_malformed():
    assert tier_ladder.route_label(route={"not": "a route"}) == tier_ladder.MALFORMED


# --- absent / unreadable file / empty / closed window -> missing-route ----

def test_absent_route_and_text_is_missing():
    assert tier_ladder.route_label() == tier_ladder.MISSING


def test_unreadable_file_mapped_to_none_text_is_missing():
    # The CLI maps an unreadable path to route_from_text=None (Task 3.3);
    # route_label itself just sees None here.
    assert tier_ladder.route_label(route_from_text=None) == tier_ladder.MISSING


def test_empty_window_is_missing():
    text = "# Decisions log — schema v1\n\nnothing routing-shaped here\n"
    assert tier_ladder.route_label(route_from_text=text) == tier_ladder.MISSING


def test_closed_window_is_missing():
    assert tier_ladder.route_label(route_from_text=_closed_window()) == tier_ladder.MISSING


# --- routed window: env binding --------------------------------------------

def test_routed_window_env_unset_is_stale():
    text = _window("routed", "ok", LOOPBACK_REDACTED)
    assert tier_ladder.route_label(route_from_text=text, env={}) == tier_ladder.STALE


def test_routed_window_base_url_differs_from_env_is_stale():
    text = _window("routed", "ok", LOOPBACK_REDACTED)
    env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9999"}
    assert tier_ladder.route_label(route_from_text=text, env=env) == tier_ladder.STALE


def test_routed_window_same_base_url_is_routed_ok():
    text = _window("routed", "ok", LOOPBACK_REDACTED)
    env = {"ANTHROPIC_BASE_URL": LOOPBACK}
    assert tier_ladder.route_label(route_from_text=text, env=env) == "routed/ok"


# --- non-routed file-borne entries are never env-bound ----------------------

def test_unrouted_no_base_url_window_keeps_label_with_env_unset():
    text = _window("unrouted", "no-base-url", None)
    assert tier_ladder.route_label(route_from_text=text, env={}) == "unrouted/no-base-url"


def test_unrouted_non_loopback_window_keeps_label_under_remote_env():
    text = _window("unrouted", "non-loopback", None)
    env = {"ANTHROPIC_BASE_URL": REMOTE}
    assert tier_ladder.route_label(route_from_text=text, env=env) == "unrouted/non-loopback"


# --- route_floor: the no-Haiku rule's floor (Task 3.2) ----------------------

NON_ROUTED_LABELS = (
    "unrouted/no-base-url", "unrouted/non-loopback",
    "router-down/connect-refused", "router-down/timeout",
    "router-down/not-tp-router", "router-down/schema-unsupported",
    "router-down/bad-status", "router-down/error",
    tier_ladder.MISSING, tier_ladder.MALFORMED, tier_ladder.STALE,
)


def test_route_floor_table():
    for label in NON_ROUTED_LABELS:
        assert tier_ladder.route_floor("local", label) == ("sonnet", True)
    assert tier_ladder.route_floor("local", "routed/ok") == ("local", False)
    all_labels = NON_ROUTED_LABELS + ("routed/ok",)
    for tier in ("sonnet", "opus"):
        for label in all_labels:
            assert tier_ladder.route_floor(tier, label) == (tier, False)


def test_effective_model_refuses_haiku_unrouted():
    cfg_haiku = {"model": "haiku", "fallback_model": "HAIKU",
                 "max_retries": 1, "escalate": True}
    assert (tier_ladder.effective_model("sonnet", cfg_haiku, "unrouted/no-base-url")
            == tier_ladder.SAFE_CLAUDE)
    assert tier_ladder.effective_model("sonnet", cfg_haiku, "routed/ok") == "HAIKU"

    cfg_sonnet_fallback = dict(cfg_haiku, fallback_model="sonnet")
    for label in ("unrouted/no-base-url", "routed/ok"):
        assert (tier_ladder.effective_model("sonnet", cfg_sonnet_fallback, label)
                == "sonnet")

    cfg_qwen_fallback = dict(cfg_haiku, fallback_model="qwen-coder")
    for label in ("unrouted/no-base-url", "routed/ok"):
        assert (tier_ladder.effective_model("sonnet", cfg_qwen_fallback, label)
                == "qwen-coder")

    for label in ("unrouted/no-base-url", "routed/ok"):
        assert tier_ladder.effective_model("opus", cfg_haiku, label) == "opus"


def test_route_floor_keys_on_the_local_family():
    """A future `local-<size>` rung floors like `local`; `localhost`-style names do not."""
    assert tier_ladder.route_floor("local-medium", "unrouted/no-base-url") == (
        "sonnet-medium", True)
    assert tier_ladder.route_floor("local-medium", "routed/ok") == ("local-medium", False)
    assert tier_ladder.route_floor("localish", "unrouted/no-base-url") == ("localish", False)


def test_display_names_the_floor():
    assert (tier_ladder.display("local", "sonnet", "unrouted/no-base-url")
            == "local->sonnet: unrouted/no-base-url")
    assert tier_ladder.display("local", "local", "routed/ok") == "local"
    assert tier_ladder.display("sonnet", "sonnet", "unrouted/no-base-url") == "sonnet"
    assert tier_ladder.display("sonnet", "sonnet", "routed/ok") == "sonnet"
