"""test_rollover_wiring.py — prose pins for the History-rollover wiring.

design: archive-slimming, Task 2.3.

Pinned 'Shipped invocation form': every SKILL.md that runs a new script calls
it as `python3 "$TP_ROOT"/skills/_shared/<script>.py`. A bare
`skills/_shared/history_rollover.py` (no `"$TP_ROOT"/` prefix) fails these
pins. Each pin is scoped to the named section or step — a token elsewhere in
the file does not satisfy it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMAT_MD = ROOT / "skills" / "_shared" / "living-doc-format.md"
DESIGN_LEARN = ROOT / "skills" / "tp-design-learn" / "SKILL.md"
SPIKE_LEARN = ROOT / "skills" / "tp-spike-learn" / "SKILL.md"
DOCS_UPDATE = ROOT / "skills" / "tp-docs-update" / "SKILL.md"
PLAN = ROOT / "skills" / "tp-plan" / "SKILL.md"

ROLLOVER = 'python3 "$TP_ROOT"/skills/_shared/history_rollover.py'
_PIN = re.compile(re.escape(ROLLOVER))
SWEEP = 'python3 "$TP_ROOT"/skills/_shared/archive_sweep.py'
_SWEEP_PIN = re.compile(re.escape(SWEEP))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice(text: str, start: str, end: str | None = None) -> str:
    """Slice `text` from the first `start` marker to the first `end` marker
    after it (or EOF). Shared helper: Task 2.4's docs-update / post-merge /
    plan pins slice the same way."""
    i = text.index(start)
    if end is None:
        return text[i:]
    j = text.index(end, i + len(start))
    return text[i:j]


def _step(text: str, number: int) -> str:
    """Slice step `number` of a SKILL.md `## Steps` list (from `N. ` to the
    next `M. ` step marker, whichever comes first)."""
    i = re.search(r"(?m)^%d\. " % number, text).start()
    rest = text[i + 2:]
    j = re.search(r"(?m)^%d\. " % (number + 1), rest).start()
    return rest[:j]


def _assert_invocation(name: str, block: str) -> None:
    assert _PIN.search(block), (
        f"{name}: must name the shipped invocation form {ROLLOVER!r}; a bare "
        f"skills/_shared/history_rollover.py path does not count")


def _assert_history_tokens(name: str, block: str) -> None:
    _assert_invocation(name, block)
    assert "15" in block, f"{name}: must state the keep count (15)"
    assert "decisions.md" in block, (
        f"{name}: a new History entry links to the design's decisions.md")
    assert "product_roadmap_archive.md" in block, (
        f"{name}: a Design Inventory row not found live is looked up in "
        f"product_roadmap_archive.md")


# --- living-doc-format.md §History -------------------------------------------


def test_format_history_section_pins_rollover():
    text = _read(FORMAT_MD)
    section = _slice(text, "## `## History` section", "## Status cells in tables")
    _assert_history_tokens("living-doc-format.md §History", section)
    assert "stage the doc's archive in the same commit" in section, (
        "living-doc-format.md §History: the archive is staged in the same "
        "commit as the appended entry")


# --- tp-design-learn/SKILL.md steps 7 and 11 ---------------------------------


def test_design_learn_step7_pins_rollover():
    step7 = _step(_read(DESIGN_LEARN), 7)
    _assert_invocation("tp-design-learn step 7", step7)


def test_design_learn_step11_stages_both_archives_when_rollover_moved():
    step11 = _step(_read(DESIGN_LEARN), 11)
    assert "architecture_archive.md" in step11, (
        "tp-design-learn step 11: stage list must name architecture_archive.md")
    assert "product_roadmap_archive.md" in step11, (
        "tp-design-learn step 11: stage list must name product_roadmap_archive.md")
    assert "when the rollover moved entries" in step11, (
        "tp-design-learn step 11: archives are staged when the rollover "
        "moved entries")


# --- tp-spike-learn/SKILL.md steps 7 and 11 ----------------------------------


def test_spike_learn_step7_pins_rollover():
    step7 = _step(_read(SPIKE_LEARN), 7)
    _assert_invocation("tp-spike-learn step 7", step7)


def test_spike_learn_step11_stages_both_archives_when_rollover_moved():
    step11 = _step(_read(SPIKE_LEARN), 11)
    assert "architecture_archive.md" in step11, (
        "tp-spike-learn step 11: stage list must name architecture_archive.md")
    assert "product_roadmap_archive.md" in step11, (
        "tp-spike-learn step 11: stage list must name product_roadmap_archive.md")
    assert "when the rollover moved entries" in step11, (
        "tp-spike-learn step 11: archives are staged when the rollover "
        "moved entries")


# --- Auto-Mode step 11 (PR #177 r2) -------------------------------------------


def _auto_step11(path: Path) -> str:
    """The `## Auto Mode` bullet that restates step 11's stage list: --auto is
    the only path /tp-run-full-design and /tp-spike-auto use."""
    auto = _slice(_read(path), "## Auto Mode")
    return next(l for l in auto.splitlines() if "Step 11 (commit) still runs" in l)


def test_design_learn_auto_step11_stages_rollover_archives():
    line = _auto_step11(DESIGN_LEARN)
    for archive in ("architecture_archive.md", "product_roadmap_archive.md"):
        assert archive in line, (
            f"tp-design-learn Auto Mode step 11: stage list must name {archive}")


def test_spike_learn_auto_step11_stages_rollover_archives():
    line = _auto_step11(SPIKE_LEARN)
    for archive in ("architecture_archive.md", "product_roadmap_archive.md"):
        assert archive in line, (
            f"tp-spike-learn Auto Mode step 11: stage list must name {archive}")


# --- Task 2.4: writer skills roll History over --------------------------------


def test_docs_update_rolls_and_offers_sweep():
    step7 = _step(_read(DOCS_UPDATE), 7)
    _assert_invocation("tp-docs-update step 7", step7)
    assert _SWEEP_PIN.search(step7), (
        "tp-docs-update step 7: must offer the shipped invocation form "
        f"{SWEEP!r}; a bare skills/_shared/archive_sweep.py path does not count")
    assert "dry run" in step7, (
        "tp-docs-update step 7: the sweep is offered as a dry run")
    assert "never" in step7.lower(), (
        "tp-docs-update step 7: the sweep never runs automatically")
    assert "--apply" in step7, (
        "tp-docs-update step 7: --apply runs only on the operator's confirmation")
    assert "stage" in step7.lower(), (
        "tp-docs-update step 7: the doc's archive is staged in the same commit")
    assert "archive" in step7.lower(), (
        "tp-docs-update step 7: must name the archive that is staged")


def test_plan_dependency_lookup_reads_archive():
    step3 = _step(_read(PLAN), 3)
    assert "product_roadmap_archive.md" in step3, (
        "tp-plan step 3: a dependency's Design Inventory row not found in "
        "the live product_roadmap.md is looked up in product_roadmap_archive.md")
    assert "Design Inventory — completed and superseded rows" in step3, (
        "tp-plan step 3: the lookup names the archive's completed-rows section")
