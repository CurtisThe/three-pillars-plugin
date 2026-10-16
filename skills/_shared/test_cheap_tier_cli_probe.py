"""Tests for `cheap_tier_cli.py spec --probe [--design D]`.

design: cheap-tier-local-routing (Task 5.1; detailed-design.md §Interfaces
`cheap_tier_cli.py spec ... [--probe] [--design D]`).

`--probe` runs `cheap_route.probe` and feeds its labels to `cheap_tier.resolve`; the output
gains `requested_rung`, `fallback`, `lease_wait_s` and `measure`. Without `--probe` the line is
today's, byte for byte. No case reads operator state: HOME and the state dirs point at tmp_path,
the in-process cases stub `cheap_route.probe`, and the end-to-end cases run a subprocess with an
explicit env (no `tp-local` on PATH, no live router, no network).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_ref  # noqa: E402
import cheap_route  # noqa: E402
import cheap_tier  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402
import measure_window  # noqa: E402
import model_policy  # noqa: E402

SHARED = Path(__file__).resolve().parent
LOCAL = {"enabled": True, "model": "qwen3-coder", "fallback_model": "sonnet"}
NEW_KEYS = {"requested_rung", "fallback", "lease_wait_s", "measure"}
CONFIG = {"models": {"docs_draft": "local-medium"}, "local_implement": LOCAL}


def _route(state: str, reason: str) -> str:
    return json.dumps({"schema": "tp-local-route/v1", "state": state, "reason": reason,
                       "base_url": "http://127.0.0.1:3457", "checked_at": "2026-10-02T00:00:00Z"})


ROUTED = _route("routed", "ok")
UNROUTED = _route("unrouted", "no-base-url")
DOWN = _route("router-down", "connect-refused")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No operator state: state dirs and HOME under tmp_path, no router, no git discovery."""
    state = tmp_path / "state"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("TP_LOCAL_LOG", str(state / "tp-local" / "router.log"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


@pytest.fixture
def probe(monkeypatch):
    """Stub `cheap_route.probe`: `(calls, answer)`; a test edits `answer` before the call."""
    calls = []
    answer = {"route_label": "routed/ok", "lease_state": "free", "lease_why": "free",
              "lease_wait_s": 0.0, "measure": "off", "fallback": None}

    def fake(slot, rung, root, **kwargs):
        calls.append({"slot": slot, "rung": rung, "root": str(root), **kwargs})
        return dict(answer)

    monkeypatch.setattr(cheap_route, "probe", fake)

    def no_lease(*_a, **_k):
        raise AssertionError("--probe takes the lease through cheap_route.probe only")

    monkeypatch.setattr(cli.local_lease, "acquire", no_lease)
    return calls, answer


def _root(tmp_path: Path, config=CONFIG) -> Path:
    cfg = tmp_path / "repo" / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return tmp_path / "repo"


def _spec(capsys, root: Path, slot: str, *extra: str):
    code = cli.main(["spec", "--slot", slot, "--root", str(root), *extra])
    out, err = capsys.readouterr()
    return code, (json.loads(out) if out.strip() else None), err


def test_probe_adds_the_four_keys_and_resolves_through_the_probe(tmp_path, capsys, probe):
    calls, answer = probe
    answer.update(lease_wait_s=42.5, measure="owner")
    code, spec, _err = _spec(capsys, _root(tmp_path), "docs_draft", "--cheap-tier", "on",
                             "--probe", "--design", "D", "--route", ROUTED)
    assert code == 0
    assert spec == {
        "slot": "docs_draft", "rung": "local-medium", "why": "local-medium: routed/ok, lease free",
        "agent": "tp-drafter", "agent_ref": agent_ref.resolve("tp-drafter"),
        "model": "qwen3-coder", "oracle": "prose_shape", "on_fail": "drop", "mode": "on",
        "requested_rung": "local-medium", "fallback": None, "lease_wait_s": 42.5,
        "measure": "owner", "mirror_rung": "sonnet-medium",
        "mirror_agent_ref": agent_ref.resolve("tp-drafter"), "mirror_model": "sonnet"}
    assert [(c["slot"], c["rung"], c["design"], c["route"]) for c in calls] == [
        ("docs_draft", "local-medium", "D", ROUTED)]


@pytest.mark.parametrize("label, lease_state, fallback, tail", [
    ("routed/ok", "busy", "local-busy", "lease busy"),
    ("routed/ok", "busy-measure", "local-busy-measure", "lease busy-measure"),
    ("unrouted/no-base-url", "unchecked", "unrouted", "route unrouted/no-base-url"),
    ("router-down/timeout", "unchecked", "unreachable", "route router-down/timeout"),
])
def test_probe_labels_floor_the_rung_to_its_mirror(tmp_path, capsys, probe, label, lease_state,
                                                   fallback, tail):
    _calls, answer = probe
    answer.update(route_label=label, lease_state=lease_state, fallback=fallback)
    _code, spec, _err = _spec(capsys, _root(tmp_path), "docs_draft", "--cheap-tier", "on",
                              "--probe")
    assert spec["rung"] == "sonnet-medium" and spec["why"].endswith(tail)
    assert spec["requested_rung"] == "local-medium" and spec["fallback"] == fallback
    assert spec["model"] == "sonnet" and spec["agent"] == "tp-drafter"
    assert spec["lease_wait_s"] == 0.0 and spec["measure"] == "off"


def test_probe_on_a_sonnet_rung_requests_that_rung(tmp_path, capsys, probe):
    _calls, answer = probe
    answer.update(route_label="unrouted/rung", lease_state="unchecked")
    root = _root(tmp_path, {"models": {"handoff": "sonnet-medium"}})
    _code, spec, _err = _spec(capsys, root, "handoff", "--cheap-tier", "on", "--probe")
    assert (spec["rung"], spec["requested_rung"], spec["fallback"]) == (
        "sonnet-medium", "sonnet-medium", None)
    assert NEW_KEYS <= set(spec)


def test_design_is_optional_and_passed_through(tmp_path, capsys, probe):
    calls, _answer = probe
    root = _root(tmp_path)
    _spec(capsys, root, "docs_draft", "--cheap-tier", "on", "--probe")
    _spec(capsys, root, "docs_draft", "--cheap-tier", "on", "--probe", "--design", "my-design")
    assert [c["design"] for c in calls] == [None, "my-design"]


def test_the_probe_gets_the_route_text_from_route_from(tmp_path, capsys, probe):
    calls, _answer = probe
    decisions = tmp_path / "decisions.md"
    decisions.write_text("route text\n", encoding="utf-8")
    _spec(capsys, _root(tmp_path), "docs_draft", "--cheap-tier", "on", "--probe",
          "--route-from", str(decisions))
    assert calls[0]["route_text"] == "route text\n" and calls[0]["route"] is None


@pytest.mark.parametrize("extra", [[], ["--design", "D"]])
def test_without_probe_the_line_is_byte_identical(tmp_path, capsys, probe, monkeypatch, extra):
    monkeypatch.setattr(cli.local_lease, "acquire", lambda *a, **k: ("free", "unowned"))
    root = _root(tmp_path)
    assert cli.main(["spec", "--slot", "docs_draft", "--root", str(root), "--cheap-tier", "on",
                     "--route", ROUTED, *extra]) == 0
    expected = {"slot": "docs_draft", "rung": "local-medium",
                "why": "local-medium: routed/ok, lease free", "agent": "tp-drafter",
                "agent_ref": agent_ref.resolve("tp-drafter"), "model": "qwen3-coder",
                "oracle": "prose_shape", "on_fail": "drop", "mode": "on"}
    assert capsys.readouterr().out == json.dumps(expected, sort_keys=True) + "\n"
    assert probe[0] == []


def test_a_null_rung_and_a_code_rung_never_probe(tmp_path, capsys, probe):
    off_root = _root(tmp_path / "off", {"models": {"docs_draft": "off"}})  # the one off key
    off = _spec(capsys, off_root, "docs_draft", "--probe")
    assert off[:2] == (0, {"slot": "docs_draft", "rung": None})
    code_root = _root(tmp_path / "code", {"models": {"runbook": "code"}})
    code, spec, _err = _spec(capsys, code_root, "runbook", "--cheap-tier", "on", "--probe")
    assert code == 0 and spec["rung"] == "code" and not NEW_KEYS & set(spec)
    assert probe[0] == []


EXCLUDED = sorted(r for r in cheap_tier.EXCLUDED if r not in model_policy.ROLES)


@pytest.mark.parametrize("role", EXCLUDED)
def test_an_excluded_role_through_probe_still_raises(tmp_path, capsys, probe, role):
    root = _root(tmp_path, {"models": {role: "sonnet-medium"}})
    with pytest.raises(ValueError, match=role):
        cli.spec("docs_draft", root, cheap_flag="on", probe=True)
    code, spec, err = _spec(capsys, root, "docs_draft", "--cheap-tier", "on", "--probe")
    assert (code, spec) == (2, None) and role in err and len(err.strip().splitlines()) == 1
    code, spec, err = _spec(capsys, _root(tmp_path / "s", CONFIG), role, "--cheap-tier", "on",
                            "--probe")
    assert (code, spec) == (2, None) and len(err.strip().splitlines()) == 1
    assert probe[0] == []


def test_without_design_a_live_window_makes_the_caller_a_non_owner(tmp_path, capsys):
    """The real probe: a live window held by another design, no `--design`."""
    env = dict(os.environ)
    assert measure_window.main(["start", "--design", "other-d", "--hours", "1"], env=env) == 0
    capsys.readouterr()
    code, spec, _err = _spec(capsys, _root(tmp_path), "docs_draft", "--cheap-tier", "on",
                             "--probe", "--route", ROUTED)
    assert code == 0
    assert (spec["rung"], spec["fallback"], spec["measure"], spec["lease_wait_s"]) == (
        "sonnet-medium", "local-busy-measure", "other", 0.0)


def test_without_a_window_the_measure_is_off(tmp_path, capsys):
    code, spec, _err = _spec(capsys, _root(tmp_path), "docs_draft", "--cheap-tier", "on",
                             "--probe", "--route", UNROUTED)
    assert code == 0
    assert (spec["fallback"], spec["measure"], spec["lease_wait_s"]) == ("unrouted", "off", 0.0)


# --- end to end through both CLIs ------------------------------------------------------


def _subprocess_env(tmp_path: Path, **extra: str) -> dict:
    """An explicit env: PATH holds no `tp-local` (an empty dir), state and HOME in tmp_path."""
    (tmp_path / "bin").mkdir(exist_ok=True)
    state = tmp_path / "state"
    return {"PATH": str(tmp_path / "bin"), "HOME": str(tmp_path / "home"),
            "XDG_STATE_HOME": str(state), "TP_LOCAL_LOG": str(state / "tp-local" / "router.log"),
            "GIT_CEILING_DIRECTORIES": str(tmp_path.parent), **extra}


def _run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SHARED / script), *args], env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("env_extra, route_args, fallback", [
    ({}, [], "unrouted"),  # the consumer: no ANTHROPIC_BASE_URL, no tp-local
    ({"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}, ["--route", DOWN], "unreachable"),
])
def test_unrouted_and_router_down_serve_the_mirror_end_to_end(tmp_path, env_extra, route_args,
                                                              fallback):
    env = _subprocess_env(tmp_path, **env_extra)
    root = _root(tmp_path)
    proc = _run("cheap_tier_cli.py", env, "spec", "--slot", "docs_draft", "--root", str(root),
                "--cheap-tier", "on", "--probe", *route_args)
    assert proc.returncode == 0, proc.stderr
    spec = json.loads(proc.stdout)
    got = {k: spec.get(k) for k in ("requested_rung", "rung", "fallback")}
    want = {"requested_rung": "local-medium", "rung": "sonnet-medium", "fallback": fallback}
    assert got == want, (  # named in full: pytest's tuple repr truncates the values
        f"spec --probe served {got} where the mirror {want} was expected")
    assert spec["lease_wait_s"] == 0.0 and isinstance(spec["lease_wait_s"], float)
    assert spec["measure"] == "off"
    rec = _run("dispatch_log.py", env, "record", "--design-dir", str(tmp_path), "--role",
               "docs_draft", "--agent", "tp-drafter", "--reason", "x", "--outcome", "y",
               "--root", str(tmp_path), "--config-dir", str(tmp_path),
               "--requested-rung", spec["requested_rung"], "--rung", spec["rung"],
               "--lease-wait-s", str(spec["lease_wait_s"]), "--fallback", spec["fallback"])
    assert rec.returncode == 0, rec.stderr
    row = json.loads(rec.stdout)
    got = {k: row.get(k) for k in ("served_rung", "fallback", "lease_wait_s")}
    want = {"served_rung": "sonnet-mirror", "fallback": fallback, "lease_wait_s": 0.0}
    assert got == want, f"dispatch_log record stored {got} where {want} was expected"
