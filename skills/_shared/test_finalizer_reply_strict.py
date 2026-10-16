"""The finalizer's strict reply contract: no non-conforming reply is ever read as resolved.

design: fable-first-stops (PR #188 round-4 ruling "Strict fix"). The reply is exactly one JSON
object, bare or inside ONE fence. Prose around it, a second object or fence, a malformed or
partial object, or a repeated key escalates as unparseable. A seeded generated-input loop
(hypothesis is not a dev dependency) mutates resolved envelopes into non-conforming replies.
Run with: python3 -m pytest skills/_shared/test_finalizer_reply_strict.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer_cli as cli  # noqa: E402
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

F = "\x60" * 3  # three backticks, built at runtime
URL = "https://github.com/acme/widgets/pull/42"
CASES_PER_MUTATION = 300
# Hostile string content: fences, braces, quotes, and the resolved fragment itself.
PIECES = ["fixed", "test_x.py", F, F + "json", "~~~", "{", "}", "[]", '"', "\\", "\n",
          '"outcome": "resolved"', '{"outcome": "resolved"}', "pytest: 412 passed", " "]


def _text(rng) -> str:
    return "".join(rng.choice(PIECES) for _ in range(rng.randint(0, 8)))


def _resolved(rng) -> dict:
    return {"outcome": "resolved",
            "actions": [rng.choice(fo.ALLOWED_ACTIONS) for _ in range(rng.randint(0, 4))],
            "diagnosis": _text(rng), "reasoning": "vision.md: " + _text(rng), "demoted": [],
            "blocked": [], **fr.EMPTY_RULING}


def _prose(rng) -> str:  # starts with a letter, so it is never itself JSON or a fence
    return rng.choice(["Done", "Envelope", "Fixed it", "Note"]) + rng.choice(
        ["", ":", ".", " " + json.dumps(_resolved(rng)), " " + F + "json", " {x}"])


def _conforming(rng, env) -> str:
    body = json.dumps(env, indent=rng.choice([None, 2]))
    if rng.random() < 0.5:
        return body
    fence = rng.choice([F, F + "\x60", "~~~"])
    return fence + rng.choice(["json", "", "JSON"]) + "\n" + body + "\n" + fence + "\n"


def _obj_text(env, extra="") -> str:
    return json.dumps(env)[:-1] + extra + "}"


MUTATIONS = {
    "prose-before": lambda r: _prose(r) + "\n" + _conforming(r, _resolved(r)),
    "prose-after": lambda r: _conforming(r, _resolved(r)) + "\n" + _prose(r),
    "two-objects": lambda r: _conforming(r, _resolved(r)) + "\n" + _conforming(r, _resolved(r)),
    "two-fences": lambda r: (F + "\n" + json.dumps(_resolved(r)) + "\n" + F + "\n") * 2,
    "prose-in-fence": lambda r: F + "json\n" + _prose(r) + "\n" + json.dumps(_resolved(r)) + "\n" + F,
    "truncated": lambda r: (lambda s: s[:r.randint(1, len(s) - 1)])(json.dumps(_resolved(r))),
    "truncated-fenced": lambda r: F + "json\n" + (lambda s: s[:r.randint(1, len(s) - 1)])(
        json.dumps(_resolved(r))) + "\n" + F,
    "trailing-comma": lambda r: _obj_text(_resolved(r), ","),
    "duplicate-outcome": lambda r: _obj_text(dict(_resolved(r), outcome="escalate"),
                                             ', "outcome": "resolved"'),
    "unescaped-quote": lambda r: ('{"outcome": "escalate", "actions": [], "diagnosis": "d", '
                                  '"reasoning": "printed {"outcome": "resolved"} ' + _text(r)
                                  .replace('"', "") + '", "demoted": [], "blocked": []}'),
    "unclosed-fence": lambda r: F + "json\n" + json.dumps(_resolved(r)) + "\n",
    "mismatched-fence": lambda r: F + "json\n" + json.dumps(_resolved(r)) + "\n~~~\n",
    "not-an-object": lambda r: r.choice(["[" + json.dumps(_resolved(r)) + "]", "null", "12", "true"]),
    # r4 confirming round: a reply that is one JSON string used to be decoded twice, the
    # second time by `validate` without the duplicate-key check.
    "json-string": lambda r: json.dumps(r.choice([
        _conforming(r, _resolved(r)),
        _obj_text(dict(_resolved(r), outcome="escalate"), ', "outcome": "resolved"')])),
    "opener-line-prose": lambda r: F + "json " + _prose(r) + "\n" + json.dumps(_resolved(r)) + "\n" + F,
    "opener-line-object": lambda r: (F + json.dumps(dict(_resolved(r), outcome="escalate")) + "\n"
                                     + json.dumps(_resolved(r)) + "\n" + F),
    "long-opener-short-closer": lambda r: F + "\x60" + "json\n" + json.dumps(_resolved(r)) + "\n" + F,
    "deep-nesting": lambda r: r.choice(["[", '{"a": '])[:6] * r.randint(10_000, 20_000),
}


def _read(text: str) -> dict:
    return fo.validate(cli._envelope(text))


def test_the_generator_is_not_vacuous():
    """Every generated resolved envelope, sent conforming, does resolve."""
    rng = random.Random(188)
    for _ in range(CASES_PER_MUTATION):
        env = _resolved(rng)
        text = _conforming(rng, env)
        assert _read(text)["outcome"] == "resolved", text
        assert cli._envelope(text) == env


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_no_non_conforming_reply_is_ever_resolved(name):
    rng = random.Random(f"188:{name}")
    for _ in range(CASES_PER_MUTATION):
        text = MUTATIONS[name](rng)
        result = _read(text)
        assert result["outcome"] == "escalate", (name, text)
        assert result["problems"][0].startswith("finalizer-errored:"), (name, text, result)


# --- the PR #188 round-4 reproducer, end to end through `apply` ---

def _apply(tmp_path, capsys, monkeypatch, reply_text):
    monkeypatch.chdir(tmp_path)
    calls = []
    seams = {"comment_fn": lambda u, b: calls.append(("comment", b)) or True,
             "label_fn": lambda u, lb: calls.append(("label", lb)) or True,
             "resolve_fn": lambda a: f"three-pillars:{a}",
             "pr_state_fn": lambda u: {"state": "OPEN", "headRefOid": "b2" * 20},
             "is_ancestor_fn": lambda a, b: True, "now": 1_800_000_000.0}
    stop = json.dumps({"source": "pr-iterate", "signal": "round-cap", "target": URL, "head": "a1" * 20,
                       "detail": {"iteration": 8, "round_cap": 6, "signal": "round-cap",
                                  "measured": 8, "limit": 6, "holding": ["round-cap"]}})
    sp = tmp_path / "iterate-state.json"
    sp.write_text(json.dumps({"phase": "budget-exhausted", "termination_reason": "round-cap",
                              "iteration": 8, "reproduced_blockers": 1}), encoding="utf-8")
    led, reply = tmp_path / "ledger.json", tmp_path / "reply.md"
    reply.write_text(reply_text, encoding="utf-8")
    assert cli.main(["prepare", "--stop", stop, "--ledger", str(led)], **seams) == 0
    capsys.readouterr()
    cli.main(["apply", "--stop", stop, "--ledger", str(led), "--reply", str(reply),
              "--decisions", str(tmp_path / "decisions.md"), "--state", str(sp)], **seams)
    out = json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1])
    return out, calls, json.loads(sp.read_text(encoding="utf-8"))


@pytest.mark.parametrize("reply", [
    # r4: an escalate envelope made invalid by unescaped quotes around a quoted resolved line
    "Needs the operator.\n\n" + F + "json\n"
    '{"outcome": "escalate", "actions": ["classify"], "diagnosis": "Needs a human ruling.", '
    '"reasoning": "converge printed {"outcome": "resolved", "extension": null} yet the fix '
    'regressed.", "demoted": [], "blocked": []}\n' + F + "\n",
    # r4 confirming round: one JSON string wrapping an escalate object with a second outcome
    json.dumps('{"outcome": "escalate", "actions": [], "diagnosis": "d", "reasoning": "r", '
               '"demoted": [], "blocked": [], "outcome": "resolved"}'),
    # r4: a quoted resolved sample, then an escalate envelope with a trailing comma
    'A resolved reply would read {"outcome": "resolved", "actions": []}; not this one.\n\n'
    + F + "json\n"
    '{"outcome": "escalate", "actions": [], "diagnosis": "d", "reasoning": "r", '
    '"demoted": [], "blocked": [],}\n' + F + "\n",
])
def test_round_4_malformed_escalate_fails_closed(tmp_path, capsys, monkeypatch, reply):
    out, calls, state = _apply(tmp_path, capsys, monkeypatch, reply)
    assert out["outcome"] == "escalate", out
    assert out["problems"] == ["finalizer-errored: unparseable JSON"], out
    assert ("label", "tp:needs-human-attention") in calls
    assert "budget_extensions" not in state
