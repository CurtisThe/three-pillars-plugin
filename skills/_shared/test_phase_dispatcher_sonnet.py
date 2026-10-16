"""The phase dispatcher (`tp-worker`, Slot 7) runs on Sonnet; Opus only on a retry.

design: strata-spend-leaks (Task 2.1). Operator ruling: the Slot 7 phase dispatcher is
orchestration (it spawns `tp-task-worker` per task and returns the envelope), so it
defaults to Sonnet. The first dispatch names no `model` (the generated agent file's
`model: sonnet` applies); a retry re-dispatches the phase with `model="opus"` and logs
`phase-dispatch-escalated: opus`.

Each check reads the artifact as data (the policy table, the frontmatter through
`weight_class.parse_frontmatter`, the dispatch call as a balanced-paren span, the retry
section as the text between two `## ` headings), never a free-text grep of a whole doc.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import agent_variants  # noqa: E402
import model_policy  # noqa: E402
import skill_text  # noqa: E402
from weight_class import parse_frontmatter  # noqa: E402

ROOT = HERE.parents[1]
WORKER = ROOT / "agents" / "tp-worker.md"
SKILL = ROOT / "skills" / "tp-run-full-design" / "SKILL.md"
DISPATCH_OPEN = 'Agent(subagent_type=agent_ref("tp-worker")'


def _span_from(text: str, start: int) -> str:
    """The balanced-paren span that opens at `text[start:]`'s first `(`."""
    depth = 0
    for i in range(text.index("(", start), len(text)):
        depth += {"(": 1, ")": -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i + 1]
    raise AssertionError("unbalanced Agent( span")


def _section(text: str, heading: str) -> str:
    """The body of the `## heading` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\s*$", text, re.M)
    assert m, f"no '## {heading}' section"
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.end():m.end() + nxt.start()] if nxt else text[m.end():]


def test_tp_worker_policy_is_sonnet():
    spec = model_policy.agent_spec("tp-worker")
    assert spec == {"role": "phase-worker", "model": "sonnet", "effort": "high"}


def test_tp_worker_agent_file_is_sonnet():
    fm = parse_frontmatter(WORKER.read_text(encoding="utf-8"))
    assert fm.get("model") == "sonnet"
    assert agent_variants.check(ROOT) == [], "agent_variants.check: tp-worker.md drifted from the policy row"


def test_first_dispatch_names_no_model():
    text = skill_text.read_skill_text("tp-run-full-design")
    spans = [_span_from(text, m.start()) for m in re.finditer(re.escape(DISPATCH_OPEN), text)]
    assert spans, "no tp-worker dispatch span in tp-run-full-design/SKILL.md"
    for span in spans:
        assert 'isolation="worktree"' in span
        assert not re.search(r"\bmodel\s*=", span), f"re.search found a model= in the first dispatch: {span}"


def test_retry_redispatch_is_opus_and_logged():
    retry = _section(skill_text.read_skill_text("tp-run-full-design"), "Retry & max-attempts")
    assert "tp-worker" in retry
    # The re-dispatch clause itself: `re-dispatches `tp-worker` with `…``. Only that clause may
    # carry the Opus pin; the literal elsewhere in the section (a log line, a negation) is not
    # a re-dispatch on Opus.
    clause = re.search(r"re-dispatch\w*\s+`tp-worker`\s+with\s+(`[^`]*`)", retry)
    with_clause = clause.group(1) if clause else ""
    assert 'model="opus"' in with_clause, (
        f"no 'model=\"opus\"' in the re-dispatch with-clause: {retry[:160]!r}")
    assert "phase-dispatch-escalated: opus" in retry
