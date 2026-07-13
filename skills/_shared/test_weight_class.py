"""Tests for skills/_shared/weight_class.py — the design weight-class axis.

Covers Phase 1 of the design-depth-axis plan:
  1.1 frontmatter parsing + class enum
  1.2 read_class / write_class
  1.3 check_consistency (frontmatter-source guard, plan-audit F3)
  1.4 recommend_class rubric
  1.5 CLI entry points
  1.6 weight-class.md protocol doc content

Also hosts the consolidated SKILL.md surface assertions (Phases 2+).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from weight_class import (  # noqa: E402
    VALID_CLASSES,
    check_consistency,
    main,
    parse_frontmatter,
    read_class,
    recommend_class,
    write_class,
)

# ---------------------------------------------------------------------------
# 1.1 parse_frontmatter + VALID_CLASSES
# ---------------------------------------------------------------------------

def test_valid_classes():
    assert VALID_CLASSES == ("just-do-it", "light", "spike", "full")


def test_parse_frontmatter_present():
    text = "---\nweight-class: light\n---\n# My Design\n\nBody text.\n"
    assert parse_frontmatter(text) == {"weight-class": "light"}


def test_parse_frontmatter_extra_keys():
    text = "---\nweight-class: full\nstatus: draft\nowner: someone\n---\n# T\n"
    assert parse_frontmatter(text) == {
        "weight-class": "full",
        "status": "draft",
        "owner": "someone",
    }


def test_parse_frontmatter_absent():
    assert parse_frontmatter("# Just a heading\n\nNo frontmatter here.\n") == {}


def test_parse_frontmatter_empty_text():
    assert parse_frontmatter("") == {}


def test_parse_frontmatter_unclosed_fence():
    # Opening fence with no closing fence is malformed -> {}
    assert parse_frontmatter("---\nweight-class: light\n# heading\n") == {}


def test_parse_frontmatter_not_at_start():
    # A --- block later in the document is a horizontal rule, not frontmatter.
    text = "# Title\n\n---\nweight-class: light\n---\n"
    assert parse_frontmatter(text) == {}


def test_parse_frontmatter_malformed_lines_skipped():
    # Lines without "key: value" shape inside the block are skipped (partial dict).
    text = "---\nweight-class: spike\nnot a kv line\nother: ok\n---\n"
    assert parse_frontmatter(text) == {"weight-class": "spike", "other": "ok"}


def test_parse_frontmatter_never_raises_on_arbitrary_text():
    for junk in (
        "---",
        "---\n",
        "---\n---",
        "---\n---\n",
        ":\n:::\n",
        "\x00\x01binary\xff",
        "key: value",  # no fences at all
        "----\nweight-class: light\n----\n",
    ):
        result = parse_frontmatter(junk)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 1.2 read_class / write_class
# ---------------------------------------------------------------------------

def _design_dir(tmp_path, design_md: str | None) -> Path:
    d = tmp_path / "some-design"
    d.mkdir()
    if design_md is not None:
        (d / "design.md").write_text(design_md)
    return d


def test_read_class_from_frontmatter(tmp_path):
    d = _design_dir(tmp_path, "---\nweight-class: light\n---\n# D\n")
    assert read_class(d) == ("light", "frontmatter")


def test_read_class_all_valid_values(tmp_path):
    for klass in VALID_CLASSES:
        d = tmp_path / klass
        d.mkdir()
        (d / "design.md").write_text(f"---\nweight-class: {klass}\n---\n# D\n")
        assert read_class(d) == (klass, "frontmatter")


def test_read_class_no_design_md(tmp_path):
    d = _design_dir(tmp_path, None)
    assert read_class(d) == ("full", "default")


def test_read_class_no_frontmatter(tmp_path):
    d = _design_dir(tmp_path, "# Plain design\n\nNo block.\n")
    assert read_class(d) == ("full", "default")


def test_read_class_frontmatter_without_weight_class_key(tmp_path):
    d = _design_dir(tmp_path, "---\nstatus: draft\n---\n# D\n")
    assert read_class(d) == ("full", "default")


def test_read_class_unknown_value_fails_safe(tmp_path):
    d = _design_dir(tmp_path, "---\nweight-class: enormous\n---\n# D\n")
    assert read_class(d) == ("full", "default")


def test_write_class_inserts_block(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("# Plan\n\nTasks.\n")
    write_class(p, "light")
    assert p.read_text(encoding="utf-8").startswith("---\nweight-class: light\n---\n")
    assert "# Plan" in p.read_text(encoding="utf-8")


def test_write_class_updates_existing_value(tmp_path):
    p = tmp_path / "design.md"
    p.write_text("---\nweight-class: full\n---\n# D\n")
    write_class(p, "light")
    text = p.read_text(encoding="utf-8")
    assert parse_frontmatter(text)["weight-class"] == "light"
    assert text.count("weight-class:") == 1
    assert "# D" in text


def test_write_class_preserves_other_keys(tmp_path):
    p = tmp_path / "design.md"
    p.write_text("---\nstatus: draft\nowner: someone\n---\n# D\n")
    write_class(p, "spike")
    fm = parse_frontmatter(p.read_text(encoding="utf-8"))
    assert fm == {"status": "draft", "owner": "someone", "weight-class": "spike"}


def test_write_class_idempotent(tmp_path):
    p = tmp_path / "design.md"
    p.write_text("---\nstatus: draft\n---\n# D\n\nBody.\n")
    write_class(p, "light")
    first = p.read_text(encoding="utf-8")
    write_class(p, "light")
    assert p.read_text(encoding="utf-8") == first


def test_write_class_rejects_invalid_class(tmp_path):
    p = tmp_path / "design.md"
    p.write_text("# D\n")
    with pytest.raises(ValueError):
        write_class(p, "enormous")
    assert p.read_text(encoding="utf-8") == "# D\n"  # untouched on rejection


# ---------------------------------------------------------------------------
# 1.3 check_consistency
# ---------------------------------------------------------------------------

def _stamped(klass: str, title: str = "Doc") -> str:
    return f"---\nweight-class: {klass}\n---\n# {title}\n"


def test_check_consistency_all_matching(tmp_path):
    d = _design_dir(tmp_path, _stamped("light"))
    for sibling in ("seed.md", "detailed-design.md", "plan.md"):
        (d / sibling).write_text(_stamped("light"))
    assert check_consistency(d) == []


def test_check_consistency_divergent_sibling(tmp_path):
    d = _design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text(_stamped("full"))
    findings = check_consistency(d)
    assert len(findings) == 1
    assert "plan.md" in findings[0]
    assert "full" in findings[0] and "light" in findings[0]


def test_check_consistency_each_divergent_sibling_reported(tmp_path):
    d = _design_dir(tmp_path, _stamped("full"))
    (d / "seed.md").write_text(_stamped("light"))
    (d / "detailed-design.md").write_text(_stamped("spike"))
    (d / "plan.md").write_text(_stamped("full"))  # matching -> no finding
    findings = check_consistency(d)
    assert len(findings) == 2
    assert any("seed.md" in f for f in findings)
    assert any("detailed-design.md" in f for f in findings)


def test_check_consistency_missing_frontmatter_is_finding(tmp_path):
    # design.md declares a class -> a frontmatter-free sibling is a finding.
    d = _design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text("# Plan with no frontmatter\n")
    findings = check_consistency(d)
    assert len(findings) == 1
    assert "plan.md" in findings[0]


def test_check_consistency_missing_sibling_files_skipped(tmp_path):
    # Only design.md exists -> nothing to compare, zero findings.
    d = _design_dir(tmp_path, _stamped("full"))
    assert check_consistency(d) == []


def test_check_consistency_legacy_frontmatter_free_design(tmp_path):
    # Pinned legacy fixture (plan-audit F3): design.md without frontmatter
    # -> source == "default" -> vacuous pass even with divergent siblings.
    d = _design_dir(tmp_path, "# Legacy design, no frontmatter\n")
    (d / "plan.md").write_text(_stamped("light"))
    (d / "seed.md").write_text("# Legacy seed\n")
    assert check_consistency(d) == []


def test_check_consistency_legacy_design_md_absent(tmp_path):
    # Pinned legacy fixture (plan-audit F3): design.md entirely absent
    # -> source == "default" -> vacuous pass.
    d = _design_dir(tmp_path, None)
    (d / "plan.md").write_text(_stamped("light"))
    assert check_consistency(d) == []


def test_check_consistency_invalid_design_class_vacuous(tmp_path):
    # Invalid value -> read_class falls back to default -> vacuous pass.
    d = _design_dir(tmp_path, _stamped("enormous"))
    (d / "plan.md").write_text(_stamped("light"))
    assert check_consistency(d) == []


# ---------------------------------------------------------------------------
# 1.4 recommend_class rubric
# ---------------------------------------------------------------------------
# Axes: risk, blast_radius, reversibility, novelty — each low|medium|high.
# Reversibility is inverted: high reversibility is GOOD (minimal concern).

def test_recommend_class_all_minimal_is_just_do_it():
    klass, why = recommend_class("low", "low", "high", "low")
    assert klass == "just-do-it"
    assert why  # non-empty justification


def test_recommend_class_novelty_high_is_spike():
    klass, why = recommend_class("low", "low", "high", "high")
    assert klass == "spike"
    assert "novelty" in why


def test_recommend_class_one_medium_is_light():
    klass, why = recommend_class("medium", "low", "high", "low")
    assert klass == "light"
    assert "risk" in why


def test_recommend_class_medium_reversibility_is_light():
    klass, why = recommend_class("low", "low", "medium", "low")
    assert klass == "light"
    assert "reversibility" in why


def test_recommend_class_two_mediums_is_full():
    klass, _ = recommend_class("medium", "medium", "high", "low")
    assert klass == "full"


def test_recommend_class_high_risk_is_full():
    klass, why = recommend_class("high", "low", "high", "low")
    assert klass == "full"
    assert "risk" in why


def test_recommend_class_high_blast_radius_is_full():
    klass, why = recommend_class("low", "high", "high", "low")
    assert klass == "full"
    assert "blast" in why


def test_recommend_class_low_reversibility_is_full():
    # Hard to reverse = high concern -> full.
    klass, why = recommend_class("low", "low", "low", "low")
    assert klass == "full"
    assert "reversibility" in why


def test_recommend_class_medium_novelty_counts_as_medium():
    # novelty medium + risk medium -> two medium axes -> full (>1 medium escalates
    # past light; the "ambiguity resolves heavier" rule itself is pinned by
    # test_recommend_class_unknown_axis_value_is_full).
    klass, _ = recommend_class("medium", "low", "high", "medium")
    assert klass == "full"


def test_recommend_class_one_medium_plus_one_high_is_full():
    klass, _ = recommend_class("medium", "high", "high", "low")
    assert klass == "full"


def test_recommend_class_unknown_axis_value_is_full():
    for args in (
        ("banana", "low", "high", "low"),
        ("low", "", "high", "low"),
        ("low", "low", None, "low"),
        ("low", "low", "high", "LOWISH"),
    ):
        klass, _ = recommend_class(*args)
        assert klass == "full"


def test_recommend_class_every_class_reachable():
    reached = {
        recommend_class("low", "low", "high", "low")[0],
        recommend_class("low", "low", "high", "high")[0],
        recommend_class("medium", "low", "high", "low")[0],
        recommend_class("high", "high", "low", "low")[0],
    }
    assert reached == set(VALID_CLASSES)


# ---------------------------------------------------------------------------
# 1.5 CLI entry points
# ---------------------------------------------------------------------------

def test_cli_recommend(capsys):
    rc = main([
        "recommend",
        "--risk", "low",
        "--blast-radius", "low",
        "--reversibility", "high",
        "--novelty", "high",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "spike" in out
    assert "novelty" in out


def test_cli_read(tmp_path, capsys):
    d = _design_dir(tmp_path, _stamped("light"))
    rc = main(["read", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "light" in out
    assert "frontmatter" in out


def test_cli_read_default(tmp_path, capsys):
    d = _design_dir(tmp_path, "# No frontmatter\n")
    rc = main(["read", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "full" in out
    assert "default" in out


def test_cli_check_clean_exits_zero(tmp_path):
    d = _design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text(_stamped("light"))
    assert main(["check", str(d)]) == 0


def test_cli_check_findings_exit_one(tmp_path, capsys):
    d = _design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text(_stamped("full"))
    rc = main(["check", str(d)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "plan.md" in out


def test_cli_check_runs_against_real_dir():
    import subprocess

    here = Path(__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, str(here / "weight_class.py"), "check", str(here.parent.parent)],
        capture_output=True,
        text=True,
    )
    # Repo root has no design.md -> vacuous pass, exit 0, no crash.
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# 1.6 weight-class.md protocol doc
# ---------------------------------------------------------------------------
# These test_protocol_doc_* tests cover the Task 1.6 content only; the light
# fidelity checklist section lands in Task 4.1 with its own test
# (test_protocol_doc_fidelity — plan-audit boundary note).

_PROTOCOL_DOC = Path(__file__).resolve().parent / "weight-class.md"


def _doc_text() -> str:
    return _PROTOCOL_DOC.read_text(encoding="utf-8")


def test_protocol_doc_exists():
    assert _PROTOCOL_DOC.is_file()


def test_protocol_doc_names_all_four_classes():
    text = _doc_text()
    for klass in VALID_CLASSES:
        assert f"`{klass}`" in text


def test_protocol_doc_ceremony_table():
    text = _doc_text()
    # Per-check-level ceremony table: the four check levels appear as a
    # markdown table alongside the classes.
    assert "| Check level" in text or "| Check-level" in text
    for level in ("design-level", "plan-level", "impl-level"):
        assert level in text


def test_protocol_doc_rubric_axes():
    text = _doc_text()
    for axis in ("risk", "blast radius", "reversibility", "novelty"):
        assert axis in text.lower()
    assert "weight_class.py" in text  # points at the executable rubric


def test_protocol_doc_frontmatter_schema_example():
    text = _doc_text()
    assert "weight-class:" in text
    assert "---" in text
    assert "design.md" in text  # names the authoritative artifact


def test_protocol_doc_escalation_rule():
    text = _doc_text()
    assert "escalate" in text.lower()
    assert "de-escalat" in text.lower()  # never de-escalate


def test_protocol_doc_fidelity():
    """Task 4.1 — Light fidelity checklist section in weight-class.md."""
    text = _doc_text()
    assert "Light fidelity checklist" in text
    section = text.split("Light fidelity checklist")[1].split("\n## ")[0]
    # Every in-scope item of the collapsed note traced to the diff.
    assert "in-scope" in section.lower()
    assert "diff" in section.lower()
    assert "trace" in section.lower()
    # Drift flagged.
    assert "drift" in section.lower()
    # Phrased for direct inclusion in a code-review prompt / PR body.
    assert "code-review" in section.lower() or "code review" in section.lower()
    assert "PR body" in section


def test_protocol_doc_composition_contract():
    text = _doc_text()
    assert "Composition" in text
    assert "slice" in text
    assert "orchestrator-pipeline-modes" in text


# ---------------------------------------------------------------------------
# Phase 6 — live-repo integration stamps
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_self_stamp():
    """Task 6.1 — this design's own artifacts carry weight-class: full."""
    design_dir = _REPO_ROOT / "three-pillars-docs" / "tp-designs" / "design-depth-axis"
    if not (design_dir / "design.md").exists():
        pytest.skip("design-depth-axis dir absent (archived or different checkout)")
    assert read_class(design_dir) == ("full", "frontmatter")
    assert check_consistency(design_dir) == []


def test_dogfood_seed():
    """Task 6.2 — the file-size-limits seed is classified light for the dogfood."""
    seed = _REPO_ROOT / "three-pillars-docs" / "tp-designs" / "file-size-limits" / "seed.md"
    if not seed.exists():
        pytest.skip("file-size-limits seed absent (archived or different checkout)")
    assert parse_frontmatter(seed.read_text(encoding="utf-8")).get("weight-class") == "light"


# ---------------------------------------------------------------------------
# Consolidated SKILL.md surface assertions (Phase 2)
# ---------------------------------------------------------------------------

_SKILLS_ROOT = Path(__file__).resolve().parent.parent


def _skill_text(skill: str) -> str:
    return (_SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")


def test_surface_tp_design():
    """Task 2.2 — class declaration step + light collapsed mode in tp-design."""
    text = _skill_text("tp-design")
    # Class-declaration step: read seed frontmatter, else ask once, rubric-assisted.
    assert "weight class" in text.lower()
    assert "seed.md" in text
    assert "frontmatter" in text.lower()
    assert "recommend" in text.lower()  # rubric-assisted
    assert "weight_class.py" in text or "weight-class.md" in text
    # Frontmatter stamp in the design.md-writing step.
    assert "weight-class:" in text
    # Light-mode branch: same sitting produces thin plan.md; skip detail + plan.
    assert "thin plan.md" in text
    assert "skip" in text.lower()
    assert "/tp-design-detail" in text and "/tp-plan" in text
    # F4: collapsed design.md must keep all floor-required ## sections,
    # naming the gate it must still pass.
    assert "floor-required" in text
    assert "validate_design_floor.py" in text


def test_surface_claude_md():
    """Task 2.5 — CLAUDE.md + CLAUDE.plugin.md use the four-class taxonomy."""
    for name in ("CLAUDE.md", "CLAUDE.plugin.md"):
        text = (_SKILLS_ROOT.parent / name).read_text(encoding="utf-8")
        assert "just do it, spike, or full design" not in text, (
            f"{name} still carries the bare three-approach phrase"
        )
        for klass in ("just-do-it", "light", "spike", "full"):
            assert klass in text, f"{name} must name the {klass!r} class"


def test_surface_plan_audit():
    """Task 3.4 — --light docs + merged conceptual+plan council pass (F6)."""
    import re as _re

    text = _skill_text("tp-plan-audit")
    # --light documented; prerequisites need design.md + plan.md only.
    assert "`--light`" in text
    prereqs = text.split("## Prerequisites")[1].split("##")[0]
    assert "--light" in prereqs, "Prerequisites must exempt detailed-design.md under --light"
    # Merged council pass: same triad, single round, short-circuit rule reused.
    assert "Light mode prompts" in text
    light_block = text.split("Light mode prompts")[1].split("### Step")[0]
    for member in ("council-torvalds", "council-ada", "council-feynman"):
        assert member in light_block, f"light pass keeps the {member} triad"
    assert "single round" in light_block.lower()
    assert "short-circuit" in light_block.lower(), (
        "light pass reuses the Round-2 short-circuit rule"
    )
    # F6: two distinct, separately numbered question groups — conceptual-design
    # and plan — present as separate sets, not an undifferentiated blob.
    assert "Conceptual-design questions" in light_block
    assert "Plan questions" in light_block
    conceptual = _re.findall(r"^C\d+\.", light_block, _re.MULTILINE)
    plan_qs = _re.findall(r"^P\d+\.", light_block, _re.MULTILINE)
    assert len(conceptual) >= 3, "conceptual group has its own numbered questions"
    assert len(plan_qs) >= 3, "plan group has its own numbered questions"
    conceptual_text = light_block.split("Conceptual-design questions")[1].split("Plan questions")[0]
    plan_text = light_block.split("Plan questions")[1]
    assert "vision" in conceptual_text.lower() and "scope" in conceptual_text.lower()
    for topic in ("coverage", "ordering", "buildab"):
        assert topic in plan_text.lower(), f"plan group must cover {topic}"


def test_surface_propagation():
    """Task 2.4 — tp-design-detail and tp-plan stamp their artifacts from design.md."""
    for skill in ("tp-design-detail", "tp-plan"):
        text = _skill_text(skill)
        assert "weight-class" in text, f"{skill} must stamp weight-class frontmatter"
        assert "design.md" in text
        assert "write_class" in text or "frontmatter" in text.lower(), (
            f"{skill}'s artifact-writing step must instruct the frontmatter stamp"
        )
        assert "stamp" in text.lower(), (
            f"{skill} must carry design.md's weight-class onto its artifact"
        )
