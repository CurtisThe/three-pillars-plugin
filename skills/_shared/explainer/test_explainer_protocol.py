"""test_explainer_protocol.py — the protocol doc `skills/_shared/explainer.md`.

Covers explainer-agent plan Task 9.3 (detailed-design §Wiring: "a new protocol doc
`skills/_shared/explainer.md`"; plan Task 9.3 Red). `explainer.md` is the only place a
`tp-explainer` `Agent(` span may live (plan §Conventions, last bullet): its drafter span
takes `model=` from the `request` subcommand's own `drafter.model` output (never a literal
`sonnet`/`haiku`), and its check span is pinned to `model="opus"`. The doc also names the
`strata-spawn.md` busy `fallback` rule, `explain_engine.on_exhausted`, the one-rewrite rule,
the fail-open `||` guard, the Artifact-publish step before `record-artifact`, and a Refresh
and a Rulings section. Every `explain_cli.py <sub>` it cites is a real subcommand of the
parser, and the drafter/check spawn prompt carries the never-kill-by-name line.

`skill_spans` is dev-only (`pytest.importorskip`, as `test_role_engine_guard_spans.py`
does); `explainer.md` itself is read directly — it ships, and reading it is not reading
`three-pillars-docs/`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import explain_cli  # noqa: E402

DOC = _SHARED_DIR / "explainer.md"
SUB_CITE_RE = re.compile(r"explain_cli\.py\s+([a-z][a-z-]*)")


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _agent_spans(text: str) -> list[str]:
    skill_spans = pytest.importorskip("skill_spans")
    return [t for _, t in skill_spans.spans(text) if t.startswith("Agent(")]


def _subcommands() -> set[str]:
    parser = explain_cli.build_parser()
    action = next(a for a in parser._actions if getattr(a, "dest", None) == "cmd")
    return set(action.choices)


def test_a_drafter_span_names_tp_explainer_with_a_resolve_drafter_model_placeholder():
    text = _text()
    spans = _agent_spans(text)
    drafter_spans = [t for t in spans if "tp-explainer" in t and 'model="opus"' not in t]
    assert drafter_spans, f"no drafter Agent( span naming tp-explainer: {spans}"
    for t in drafter_spans:
        assert not re.search(r'model\s*=\s*"?(sonnet|haiku)\b', t, re.I), t
        assert "drafter.model" in t, t
    assert "resolve_drafter" in text


def test_a_check_span_is_pinned_to_opus():
    text = _text()
    spans = _agent_spans(text)
    check_spans = [t for t in spans if "tp-explainer" in t and 'model="opus"' in t]
    assert check_spans, f"no check Agent( span pinned to opus: {spans}"


def test_the_doc_has_both_a_drafter_and_a_check_span():
    """Non-vacuity: two distinct spans, not one span satisfying both greps."""
    spans = _agent_spans(_text())
    assert len(spans) >= 2, spans


def test_cites_strata_spawn_busy_fallback_rule():
    text = _text()
    assert "strata-spawn.md" in text
    assert re.search(r"busy.{0,200}fallback|fallback.{0,200}busy", text, re.I | re.S)


def test_cites_on_exhausted():
    assert "on_exhausted" in _text()


def test_cites_the_one_rewrite_rule():
    assert re.search(r"one[ -]rewrite", _text(), re.I)


def test_cites_the_fail_open_guard():
    assert "||" in _text()
    assert re.search(r"fail-open", _text(), re.I)


def test_artifact_publish_precedes_record_artifact():
    text = _text()
    assert "publish_artifact" in text
    artifact_idx = text.find("Artifact")
    record_idx = text.find("record-artifact")
    assert artifact_idx != -1 and record_idx != -1
    assert artifact_idx < record_idx


def test_has_a_refresh_and_a_rulings_section():
    text = _text()
    assert re.search(r"^#{1,4}\s*.*Refresh.*$", text, re.I | re.M)
    assert re.search(r"^#{1,4}\s*.*Rulings.*$", text, re.I | re.M)


def test_every_cited_subcommand_is_a_real_subcommand_of_the_parser():
    text = _text()
    cited = set(SUB_CITE_RE.findall(text))
    assert cited, "no explain_cli.py subcommand cited"
    real = _subcommands()
    unknown = cited - real
    assert unknown == set(), f"{unknown} not in the real subcommands {sorted(real)}"


def test_the_citations_are_not_vacuous():
    """At least the pipeline and the delivery sets each get one real citation."""
    cited = set(SUB_CITE_RE.findall(_text()))
    assert {"request", "gate", "finalize", "render"} & cited
    assert {"brief", "post", "rulings-sync", "record-artifact"} & cited


def test_the_spawn_prompt_carries_the_never_kill_by_name_line():
    text = _text()
    assert re.search(r"never kill processes by name or pattern", text, re.I)
    assert "pkill" in text and "killall" in text
