"""test_local_route_append.py — the Task 2.4 `append` CLI contract: the one
mechanical writer of `[routing]` entries in a design's decisions.md.

design: hybrid-routing-hardening (detailed-design.md §local_route_log.py →
"`append` CLI")

`append --decisions PATH` reads one JSON line on stdin. A check line
(`parse_result` accepts it) appends `transition.entry` byte-for-byte and
prints the five-key `route` (the `ROUTE_KEYS` projection — never
`transition`/`ollama`/`detail`) for every valid check line, whatever the
transition. An end line appends its `entry` and prints `line`. A no-op never
creates the file; a written first entry is preceded by the auto-mode schema
header. Invalid stdin never touches the file. Every case exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import local_route_check  # noqa: E402
import local_route_log  # noqa: E402

CLI = _SHARED / "local_route_log.py"
SCHEMA_HEADER = "# Decisions log — schema v1\n"
CHECKED_AT = "2026-09-27T21:04:11Z"


def _run_cli(decisions: Path, stdin: str) -> dict:
    env = dict(os.environ)
    env.pop("ANTHROPIC_BASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-I", str(CLI), "append", "--decisions", str(decisions)],
        input=stdin, capture_output=True, text=True, timeout=30, env=env,
    )
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr}"
    return json.loads(proc.stdout)


def _result(state: str, reason: str, **kw) -> dict:
    return {"schema": local_route_check.SCHEMA, "state": state, "reason": reason,
            "base_url": kw.get("base_url"), "checked_at": CHECKED_AT,
            "ollama": None, "detail": ""}


def _check_line(transition: object) -> str:
    result = local_route_check.decide({}, None, checked_at=CHECKED_AT)
    return json.dumps({**result, "transition": transition})


def _end_line(text: str) -> str:
    return json.dumps({"line": local_route_log.summary_line(text),
                       "entry": local_route_log.end_entry(text)})


# ---------------------------------------------------------------------------
# check lines: byte-exact append + the five-key route, whatever the transition
# ---------------------------------------------------------------------------

def test_check_line_appends_entry_byte_exact_and_prints_route(tmp_path):
    decisions = tmp_path / "decisions.md"
    result = _result("routed", "ok", base_url="http://127.0.0.1:8787", ollama="up")
    line = _check_line(local_route_log.transition("", result, "run-start"))
    parsed = json.loads(line)
    entry = parsed["transition"]["entry"]
    out = _run_cli(decisions, line + "\n")
    assert decisions.read_bytes() == (
        SCHEMA_HEADER.encode("utf-8") + "\n".encode("utf-8")
        + entry.encode("utf-8") + b"\n")
    assert out == {
        "route": {k: parsed[k] for k in local_route_check.ROUTE_KEYS},
        "line": None, "appended": True, "error": None,
    }
    assert set(out["route"]) == set(local_route_check.ROUTE_KEYS)
    assert "transition" not in out["route"] and "ollama" not in out["route"] \
        and "detail" not in out["route"]


def test_check_line_appends_after_blank_line_when_file_exists(tmp_path):
    decisions = tmp_path / "decisions.md"
    content = "earlier text\n"
    decisions.write_text(content, encoding="utf-8")
    result = _result("routed", "ok", base_url="http://127.0.0.1:8787")
    parsed = json.loads(_check_line(local_route_log.transition("", result, "run-start")))
    entry = parsed["transition"]["entry"]
    out = _run_cli(decisions, json.dumps(parsed) + "\n")
    assert decisions.read_bytes() == content.encode("utf-8") \
        + b"\n" + entry.encode("utf-8") + b"\n"
    assert out["appended"] is True and out["error"] is None and out["route"] is not None


def test_check_line_transition_null_not_appended_route_still_five_keys(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("earlier text\n", encoding="utf-8")
    window = local_route_log.render_entry(
        {"state": "routed", "reason": "ok", "checked_at": CHECKED_AT,
         "base_url": None, "ollama": None, "detail": ""},
        "run-start", "none")
    line = _check_line(local_route_log.transition(window, {"state": "routed"}, "phase 1"))
    parsed = json.loads(line)
    out = _run_cli(decisions, line + "\n")
    assert out["appended"] is False and out["error"] is None and out["line"] is None
    assert out["route"] == {k: parsed[k] for k in local_route_check.ROUTE_KEYS}
    assert decisions.read_bytes() == b"earlier text\n"


def test_check_line_transition_error_not_appended_route_still_five_keys(tmp_path):
    decisions = tmp_path / "decisions.md"
    decisions.write_text("earlier text\n", encoding="utf-8")
    result = local_route_check.decide({}, None, checked_at=CHECKED_AT)
    line = json.dumps({**result, "transition": {"error": "permission denied"}})
    out = _run_cli(decisions, line + "\n")
    assert out["appended"] is False and out["line"] is None
    assert out["error"] == "transition error: permission denied"
    assert out["route"] == {k: result[k] for k in local_route_check.ROUTE_KEYS}
    assert decisions.read_bytes() == b"earlier text\n"


# ---------------------------------------------------------------------------
# end lines
# ---------------------------------------------------------------------------

def test_end_line_appends_entry_and_prints_line(tmp_path):
    decisions = tmp_path / "decisions.md"
    text = local_route_log.render_entry(
        {"state": "router-down", "reason": "connect-refused", "checked_at": CHECKED_AT,
         "base_url": "http://127.0.0.1:8787", "ollama": None, "detail": ""},
        "run-start", "none")
    line = _end_line(text)
    out = _run_cli(decisions, line + "\n")
    entry = json.loads(line)["entry"]
    assert out == {"route": None, "line": json.loads(line)["line"],
                   "appended": True, "error": None}
    assert decisions.read_bytes() == (
        SCHEMA_HEADER.encode("utf-8") + b"\n" + entry.encode("utf-8") + b"\n")


def test_end_line_entry_null_on_missing_file_creates_no_file(tmp_path):
    decisions = tmp_path / "decisions.md"
    out = _run_cli(decisions, json.dumps({"line": "routing: not checked",
                                          "entry": None}) + "\n")
    assert not decisions.exists()
    assert out == {"route": None, "line": "routing: not checked",
                   "appended": False, "error": None}


def test_check_line_transition_null_on_missing_file_creates_no_file(tmp_path):
    decisions = tmp_path / "decisions.md"
    # a `check` line whose `check` handler computed a null transition
    # (e.g. a reason-only change): no entry, so a missing file is never created
    result = local_route_check.decide({}, None, checked_at=CHECKED_AT)
    line = json.dumps({**result, "transition": None})
    out = _run_cli(decisions, line + "\n")
    assert not decisions.exists()
    assert out["appended"] is False and out["route"] is not None \
        and out["error"] is None


# ---------------------------------------------------------------------------
# invalid stdin: route null, error set, file untouched, exit 0 (always)
# ---------------------------------------------------------------------------

def _invalid(stdin: str, tmp_path: Path, existing: str | None = None) -> None:
    decisions = tmp_path / "decisions.md"
    if existing is not None:
        decisions.write_text(existing, encoding="utf-8")
    out = _run_cli(decisions, stdin)
    assert out["route"] is None and out["line"] is None
    assert out["appended"] is False and out["error"]
    if existing is None:
        assert not decisions.exists()
    else:
        assert decisions.read_bytes() == existing.encode("utf-8")


def test_non_json_stdin_invalid(tmp_path):
    _invalid("not json at all\n", tmp_path)


def test_non_dict_stdin_invalid(tmp_path):
    _invalid(json.dumps([1, 2, 3]) + "\n", tmp_path, existing="earlier text\n")


def test_check_line_with_unhashable_reason_list_invalid(tmp_path):
    _invalid(json.dumps({"schema": "tp-local-route/v1", "state": "routed",
                         "reason": ["ok"], "base_url": None,
                         "checked_at": CHECKED_AT,
                         "transition": {"from": "none", "entry": "### x"}}) + "\n",
             tmp_path, existing="earlier text\n")


def test_check_line_with_unhashable_reason_dict_invalid(tmp_path):
    _invalid(json.dumps({"schema": "tp-local-route/v1", "state": "routed",
                         "reason": {}, "base_url": None,
                         "checked_at": CHECKED_AT}) + "\n",
             tmp_path, existing="earlier text\n")


def test_end_line_with_malformed_entry_invalid(tmp_path):
    _invalid(json.dumps({"line": "routing: routed/ok",
                         "entry": "### [routing] end: no routing prefix"}) + "\n",
             tmp_path, existing="earlier text\n")


# ---------------------------------------------------------------------------
# summary_line consistency: an uncounted floor label still takes the
# "no routing check logged" branch, not the END-line / not-checked fallback
# ---------------------------------------------------------------------------

def test_end_line_uncounted_floor_uses_unknown_routing_summary(tmp_path):
    decisions = tmp_path / "decisions.md"
    text = "**Route floor**: local->sonnet: unrouted/no-base-url"
    assert local_route_log.summary_line(text) == (
        "routing: unknown (no routing check logged) -> claude ladder")
    line = _end_line(text)
    out = _run_cli(decisions, line + "\n")
    assert out["appended"] is True and out["error"] is None
    entry = json.loads(line)["entry"]
    assert entry.startswith(
        "### [routing] end: routing: unknown (no routing check logged) -> claude ladder")
    assert decisions.read_bytes() == (
        SCHEMA_HEADER.encode("utf-8") + b"\n" + entry.encode("utf-8") + b"\n")
