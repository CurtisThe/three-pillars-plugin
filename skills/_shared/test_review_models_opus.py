"""Guard: reviews and audits always run on Opus (operator ruling 2026-09-23).

Every council persona and the read-only auditor declare `model: opus`, and the
review/audit dispatch sites pin `model="opus"` (or, for the pr-iterate angle
fan-out, the manifest's `dispatch_model`) instead of inheriting a default. The
one allow-listed exception is the borderline comment classifier — `model_policy`'s
`classifier` role (default `sonnet`) in tp-pr-fix §3 / tp-pr-iterate step 5 — which
classifies existing comments rather than reviewing code — an open question on the
`reviews-always-opus` seed.

Since `local-role-routing`, every *judgment* is Opus (council synth, gate roles,
finalizer fallback, certifier, the opus-check confirmer); Strata (local) is
allow-listed only for the member, finder and scout roles via the `role_engines`
config block (`model_policy.ENGINE_ROLES`). That allow-list is guarded by
`test_role_engine_guard.py` and `test_role_engine_guard_spans.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import skill_text

ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS = sorted((ROOT / "agents").glob("council-*.md")) + [
    ROOT / "agents" / "tp-readonly-auditor.md", ROOT / "agents" / "tp-certifier.md"]
CLASSIFIER_ALLOW = {"skills/tp-pr-fix/SKILL.md", "skills/tp-pr-iterate/SKILL.md"}


def _model(path: Path) -> str | None:
    m = re.search(r"^model:\s*(\S+)", path.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else None


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_review_agents_declare_opus(path):
    assert _model(path) == "opus", f"{path.name} must declare model: opus"


def test_phase_checker_frontmatter_opus_medium():
    """review-convergence 8.2: the per-phase check judge is pinned opus, effort medium."""
    text = (ROOT / "agents" / "tp-phase-checker.md").read_text(encoding="utf-8")
    assert re.search(r"^model:\s*opus\s*$", text, flags=re.M)
    assert re.search(r"^effort:\s*medium\s*$", text, flags=re.M)


def test_review_policy_defaults_pin_opus():
    """The policy lives in model_policy (the registry the dispatch sites read), not in SKILL.md wording."""
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "_shared"))
    import model_policy  # noqa: E402

    assert model_policy.DEFAULTS["review"] == "opus"


def test_review_skill_references_resolve():
    """Deleted prose pins were references; skill_refs (invariant 46) covers them."""
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "_shared"))
    skill_refs = pytest.importorskip("skill_refs")

    paths = []
    for s in ("council", "tp-pr-iterate", "tp-run-full-design", "tp-design-audit"):
        paths += (skill_text.skill_paths(s) if s == "tp-run-full-design" else [ROOT / "skills" / s / "SKILL.md"])
    report = skill_refs.check(ROOT, paths)
    assert not report.issues, report.issues


def test_pr_iterate_angles_module_pins_opus():
    """The angles-as-data module: every default angle is Opus; no Sonnet/Haiku literal."""
    path = ROOT / "skills" / "tp-pr-iterate" / "scripts" / "angles.py"
    text = path.read_text(encoding="utf-8")
    block = text[text.index("DEFAULT_ANGLES = ["):text.index("def tier(")]
    assert block.count('"model": "opus"') == block.count('"model":') >= 3
    assert "claude-sonnet" not in text and '"model": "sonnet"' not in text
    assert '"model": "haiku"' not in text


def test_security_angle_is_opus():
    """The security lens is a Claude confirmer on Opus, never a cheap finder (review-convergence 4.1)."""
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "tp-pr-iterate" / "scripts"))
    angles = pytest.importorskip("angles")

    entry = angles.security_angle(Path("b.md"), [{"surface": "credentials", "path": "a.py"}])
    assert entry["model"] == "opus"


def _agent_spans(skill: Path) -> list[tuple[int, str]]:
    import sys
    sys.path.insert(0, str(ROOT / "skills" / "_shared"))
    skill_spans = pytest.importorskip("skill_spans")

    return [(n, t) for n, t in skill_spans.spans(skill.read_text(encoding="utf-8")) if t.startswith("Agent(")]


def test_design_audit_agent_launches_run_on_opus():
    """Operator policy guard: reviews always Opus. Every `Agent(...)` span in the
    design-audit SKILL.md either carries model="opus" or names an agent whose
    frontmatter declares `model: opus`."""
    skill = ROOT / "skills" / "tp-design-audit" / "SKILL.md"
    found = _agent_spans(skill)
    assert sum('"general-purpose"' in t for _, t in found) >= 3, found  # explorer launches stay spans
    for line, text in found:
        named = re.search(r'agent_ref\("([\w-]+)"\)', text)
        declared = named and (ROOT / "agents" / f"{named.group(1)}.md").is_file() \
            and _model(ROOT / "agents" / f"{named.group(1)}.md") == "opus"
        assert declared or re.search(r'model\s*[=:]\s*"?opus', text), f"{skill.name}:{line} {text}"
