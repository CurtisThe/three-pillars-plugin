"""Tests for skills/_shared/weight_class.py — the design weight-class axis.

Covers Phase 1 of the design-depth-axis plan:
  1.1 frontmatter parsing + class enum
  1.2 read_class / write_class
  1.3 check_consistency (frontmatter-source guard, plan-audit F3)
  1.4 recommend_class rubric
  1.5 CLI entry points
  1.6 weight-class.md protocol doc exists

The SKILL.md and protocol-doc surfaces are checked as parsed structures in
test_weight_class_contracts.py, never as prose here.
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
    write_class,
)

_DEV_ROOT = Path(__file__).resolve().parents[2]
_needs_claude_plugin_md = pytest.mark.skipif(
    not (_DEV_ROOT / "CLAUDE.plugin.md").exists(),
    reason="reads CLAUDE.plugin.md, which never ships (dev-repo only)")

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

def _tmp_design_dir(tmp_path, design_md: str | None) -> Path:
    d = tmp_path / "some-design"
    d.mkdir()
    if design_md is not None:
        (d / "design.md").write_text(design_md)
    return d


def test_read_class_from_frontmatter(tmp_path):
    d = _tmp_design_dir(tmp_path, "---\nweight-class: light\n---\n# D\n")
    assert read_class(d) == ("light", "frontmatter")


def test_read_class_all_valid_values(tmp_path):
    for klass in VALID_CLASSES:
        d = tmp_path / klass
        d.mkdir()
        (d / "design.md").write_text(f"---\nweight-class: {klass}\n---\n# D\n")
        assert read_class(d) == (klass, "frontmatter")


def test_read_class_no_design_md(tmp_path):
    d = _tmp_design_dir(tmp_path, None)
    assert read_class(d) == ("full", "default")


def test_read_class_no_frontmatter(tmp_path):
    d = _tmp_design_dir(tmp_path, "# Plain design\n\nNo block.\n")
    assert read_class(d) == ("full", "default")


def test_read_class_frontmatter_without_weight_class_key(tmp_path):
    d = _tmp_design_dir(tmp_path, "---\nstatus: draft\n---\n# D\n")
    assert read_class(d) == ("full", "default")


def test_read_class_unknown_value_fails_safe(tmp_path):
    d = _tmp_design_dir(tmp_path, "---\nweight-class: enormous\n---\n# D\n")
    assert read_class(d) == ("full", "default")


def test_write_class_inserts_block(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text("# Plan\n\nTasks.\n")
    write_class(p, "light")
    # tp-allow-fragile: reads the file write_class just wrote from a system-built input; the leading block it emits is its contract
    assert p.read_text(encoding="utf-8").startswith("---\nweight-class: light\n---\n")
    # tp-allow-fragile: reads the file write_class just wrote from a system-built input; preserving the body is its contract
    assert "# Plan" in p.read_text(encoding="utf-8")


def test_write_class_updates_existing_value(tmp_path):
    p = tmp_path / "design.md"
    p.write_text("---\nweight-class: full\n---\n# D\n")
    write_class(p, "light")
    text = p.read_text(encoding="utf-8")
    assert parse_frontmatter(text)["weight-class"] == "light"
    assert text.count("weight-class:") == 1
    # tp-allow-fragile: reads the file write_class just wrote from a system-built input; preserving the body is its contract
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
    d = _tmp_design_dir(tmp_path, _stamped("light"))
    for sibling in ("seed.md", "detailed-design.md", "plan.md"):
        (d / sibling).write_text(_stamped("light"))
    assert check_consistency(d) == []


def test_check_consistency_divergent_sibling(tmp_path):
    d = _tmp_design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text(_stamped("full"))
    findings = check_consistency(d)
    assert len(findings) == 1
    assert "plan.md" in findings[0]
    assert "full" in findings[0] and "light" in findings[0]


def test_check_consistency_each_divergent_sibling_reported(tmp_path):
    d = _tmp_design_dir(tmp_path, _stamped("full"))
    (d / "seed.md").write_text(_stamped("light"))
    (d / "detailed-design.md").write_text(_stamped("spike"))
    (d / "plan.md").write_text(_stamped("full"))  # matching -> no finding
    findings = check_consistency(d)
    assert len(findings) == 2
    assert any("seed.md" in f for f in findings)
    assert any("detailed-design.md" in f for f in findings)


def test_check_consistency_missing_frontmatter_is_finding(tmp_path):
    # design.md declares a class -> a frontmatter-free sibling is a finding.
    d = _tmp_design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text("# Plan with no frontmatter\n")
    findings = check_consistency(d)
    assert len(findings) == 1
    assert "plan.md" in findings[0]


def test_check_consistency_missing_sibling_files_skipped(tmp_path):
    # Only design.md exists -> nothing to compare, zero findings.
    d = _tmp_design_dir(tmp_path, _stamped("full"))
    assert check_consistency(d) == []


def test_check_consistency_legacy_frontmatter_free_design(tmp_path):
    # Pinned legacy fixture (plan-audit F3): design.md without frontmatter
    # -> source == "default" -> vacuous pass even with divergent siblings.
    d = _tmp_design_dir(tmp_path, "# Legacy design, no frontmatter\n")
    (d / "plan.md").write_text(_stamped("light"))
    (d / "seed.md").write_text("# Legacy seed\n")
    assert check_consistency(d) == []


def test_check_consistency_legacy_design_md_absent(tmp_path):
    # Pinned legacy fixture (plan-audit F3): design.md entirely absent
    # -> source == "default" -> vacuous pass.
    d = _tmp_design_dir(tmp_path, None)
    (d / "plan.md").write_text(_stamped("light"))
    assert check_consistency(d) == []


def test_check_consistency_invalid_design_class_vacuous(tmp_path):
    # Invalid value -> read_class falls back to default -> vacuous pass.
    d = _tmp_design_dir(tmp_path, _stamped("enormous"))
    (d / "plan.md").write_text(_stamped("light"))
    assert check_consistency(d) == []


# 1.4 recommend_class rubric cases live in test_weight_class_lean.py


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
    d = _tmp_design_dir(tmp_path, _stamped("light"))
    rc = main(["read", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "light" in out
    assert "frontmatter" in out


def test_cli_read_default(tmp_path, capsys):
    d = _tmp_design_dir(tmp_path, "# No frontmatter\n")
    rc = main(["read", str(d)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "full" in out
    assert "default" in out


def test_cli_check_clean_exits_zero(tmp_path):
    d = _tmp_design_dir(tmp_path, _stamped("light"))
    (d / "plan.md").write_text(_stamped("light"))
    assert main(["check", str(d)]) == 0


def test_cli_check_findings_exit_one(tmp_path, capsys):
    d = _tmp_design_dir(tmp_path, _stamped("light"))
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
# The doc's content is not asserted here: its references are covered by
# skill_refs (invariant 46) and test_weight_class_contracts.py.

_PROTOCOL_DOC = Path(__file__).resolve().parent / "weight-class.md"


def test_protocol_doc_exists():
    assert _PROTOCOL_DOC.is_file()


# ---------------------------------------------------------------------------
# Phase 6 — live-repo integration stamps
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _design_dir(name: str) -> Path | None:
    """First existing design dir for `name`: archive first, then in-flight."""
    docs = _REPO_ROOT / "three-pillars-docs"
    for parent in ("completed-tp-designs", "tp-designs"):
        d = docs / parent / name
        if d.is_dir():
            return d
    return None


def test_self_stamp():
    """Task 6.1 — this design's own artifacts carry weight-class: full."""
    design_dir = _design_dir("design-depth-axis")
    if design_dir is None:
        pytest.skip("design-depth-axis dir absent (archived or different checkout)")
    assert read_class(design_dir) == ("full", "frontmatter")
    assert check_consistency(design_dir) == []


def test_dogfood_seed():
    """Task 6.2 — the file-size-limits seed is classified light for the dogfood."""
    design_dir = _design_dir("file-size-limits")
    seed = None if design_dir is None else design_dir / "seed.md"
    if seed is None or not seed.exists():
        pytest.skip("file-size-limits seed absent (archived or different checkout)")
    assert parse_frontmatter(seed.read_text(encoding="utf-8")).get("weight-class") == "light"


# ---------------------------------------------------------------------------
# Consolidated SKILL.md surface assertions (Phase 2)
# ---------------------------------------------------------------------------

_SKILLS_ROOT = Path(__file__).resolve().parent.parent


@_needs_claude_plugin_md
def test_surface_claude_md():
    """Task 2.5 — CLAUDE.md + CLAUDE.plugin.md use the four-class taxonomy."""
    for name in ("CLAUDE.md", "CLAUDE.plugin.md"):
        text = (_SKILLS_ROOT.parent / name).read_text(encoding="utf-8")
        assert "just do it, spike, or full design" not in text, (
            f"{name} still carries the bare three-approach phrase"
        )
        for klass in ("just-do-it", "light", "spike", "full"):
            assert klass in text, f"{name} must name the {klass!r} class"
