"""Pins for the certifier agent definition and its single prose source.

The certifier authors RED/GREEN records that try to break a guard claim. That
judging work is pinned to Opus at extra-high effort in the agent's own
frontmatter, so it never inherits a session's model or effort. The contract it
follows lives in `skills/_shared/certification-protocol.md` and nowhere else.
"""
# pin-source: skills/tp-implementation-audit/SKILL.md
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
AGENT = ROOT / "agents" / "tp-certifier.md"
PROTOCOL = ROOT / "skills" / "_shared" / "certification-protocol.md"


def _frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} has no frontmatter"
    return text.split("---\n", 2)[1]


def _field(front: str, key: str) -> str | None:
    m = re.search(rf"^{key}:\s*(.+)$", front, flags=re.M)
    return m.group(1).strip() if m else None


def test_agent_frontmatter_pins():
    front = _frontmatter(AGENT)
    assert _field(front, "name") == "tp-certifier"
    assert _field(front, "model") == "opus"
    assert _field(front, "effort") == "xhigh"
    assert _field(front, "color"), "tp-certifier.md needs a color"
    assert json.loads(_field(front, "tools")) == ["Read", "Edit", "Write", "Grep", "Glob", "Bash"]


def test_agent_never_names_sonnet():
    assert "sonnet" not in AGENT.read_text(encoding="utf-8").lower()


def test_agent_body_cites_scope_and_protocol():
    body = AGENT.read_text(encoding="utf-8").split("---\n", 2)[2]
    assert "agents/_shared/project-scope.md" in body
    assert "skills/_shared/certification-protocol.md" in body


def test_plugin_lists_certifier():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "./agents/tp-certifier.md" in plugin["agents"]


# ---------------------------------------------------------------------------
# The claim keys every claim-writing surface asks for, and the certifier's allowlist
# ---------------------------------------------------------------------------
CLAIM_SURFACES = ("tp-design-audit", "tp-implementation-audit", "tp-phase-review")


def _claim_shapes(text: str) -> list[set[str]]:
    """The key sets of every backticked `{...}` claim shape (one naming `guard`)."""
    shapes = [{k.strip() for k in body.split(",")} for body in re.findall(r"`\{([^`}]*)\}`", text)]
    return [s for s in shapes if "guard" in s]


def _ticked(text: str) -> set[str]:
    return set(re.findall(r"`([^`\s]+)`", text))


@pytest.mark.parametrize("skill", CLAIM_SURFACES)
def test_a_claim_writing_surface_asks_for_every_claim_key(skill):
    """Each surface names the claim shape `certify_record` validates, `subjects` included:
    a claim written without `subjects` certifies nothing (`no-subjects`)."""
    import certify_record
    keys = set(certify_record.CLAIM_KEYS) | set(certify_record.CLAIM_OPTIONAL)
    shapes = _claim_shapes((ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
    assert shapes and all(shape == keys for shape in shapes), (skill, shapes)


def test_the_certifier_is_told_its_allowlist_keys():
    """The agent names the claim's allowlist key and the pole keys it must not write for a
    pytest guard (`argv`, `expect.exit`: `pytest-argv-supplied` / `pytest-exit-supplied`)."""
    import certify_record
    keys = set(certify_record.CLAIM_OPTIONAL) | {"argv", "expect.exit"}
    assert keys <= _ticked(AGENT.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# certification-protocol.md — the single prose source (Task 6.2, N5)
# ---------------------------------------------------------------------------


def _protocol() -> str:
    return PROTOCOL.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_protocol_shapes():
    import certify_record
    text = _protocol()
    assert set(certify_record.CLAIM_KEYS) in _claim_shapes(text), "the claim shape's keys"
    for needle in ('"disposition"', "parameters_added", "varied", "output_contains"):
        assert needle in text, needle
    for op in ("replace", "write", "delete"):
        assert re.search(rf'"op":\s*"{op}"', text), op


def test_protocol_certifier_contract():
    body = _section(_protocol(), "Certifier contract")
    for needle in ("MAX_REPAIRS", "3", "near-miss RED", "near-miss GREEN",
                   "markers are chosen before any run", "records_file", "sha256",
                   "never commits", "status is certify.py's", "terminal",
                   "fenced as untrusted data", "certifier-return.v1.json"):
        assert needle in body, needle


def test_protocol_dry_run_terminal_rule():
    body = _section(_protocol(), "Certifier contract")
    assert "`not-binding` or `false-red`" in body
    assert "`red-without-marker`" in body


def test_protocol_tags_verdicts_and_three_outcome_rule():
    text = _protocol()
    assert "[cert:<id>]" in text and "## Guards certified" in text and "No guard claims." in text
    from auto_verdict import VERDICT_ORDER
    order = r"[^\n]*?".join(re.escape(v) for v in reversed(VERDICT_ORDER))  # one line
    assert re.search(order, text), "the verdict total order, highest first"
    rule = _section(text, "Three-outcome checker rule")
    for needle in ("holds", "violated", "could not evaluate"):
        assert needle in rule, needle


def test_protocol_step_2b():
    body = _section(_protocol(), "Step 2b")
    for needle in ('"$CERT" claimant-check', "certifications/records/", '"$CERT" handoff',
                   "--unverified records-handoff",
                   '"$CERT" run', '"$CERT" fold', "issues apply", "certification-unverified"):
        assert needle in body, needle


def test_protocol_shipped_surface_hygiene():
    text = _protocol()
    assert not re.search(r"\bM\d+\b", text), "no known-issue ids in shipped prose"
    assert not re.search(r"#\d", text), "no invariant number cites in shipped prose"
    assert not re.search(r"(python3|bash)\s+skills/", text), "use the resolve form"
    from file_size_guard import LINE_CAPS
    assert len(text.splitlines()) <= LINE_CAPS["markdown"][0], "within the markdown soft cap"
