"""Tests for weight_class.escalate — the upward-only weight-class stamp.

Task 1.3 of the run-full-design-jdi-tier design: an unattended run that turns
out too big for its declared class stamps the new class into design.md and
every present sibling artifact, logs one line, and refuses to stamp the same
or a lighter class (weight-class.md: escalation is always allowed and logged,
de-escalation never).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from weight_class import (  # noqa: E402
    ESCALATION_ORDER,
    check_consistency,
    escalate,
    main,
    parse_frontmatter,
    read_class,
)

ARROW = "→"


def _stamped(klass: str, title: str = "Doc", extra: str = "") -> str:
    return f"---\nweight-class: {klass}{extra}\n---\n# {title}\n"


def _dir(tmp_path, design_md: str, siblings=()) -> Path:
    """Design dir holding design.md plus the named sibling artifacts."""
    d = tmp_path / "some-design"
    d.mkdir()
    (d / "design.md").write_text(design_md, encoding="utf-8")
    for name in siblings:
        (d / name).write_text(_stamped("just-do-it", name), encoding="utf-8")
    return d


def _snapshot(d: Path) -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(d.iterdir())}


# ---------------------------------------------------------------------------
# The order
# ---------------------------------------------------------------------------

def test_escalation_order_is_the_three_ceremony_classes():
    # `spike` is a different axis (unknown approach), so it has no rung here.
    assert ESCALATION_ORDER == ("just-do-it", "light", "full")


# ---------------------------------------------------------------------------
# Stamping up
# ---------------------------------------------------------------------------

def test_escalate_returns_the_log_line(tmp_path):
    d = _dir(tmp_path, _stamped("just-do-it", "Design"), siblings=("seed.md",))
    line = escalate(d, "diff-cap: 151", to="light")
    assert line == (
        "[tp-run-full-design] weight-class escalation: "
        f"just-do-it {ARROW} light (diff-cap: 151)"
    )


def test_escalate_stamps_design_md_and_every_present_sibling(tmp_path):
    d = _dir(
        tmp_path,
        _stamped("just-do-it", "Design"),
        siblings=("seed.md", "detailed-design.md"),
    )
    escalate(d, "diff-cap: 151", to="light")
    for name in ("design.md", "seed.md", "detailed-design.md"):
        text = (d / name).read_text(encoding="utf-8")
        assert parse_frontmatter(text)["weight-class"] == "light", name


def test_escalate_keeps_other_frontmatter_keys_and_body(tmp_path):
    d = _dir(
        tmp_path,
        _stamped("just-do-it", "Design", extra="\nstatus: draft\nowner: someone"),
        siblings=("seed.md",),
    )
    escalate(d, "reason", to="light")
    fm = parse_frontmatter((d / "design.md").read_text(encoding="utf-8"))
    assert fm == {
        "weight-class": "light",
        "status": "draft",
        "owner": "someone",
    }
    # tp-allow-fragile: reads the file escalate just wrote; preserving the body is its contract
    assert "# Design" in (d / "design.md").read_text(encoding="utf-8")


def test_escalate_leaves_check_clean(tmp_path):
    d = _dir(
        tmp_path,
        _stamped("just-do-it", "Design"),
        siblings=("seed.md", "detailed-design.md", "plan.md"),
    )
    assert check_consistency(d) == []
    escalate(d, "diff-cap: 151", to="light")
    assert check_consistency(d) == []
    assert read_class(d) == ("light", "frontmatter")


def test_escalate_stamps_plan_md_only_when_present(tmp_path):
    d = _dir(tmp_path, _stamped("just-do-it", "Design"), siblings=("seed.md",))
    escalate(d, "diff-cap: 151", to="light")
    assert not (d / "plan.md").exists()

    (d / "plan.md").write_text(_stamped("just-do-it", "Plan"), encoding="utf-8")
    escalate(d, "diff-cap: 200", to="full")
    text = (d / "plan.md").read_text(encoding="utf-8")
    assert parse_frontmatter(text)["weight-class"] == "full"


def test_escalate_two_rungs_is_allowed(tmp_path):
    d = _dir(tmp_path, _stamped("just-do-it", "Design"))
    escalate(d, "two rungs", to="full")
    assert read_class(d) == ("full", "frontmatter")


# ---------------------------------------------------------------------------
# Refusals — same, lighter, or unorderable target
# ---------------------------------------------------------------------------

def test_escalate_same_class_raises_and_changes_nothing(tmp_path):
    d = _dir(tmp_path, _stamped("light", "Design"), siblings=("seed.md", "plan.md"))
    before = _snapshot(d)
    with pytest.raises(ValueError):
        escalate(d, "already light", to="light")
    assert _snapshot(d) == before


def test_escalate_lighter_class_raises_and_changes_nothing(tmp_path):
    d = _dir(tmp_path, _stamped("full", "Design"), siblings=("seed.md", "plan.md"))
    before = _snapshot(d)
    with pytest.raises(ValueError):
        escalate(d, "want less ceremony", to="light")
    assert _snapshot(d) == before


def test_escalate_to_spike_raises_and_changes_nothing(tmp_path):
    # spike is not a rung on this axis — it is never an escalation target.
    d = _dir(tmp_path, _stamped("just-do-it", "Design"), siblings=("seed.md",))
    before = _snapshot(d)
    with pytest.raises(ValueError):
        escalate(d, "novelty", to="spike")
    assert _snapshot(d) == before


def test_escalate_unknown_target_raises_and_changes_nothing(tmp_path):
    d = _dir(tmp_path, _stamped("just-do-it", "Design"), siblings=("seed.md",))
    before = _snapshot(d)
    with pytest.raises(ValueError):
        escalate(d, "typo", to="enormous")
    assert _snapshot(d) == before


def test_escalate_from_default_full_refuses(tmp_path):
    # design.md with no frontmatter -> read_class falls back to ("full", "default")
    # -> nothing is above it, so the stamp is refused rather than invented.
    d = _dir(tmp_path, "# Design with no frontmatter\n", siblings=("seed.md",))
    before = _snapshot(d)
    with pytest.raises(ValueError):
        escalate(d, "nope", to="light")
    assert _snapshot(d) == before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_escalate_prints_the_line_and_exits_zero(tmp_path, capsys):
    d = _dir(tmp_path, _stamped("just-do-it", "Design"), siblings=("seed.md",))
    rc = main(["escalate", str(d), "--to", "light", "--reason", "diff-cap: 151"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == (
        "[tp-run-full-design] weight-class escalation: "
        f"just-do-it {ARROW} light (diff-cap: 151)"
    )
    assert read_class(d) == ("light", "frontmatter")


def test_cli_escalate_refused_exits_one(tmp_path, capsys):
    d = _dir(tmp_path, _stamped("light", "Design"), siblings=("seed.md",))
    rc = main(["escalate", str(d), "--to", "just-do-it", "--reason", "smaller"])
    assert rc == 1
    assert read_class(d) == ("light", "frontmatter")
