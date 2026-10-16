"""The finalizer's grounding and exact reply keys (PR #188, operator rulings 2026-09-30).

design: fable-first-stops. The agent file's ## Grounding list is pinned to
`finalizer_outcome.GROUNDING_DOCS`; a `resolved` must cite a grounding doc in `reasoning`
(a substring match); the brief lists only the docs this repo has (the consumer-repo rule);
the reply carries exactly the documented keys. Also: a BOM-prefixed reply and an unreadable
config after `prepare` both fail closed without a crash.
Run with: python3 -m pytest skills/_shared/test_finalizer_grounding.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import finalizer as fin  # noqa: E402
import finalizer_cli as cli  # noqa: E402
import finalizer_outcome as fo  # noqa: E402
import finalizer_ruling as fr  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
URL = "https://github.com/acme/widgets/pull/42"


def _reply(**kw) -> dict:
    return {"outcome": "resolved", "actions": ["fix"], "diagnosis": "d",
            "reasoning": "Kept the run moving per vision.md.", "demoted": [], "blocked": [],
            **fr.EMPTY_RULING, **kw}


def _grounding_section() -> str:
    agent = (REPO_ROOT / "agents" / "tp-finalizer.md").read_text(encoding="utf-8")
    return agent[agent.index("## Grounding"):agent.index("## Reply envelope")]


def test_agent_file_grounding_list_is_pinned_to_the_constant():
    listed = re.findall(r"^- `(three-pillars-docs/[^`]+)`", _grounding_section(), re.M)
    assert listed == list(fo.GROUNDING_DOCS)
    for name in fo.DESIGN_DOCS:
        assert f"`{name}`" in _grounding_section(), name


@pytest.mark.parametrize("reasoning", [
    "Per vision.md (fleet operation).", "three-pillars-docs/product_roadmap.md Current Focus.",
    "architecture.md: the loop is dual-source.", "known_issues.md L147.",
    "specs/pr-iterate.md budget rules.", "design.md scope.", "Operator ruling in decisions.md.",
])
def test_a_cited_resolved_resolves(reasoning):
    result = fo.validate(_reply(reasoning=reasoning))
    assert result["outcome"] == "resolved" and result["problems"] == [], result


@pytest.mark.parametrize("reasoning", ["", "Fixed the flaky test; pytest: 412 passed.",
                                       "Per the vision and the roadmap."])
def test_an_uncited_resolved_escalates(reasoning):
    result = fo.validate(_reply(reasoning=reasoning))
    assert result["outcome"] == "escalate"
    assert any(p.startswith("ungrounded:") for p in result["problems"]), result


def test_an_uncited_escalate_needs_no_citation():
    result = fo.validate(_reply(outcome="escalate", reasoning="Needs a human ruling."))
    assert result["outcome"] == "escalate"
    assert not any(p.startswith("ungrounded:") for p in result["problems"]), result


def test_a_partial_object_escalates():
    result = fo.validate({"outcome": "resolved", "reasoning": "vision.md"})
    assert result["outcome"] == "escalate"
    assert any(p.startswith("finalizer-errored: missing keys "
                            "['actions', 'diagnosis', 'demoted', 'blocked'")
               for p in result["problems"]), result


def test_an_extra_key_escalates():
    result = fo.validate(_reply(extension={"to": 99}))
    assert result["outcome"] == "escalate"
    assert "finalizer-errored: unexpected keys ['extension']" in result["problems"], result


def test_brief_lists_only_the_grounding_docs_this_repo_has(tmp_path):
    (tmp_path / "three-pillars-docs" / "tp-designs" / "demo").mkdir(parents=True)
    (tmp_path / "three-pillars-docs" / "vision.md").write_text("v", encoding="utf-8")
    decisions = tmp_path / "three-pillars-docs" / "tp-designs" / "demo" / "decisions.md"
    decisions.write_text("d", encoding="utf-8")
    brief = fin._brief({"source": "audit-gate", "signal": "plan", "target": "demo"}, "k",
                       decisions, tmp_path)
    assert "- three-pillars-docs/vision.md" in brief
    assert "- three-pillars-docs/tp-designs/demo/decisions.md" in brief
    for missing in ("product_roadmap.md", "architecture.md", "known_issues.md", "specs/",
                    "demo/design.md"):
        assert missing not in brief, missing


def test_brief_in_a_repo_with_no_grounding_docs_still_builds(tmp_path):
    brief = fin._brief({"source": "audit-gate", "signal": "plan", "target": "demo"}, "k",
                       tmp_path / "decisions.md", tmp_path)
    assert "Grounding (read before ruling" in brief and "- (none found)" in brief


def _apply(tmp_path, capsys, monkeypatch, reply_bytes, *more, keep_state=False):
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
    if not keep_state:
        sp.write_text(json.dumps({"phase": "budget-exhausted", "termination_reason": "round-cap",
                                  "iteration": 8, "reproduced_blockers": 1}), encoding="utf-8")
    led, reply = tmp_path / "ledger.json", tmp_path / "reply.md"
    reply.write_bytes(reply_bytes)
    assert cli.main(["prepare", "--stop", stop, "--ledger", str(led)], **seams) == 0
    capsys.readouterr()
    rc = cli.main(["apply", "--stop", stop, "--ledger", str(led), "--reply", str(reply),
                   "--decisions", str(tmp_path / "decisions.md"), "--state", str(sp), *more], **seams)
    out = json.loads([ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1])
    return rc, out, calls, json.loads(led.read_text(encoding="utf-8"))


def test_a_bom_prefixed_reply_is_read_as_its_envelope(tmp_path, capsys, monkeypatch):
    rc, out, _, _ = _apply(tmp_path, capsys, monkeypatch,
                           "﻿".encode() + json.dumps(_reply()).encode())
    assert rc == 0 and out["outcome"] == "resolved", out


def test_an_unreadable_config_after_prepare_escalates_and_clears_the_marker(tmp_path, capsys,
                                                                          monkeypatch):
    bad = tmp_path / "config.json"
    bad.write_text("{not json", encoding="utf-8")
    rc, out, calls, ledger = _apply(tmp_path, capsys, monkeypatch, json.dumps(_reply()).encode(),
                                    "--config", str(bad))
    assert rc == 0 and out["outcome"] == "escalate", out
    assert "config-unreadable" in out["problems"], out
    assert ("label", "tp:needs-human-attention") in calls
    assert ledger["in_flight"] is None


def test_resolved_on_a_spent_extension_escalates_instead_of_a_hollow_note(tmp_path, capsys,
                                                                          monkeypatch):
    # PR #188 r7: the state already carries this signal's one grant (e.g. a ledger at another
    # path never saw the key), so a resolved could lift nothing; it must escalate, not post
    # "resolved" with extension null and leave the sticky terminal to a silent held label.
    state = {"phase": "budget-exhausted", "termination_reason": "round-cap", "iteration": 8,
             "reproduced_blockers": 1,
             "budget_extensions": {"round-cap": {"limit": 8, "key": "k", "at": "t"}}}
    monkeypatch.chdir(tmp_path)
    (tmp_path / "iterate-state.json").write_text(json.dumps(state), encoding="utf-8")
    rc, out, calls, ledger = _apply(tmp_path, capsys, monkeypatch, json.dumps(_reply()).encode(),
                                    keep_state=True)
    assert rc == 0 and out["outcome"] == "escalate", out
    assert "extension-spent" in out["problems"], out
    assert ("label", "tp:needs-human-attention") in calls
    assert not any(kind == "comment" and "resolved" in body.split("\n")[0].lower()
                   for kind, body in calls), calls
    assert ledger["in_flight"] is None
