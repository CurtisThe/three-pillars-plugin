"""End-to-end tests for the deterministic scaffolding of `--auto`-pipeline skills.

D14's auto-mode retrofit splits responsibility along an explicit boundary
(see plan.md "Out-of-band" → "D14 / D12 test-scope boundary"):

  - D14 tests the deterministic scaffolding only — floor validator
    (Tasks 1.2 + 4.2), framework-check invariant (1.1), decisions.md
    init/append/BLOCKED snippet (1.3 + 4.3), and impl-audit verdict
    rule (4.4). Pure subprocess CLI / snippet exercises, no LLM.

  - D12 dogfood tests the LLM-driven paths.

Run with: pytest skills/_shared/test_auto_mode_e2e.py -q
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

VALIDATOR_SCRIPT = Path(__file__).parent / "validate_design_floor.py"
AUTO_MODE_MD = Path(__file__).parent / "auto-mode.md"
REPO_ROOT = Path(__file__).parent.parent.parent
SCHEMA_HEADER_LINE = "# Decisions log — schema v1"


def _resolve_repo_design_dir(name: str) -> Path | None:
    """Return this repo's design directory for `name`, whether active or archived.

    Probes `three-pillars-docs/tp-designs/{name}/` first (active), then
    `three-pillars-docs/completed-tp-designs/{name}/` (archived). Returns the
    first existing path, or None if neither exists. Lets the validator E2E
    fixture survive `/tp-design-complete` archiving the very design it tests.
    """
    for parent in ("tp-designs", "completed-tp-designs"):
        candidate = REPO_ROOT / "three-pillars-docs" / parent / name
        if candidate.is_dir():
            return candidate
    return None

_PYTHON_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _extract_canonical_snippet() -> str:
    """Pull the first ```python ... ``` block from auto-mode.md.

    The canonical init/append protocol lives in `skills/_shared/auto-mode.md`.
    The tests below exercise it byte-identically rather than reimplementing it —
    if the snippet drifts from the doc, the tests catch it.
    """
    text = AUTO_MODE_MD.read_text()
    m = _PYTHON_FENCE_RE.search(text)
    assert m is not None, "canonical python snippet missing from auto-mode.md"
    snippet = m.group(1)
    assert "def append_decision" in snippet, (
        "first python block in auto-mode.md is no longer the init/append snippet"
    )
    return snippet


def _load_canonical_helpers() -> dict[str, object]:
    """Exec the canonical snippet and return its namespace.

    Yields `append_decision` and `SCHEMA_HEADER` for direct invocation.
    """
    ns: dict[str, object] = {}
    exec(_extract_canonical_snippet(), ns)  # noqa: S102 — tests of doc-canonical snippet
    return ns


def _write_lock_owned_by(design_dir: Path, user: str, *, design: str = "test-design", branch: str = "tp/test-design") -> Path:
    """Drop a lock.json into the design dir owned by `user`. Shared module-level
    helper for any future test that needs to simulate a lock-conflict scenario."""
    lock = design_dir / "lock.json"
    lock.write_text(
        json.dumps(
            {
                "design": design,
                "branch": branch,
                "owner": user,
                "phase": "test",
                "acquired_at": "2026-05-22T00:00:00Z",
                "last_touched": "2026-05-22T00:00:00Z",
                "previous_owners": [],
            },
            indent=2,
        )
    )
    return lock


def _run_auto_stub(
    design_dir: Path,
    *,
    current_user: str = "me@example.com",
    entry: str | None = None,
) -> int:
    """Simulate one `--auto` skill invocation against `design_dir`.

    Mirrors the contract every `--auto` skill inherits from auto-mode.md:
      - if `lock.json` exists and is owned by a different user → append a
        BLOCKED entry and return non-zero (never prompt).
      - otherwise → append the given Decision Entry and return 0.

    The append uses the canonical snippet from auto-mode.md (loaded via
    `_load_canonical_helpers()`), so any drift between the snippet and its
    consumers is caught here.
    """
    ns = _load_canonical_helpers()
    append_decision = ns["append_decision"]

    lock = design_dir / "lock.json"
    if lock.is_file():
        owner = json.loads(lock.read_text()).get("owner")
        if owner and owner != current_user:
            blocked_entry = (
                "### [tp-test-stub] BLOCKED — lock conflict\n"
                "**Cause**: lock-conflict\n"
                f"**Details**: lock.json owned by {owner}, not {current_user}\n"
            )
            append_decision(design_dir, blocked_entry)  # type: ignore[operator]
            return 1

    if entry is None:
        entry = (
            "### [tp-test-stub] decision\n"
            "**Question**: what would have been asked\n"
            "**Decided**: a sensible default\n"
            "**Reasoning**: deterministic test stub\n"
            "**Confidence**: High\n"
        )
    append_decision(design_dir, entry)  # type: ignore[operator]
    return 0


def _well_formed_sections() -> dict[str, str]:
    """All required + optional sections with non-placeholder bodies above the 20-char floor.

    Reused by every E2E class — keep stable. Tasks 4.3 and 4.4 build their
    own design-dirs on top of this; deviating shapes go in per-class helpers.
    """
    return {
        "Problem": (
            "Autonomous TDD pipeline runs require a floor schema so an orchestrator "
            "can decide whether design.md is complete enough to proceed."
        ),
        "Vision alignment": (
            "Advances 'floor, not ceiling' — autonomous gates reject under-specified "
            "designs early instead of letting them rot in later phases."
        ),
        "Scope": (
            "### In scope\n"
            "Deterministic validation of design.md against the v1 floor schema; "
            "JSON-on-stderr verdict on BLOCKED.\n\n"
            "### Out of scope\n"
            "LLM-driven content generation; that lives in /tp-design and /tp-design-detail."
        ),
        "Behaviors": (
            "Read design.md, classify each required section as present / empty / "
            "placeholder-only, and emit the verdict on stderr."
        ),
        "Constraints": (
            "Pure stdlib; under 200 lines; schema version is a module-level constant "
            "so callers can pin against breaking changes."
        ),
        "Dependencies": "skills/_shared/auto-mode.md documents how Shape A consumers use this output.",
        "Entities": "Section parser, classification result, verdict JSON, exit-code contract.",
        "Open Questions": (
            "Whether a v2 schema needs a softer warning tier between PASS and BLOCKED."
        ),
    }


def _build_design_md(
    tmp_path: Path,
    sections: dict[str, str] | None = None,
    title: str = "test-design",
    body_before_sections: str | None = None,
) -> Path:
    """Write a design.md from the section dict and return the design dir.

    `body_before_sections` lets callers inject a title-only or
    title-plus-prose-only design.md (no ## headings at all) for negative tests.
    """
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    lines: list[str] = [f"# {title}", ""]
    if body_before_sections is not None:
        lines.append(body_before_sections)
        lines.append("")
    if sections is None:
        sections = _well_formed_sections()
    for heading, body in sections.items():
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body)
        lines.append("")
    (design_dir / "design.md").write_text("\n".join(lines))
    return design_dir


def _run_validator(design_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT), str(design_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


class TestValidatorE2E:
    """End-to-end fixture coverage of `validate_design_floor.py`.

    Unlike `test_validate_design_floor.py`, which exercises one rule per
    fixture, this class verifies the validator against full-design shapes
    an orchestrator would actually hand it: the real repo design.md, a
    title-only stub, a multi-failure-mode partial, and an optional-missing
    case.
    """

    def test_real_repo_design_passes(self) -> None:
        """This repo's own design.md must satisfy the floor schema —
        otherwise the design driving this validator wouldn't pass its own gate.

        Resolved via `_resolve_repo_design_dir` so the test keeps working after
        `/tp-design-complete` moves the design from tp-designs/ to
        completed-tp-designs/.
        """
        design_dir = _resolve_repo_design_dir("design-pipeline-auto-mode")
        assert design_dir is not None, (
            "design-pipeline-auto-mode not found under tp-designs/ or completed-tp-designs/"
        )
        assert (design_dir / "design.md").is_file()
        result = _run_validator(design_dir)
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert "BLOCKED" not in result.stderr
        assert "BLOCKED" not in result.stdout

    def test_title_only_blocked(self, tmp_path: Path) -> None:
        """A design.md with only the H1 title and no ## sections at all blocks
        with every required section flagged as missing."""
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        (design_dir / "design.md").write_text("# Title-only stub\n\nSome prose but no headings.\n")
        result = _run_validator(design_dir)
        assert result.returncode == 1
        assert "BLOCKED" not in result.stdout, "verdict must be on stderr"
        verdict = json.loads(result.stderr)
        assert verdict["verdict"] == "BLOCKED"
        assert verdict["schema_version"] == 1
        for required in ("Problem", "Vision alignment", "Scope", "Behaviors", "Constraints"):
            assert required in verdict["missing"], f"expected {required!r} in missing"

    def test_partial_fixture_flags_missing_and_placeholder_only(self, tmp_path: Path) -> None:
        """A design.md that mixes failure modes — one required section absent and
        another present-but-placeholder — must surface both keys in the verdict."""
        sections = _well_formed_sections()
        del sections["Vision alignment"]
        sections["Behaviors"] = "..."
        design_dir = _build_design_md(tmp_path, sections)
        result = _run_validator(design_dir)
        assert result.returncode == 1
        verdict = json.loads(result.stderr)
        assert "Vision alignment" in verdict["missing"]
        assert "Behaviors" in verdict["placeholder_only"]

    def test_missing_optional_open_questions_warns(self, tmp_path: Path) -> None:
        """Dropping only the optional `## Open Questions` section must still PASS
        (exit 0) and emit a human-readable warning on stderr — never JSON."""
        sections = _well_formed_sections()
        del sections["Open Questions"]
        design_dir = _build_design_md(tmp_path, sections)
        result = _run_validator(design_dir)
        assert result.returncode == 0, f"stderr={result.stderr!r}"
        assert result.stderr.strip() != "", "expected warning on stderr"
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stderr)
        assert "Open Questions" in result.stderr


class TestDecisionsLog:
    """Init / append / lock-conflict coverage for the canonical snippet
    in `skills/_shared/auto-mode.md`. The snippet is exec'd directly via
    `_run_auto_stub` so any drift between the doc and its consumers is
    caught here — no SKILL.md is invoked.
    """

    def test_fresh_design_dir_has_no_log(self, tmp_path: Path) -> None:
        """Before any `--auto` skill runs, `decisions.md` must not exist."""
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        assert not (design_dir / "decisions.md").exists()

    def test_first_invocation_creates_log_with_header_and_one_entry(self, tmp_path: Path) -> None:
        """First invocation writes the schema-v1 header on line 1 and exactly
        one Decision Entry below it."""
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        rc = _run_auto_stub(design_dir)
        assert rc == 0
        log = design_dir / "decisions.md"
        assert log.is_file()
        lines = log.read_text().splitlines()
        assert lines[0] == SCHEMA_HEADER_LINE, f"line 1 was {lines[0]!r}"
        header_count = sum(1 for ln in lines if ln == SCHEMA_HEADER_LINE)
        assert header_count == 1
        entry_count = sum(1 for ln in lines if ln.startswith("### "))
        assert entry_count == 1, f"expected exactly one entry, saw {entry_count}"

    def test_second_invocation_appends_without_rewriting_header(self, tmp_path: Path) -> None:
        """Second invocation appends a second entry; the header stays a
        single line."""
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        assert _run_auto_stub(design_dir) == 0
        assert _run_auto_stub(
            design_dir,
            entry=(
                "### [tp-test-stub] second decision\n"
                "**Question**: second pass\n"
                "**Decided**: append, do not rewrite\n"
                "**Reasoning**: snippet is append-only after init\n"
                "**Confidence**: High\n"
            ),
        ) == 0
        lines = (design_dir / "decisions.md").read_text().splitlines()
        header_count = sum(1 for ln in lines if ln == SCHEMA_HEADER_LINE)
        assert header_count == 1, f"header must not be rewritten; saw {header_count} copies"
        entry_count = sum(1 for ln in lines if ln.startswith("### "))
        assert entry_count == 2, f"expected two entries, saw {entry_count}"

    def test_lock_owned_by_other_user_exits_nonzero_with_blocked_entry(self, tmp_path: Path) -> None:
        """When `lock.json` is owned by another user, the stub exits non-zero
        and appends a BLOCKED entry to `decisions.md` rather than prompting."""
        design_dir = tmp_path / "design"
        design_dir.mkdir()
        _write_lock_owned_by(design_dir, "other@example.com")
        rc = _run_auto_stub(design_dir, current_user="me@example.com")
        assert rc != 0, "lock conflict must exit non-zero"
        log_text = (design_dir / "decisions.md").read_text()
        assert log_text.splitlines()[0] == SCHEMA_HEADER_LINE
        assert "BLOCKED" in log_text
        assert "lock-conflict" in log_text
        assert "other@example.com" in log_text


class TestImplAuditVerdict:
    """Deterministic mapping from finding-confidence mix to the
    `/tp-implementation-audit --auto` verdict + exit code.

    Empty findings → PASS. All-High → PASS WITH NOTES. Any Medium or Low
    present → NEEDS WORK (non-zero exit so the orchestrator escalates).
    The Shape C *dispatch* path lives in `/tp-design-audit --auto`
    inline; the verdict rule lives in `skills/_shared/auto_verdict.py`
    and is the only piece this class exercises.
    """

    def test_empty_findings_pass(self) -> None:
        from skills._shared.auto_verdict import compute_verdict
        verdict, code = compute_verdict([])
        assert verdict == "PASS"
        assert code == 0

    def test_all_high_pass_with_notes(self) -> None:
        from skills._shared.auto_verdict import compute_verdict
        verdict, code = compute_verdict(["High", "High", "High"])
        assert verdict == "PASS WITH NOTES"
        assert code == 0

    def test_any_medium_or_low_needs_work(self) -> None:
        from skills._shared.auto_verdict import compute_verdict
        verdict_med, code_med = compute_verdict(["High", "Medium"])
        assert verdict_med == "NEEDS WORK"
        assert code_med != 0
        verdict_low, code_low = compute_verdict(["Low"])
        assert verdict_low == "NEEDS WORK"
        assert code_low != 0

    def test_unknown_confidence_raises(self) -> None:
        """Garbage in must not silently map to PASS WITH NOTES — a policy
        function fails loudly on typos/casing differences instead of letting
        them slip through to a wrong verdict."""
        from skills._shared.auto_verdict import compute_verdict
        for bad in (["high"], ["HIGH"], ["Med"], ["High", "unknown"], [""]):
            with pytest.raises(ValueError, match="unknown confidence"):
                compute_verdict(bad)
