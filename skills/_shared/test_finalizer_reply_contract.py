"""The finalizer's reply contract: what the agent file and brief instruct is what `validate` accepts.

design: fable-first-stops (impl-audit fix). `validate` escalates any `actions` entry outside
`ALLOWED_ACTIONS`, so the agent file and the dispatch brief must name those exact tokens. The
token set is derived from the constant, never hand-typed here.
Run with: python3 -m pytest skills/_shared/test_finalizer_reply_contract.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer as fin  # noqa: E402
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _envelope() -> str:
    """The agent file's reply-envelope section, read at call time (collection never reads it)."""
    agent = (REPO_ROOT / "agents" / "tp-finalizer.md").read_text(encoding="utf-8")
    return agent[agent.index("## Reply envelope"):]

STOP = {"source": "pr-iterate", "signal": "round-cap",
        "target": "https://github.com/acme/widgets/pull/42", "head": "a1" * 20}


def _listed_tokens() -> list:
    """The tokens the `actions` bullet names after "exactly one of", in order."""
    bullet = next(ln for ln in _envelope().splitlines() if ln.startswith("- `actions`:"))
    listing = bullet.split("exactly one of", 1)[1].split("(", 1)[0]
    return re.findall(r"`([a-z-]+)`", listing)


def _example_reply() -> dict:
    match = re.search(r"`(\{\"outcome\".*?\})`", _envelope())
    assert match, "the agent file carries no example reply"
    return json.loads(match.group(1))


def test_agent_file_lists_exactly_the_allowed_tokens():
    assert sorted(_listed_tokens()) == sorted(fo.ALLOWED_ACTIONS)


def test_agent_file_example_reply_validates_resolved():
    reply = _example_reply()
    result = fo.validate(reply)
    assert result["outcome"] == "resolved" and result["problems"] == [], (
        f"documented example reply did not validate as resolved: {result}")
    assert result["actions"] == reply["actions"]


def test_reply_built_from_the_listed_tokens_validates_resolved():
    tokens = _listed_tokens()
    reply = {"outcome": "resolved", "actions": tokens, "diagnosis": "d",
             "reasoning": "Fixed the flaky assertion in test_x.py; pytest: 412 passed. Per vision.md.",
             "demoted": [], "blocked": [], **fr.EMPTY_RULING}
    assert fo.validate(reply)["outcome"] == "resolved"


def test_free_text_actions_still_escalate():
    reply = _example_reply()
    reply["actions"] = ["Fixed flaky assertion in test_x.py", "Ran pytest: 412 passed"]
    assert fo.validate(reply)["outcome"] == "escalate"


def test_agent_file_limits_blocked_to_denials():
    bullet = next(ln for ln in _envelope().splitlines() if ln.startswith("- `blocked`:"))
    assert "permission or classifier denial" in bullet


def test_brief_names_every_allowed_token(tmp_path):
    out = fin.prepare(STOP, tmp_path / "ledger.json", resolve_fn=lambda a: f"three-pillars:{a}")
    assert out["status"] == "dispatch"
    for token in fo.ALLOWED_ACTIONS:
        assert f"`{token}`" in out["brief"], token
    assert "permission or classifier denial" in out["brief"]


# --- PR #188: the strict reply contract (round-4 ruling "Strict fix") ---
# Exactly one JSON object, bare or inside ONE fence. Rounds 1-3 read the envelope out of prose;
# those shapes now escalate. Non-conforming inputs at large: test_finalizer_reply_strict.py.

import pytest  # noqa: E402

import finalizer_cli as cli  # noqa: E402

FENCE = "\x60" * 3  # three backticks, built at runtime
F4 = FENCE + "\x60"  # a CommonMark longer fence: the remedy when the content quotes ```
PR_URL = "https://github.com/acme/widgets/pull/42"
RESOLVED = {"outcome": "resolved", "actions": ["fix", "confirm", "converge"], "diagnosis": "d",
            "reasoning": "r (vision.md)", "demoted": [], "blocked": [], **fr.EMPTY_RULING}


def _apply_reply(tmp_path, capsys, monkeypatch, stop, reply_text, *more):
    monkeypatch.chdir(tmp_path)  # no repo config: limits fall back to the defaults
    calls = []
    seams = {"comment_fn": lambda u, b: calls.append(("comment", b)) or True,
             "label_fn": lambda u, lb: calls.append(("label", lb)) or True,
             "resolve_fn": lambda a: f"three-pillars:{a}",
             "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
             "is_ancestor_fn": lambda a, b: True, "now": 1_800_000_000.0}
    ledger, reply = tmp_path / "ledger.json", tmp_path / "reply.md"
    reply.write_text(reply_text, encoding="utf-8")
    cap6 = tmp_path / "cap6.json"  # keep-the-pin: 8→10 predates the review-weight cap of 3
    cap6.write_text(json.dumps({"pdw": {"guards": {"round_cap": 6}}}), encoding="utf-8")
    assert cli.main(["prepare", "--stop", json.dumps(stop), "--ledger", str(ledger)], **seams) == 0
    capsys.readouterr()
    rc = cli.main(["apply", "--stop", json.dumps(stop), "--ledger", str(ledger), "--reply", str(reply),
                   "--decisions", str(tmp_path / "decisions.md"), "--config", str(cap6),
                   *more], **seams)
    out = json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1])
    return rc, out, calls


def _round_cap_stop_and_state(tmp_path):
    stop = {"source": "pr-iterate", "signal": "round-cap", "target": PR_URL, "head": "a1" * 20,
            "detail": {"iteration": 8, "round_cap": 6, "signal": "round-cap",
                       "measured": 8, "limit": 6, "holding": ["round-cap"]}}
    state = tmp_path / "iterate-state.json"
    state.write_text(json.dumps({"phase": "budget-exhausted", "termination_reason": "round-cap",
                                 "iteration": 8, "reproduced_blockers": 1}), encoding="utf-8")
    return stop, state


def _fenced(env, fence=FENCE, tag="json") -> str:
    return fence + tag + "\n" + json.dumps(env) + "\n" + fence + "\n"


@pytest.mark.parametrize("text", [
    json.dumps(RESOLVED),
    "\n  " + json.dumps(RESOLVED, indent=2) + "\n\n",
    _fenced(RESOLVED), _fenced(RESOLVED, tag=""), _fenced(RESOLVED, tag="JSON"),
    _fenced(RESOLVED, fence=F4), _fenced(RESOLVED, fence="~~~"),
    "  " + FENCE + "json\n" + json.dumps(RESOLVED) + "\n  " + FENCE + "  ",  # indent, no newline
    FENCE + "json\r\n" + json.dumps(RESOLVED) + "\r\n" + FENCE + "\r\n",
])
def test_a_conforming_reply_is_its_envelope(text):
    assert cli._envelope(text) == RESOLVED


def test_bare_envelope_resolves_with_the_extension(tmp_path, capsys, monkeypatch):
    stop, state = _round_cap_stop_and_state(tmp_path)
    rc, out, calls = _apply_reply(tmp_path, capsys, monkeypatch, stop, json.dumps(RESOLVED),
                                  "--state", str(state))
    assert rc == 0 and out["outcome"] == "resolved", out
    assert out["extension"] == {"signal": "round-cap", "from": 8, "to": 10}
    assert ("label", "tp:needs-human-attention") not in calls


@pytest.mark.parametrize("fence", [FENCE, F4])
def test_resolved_envelope_whose_reasoning_quotes_a_fence_still_resolves(tmp_path, capsys,
                                                                         monkeypatch, fence):
    stop, state = _round_cap_stop_and_state(tmp_path)
    env = dict(RESOLVED, reasoning="The angle reply quoted " + FENCE + "json in a summary; escaped it "
               "(architecture.md).")
    rc, out, calls = _apply_reply(tmp_path, capsys, monkeypatch, stop, _fenced(env, fence=fence),
                                  "--state", str(state))
    assert rc == 0 and out["outcome"] == "resolved", out
    assert out["extension"] == {"signal": "round-cap", "from": 8, "to": 10}
    assert ("label", "tp:needs-human-attention") not in calls


def test_escalate_diagnosis_quoting_a_fence_reaches_the_operator(tmp_path, capsys, monkeypatch):
    stop, state = _round_cap_stop_and_state(tmp_path)
    diag = "Two angles quoted " + FENCE + "json [] " + FENCE + " so their findings were dropped."
    env = dict(RESOLVED, outcome="escalate", actions=["classify"], diagnosis=diag)
    rc, out, calls = _apply_reply(tmp_path, capsys, monkeypatch, stop, _fenced(env),
                                  "--state", str(state))
    assert rc == 0 and out["outcome"] == "escalate"
    assert "finalizer-errored: unparseable JSON" not in out["problems"], out
    comments = [b for kind, b in calls if kind == "comment"]
    assert comments and diag in comments[0], comments


@pytest.mark.parametrize("text", [
    # the round-1..3 lenient shapes: prose, extra blocks, or fragments around the envelope
    "Fixed the flaky assertion.\n" + FENCE + "text\npytest: 412 passed\n" + FENCE + "\n"
    "Envelope:\n" + _fenced(RESOLVED),
    "Re-ran the audit:\n\n" + FENCE + "bash\npython3 -m pytest -q\n" + FENCE + "\n\n" + _fenced(RESOLVED),
    "Patched plan.md. This reply ends with one fenced " + FENCE + "json envelope.\n\n" + _fenced(RESOLVED),
    'Fragments {"outcome": "escalate"} and {not json} first.\n' + json.dumps(RESOLVED),
    json.dumps(RESOLVED) + "\nDone.",
    "Result:\n" + FENCE + "text\n" + FENCE + "\n\n" + _fenced(RESOLVED),
])
def test_prose_or_blocks_around_the_envelope_escalate_without_a_grant(tmp_path, capsys,
                                                                      monkeypatch, text):
    stop, state = _round_cap_stop_and_state(tmp_path)
    rc, out, calls = _apply_reply(tmp_path, capsys, monkeypatch, stop, text, "--state", str(state))
    assert rc == 0 and out["outcome"] == "escalate", out
    assert out["problems"] == ["finalizer-errored: unparseable JSON"], out
    assert out["extension"] is None
    assert ("label", "tp:needs-human-attention") in calls
    assert "budget_extensions" not in json.loads(state.read_text(encoding="utf-8"))
