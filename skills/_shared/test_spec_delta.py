"""Tests for skills/_shared/spec_delta.py — the OpenSpec-derived delta-spec engine.

Covers the plan's phases: parse (P1), validate (P2), merge+refusal (P3), CLI+demo (P4),
including the design+plan audit additions (block boundaries, round-trip, responsibility
boundary, atomicity, rename edges, the parallel-edit refusal).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from spec_delta import (  # noqa: E402
    MergeConflict,
    SpecParseError,
    main,
    merge,
    parse_delta,
    parse_spec,
    validate,
)

# --------------------------------------------------------------------------- fixtures

BASE = """## Requirements

### Requirement: Login
The system SHALL provide login.

#### Scenario: Valid credentials
- **WHEN** valid credentials are submitted
- **THEN** the user is authenticated

### Requirement: Logout
The system SHALL provide logout.

#### Scenario: Click logout
- **WHEN** the user clicks logout
- **THEN** the session ends

#### Scenario: Idle logout
- **WHEN** the user is idle 30m
- **THEN** the session ends

### Requirement: Profile
The system SHALL show a profile.

#### Scenario: View profile
- **WHEN** the user opens profile
- **THEN** details are shown

### Requirement: Search
The system SHALL provide search.

#### Scenario: Query
- **WHEN** the user searches
- **THEN** results are returned
"""

BASE_NO_PREAMBLE = """### Requirement: Solo
The system SHALL stand alone.

#### Scenario: Only one
- **WHEN** parsed
- **THEN** it is found
"""

BASE_TRAILING = BASE + "## Notes\nA trailing non-requirement section.\n"

DELTA_HAPPY = """## ADDED Requirements

### Requirement: Dark Mode
The system SHALL support a dark theme.

#### Scenario: Toggle
- **WHEN** the theme is toggled
- **THEN** the UI switches

## MODIFIED Requirements

### Requirement: Login
The system SHALL provide secure login with optional 2FA.

#### Scenario: Valid credentials
- **WHEN** valid credentials are submitted
- **THEN** the user is authenticated

## REMOVED Requirements

### Requirement: Logout

## RENAMED Requirements

- FROM: `### Requirement: Profile`
- TO: `### Requirement: Account`
"""


def _added(name, scen=True):
    s = "\n\n#### Scenario: S\n- **WHEN** x\n- **THEN** y" if scen else ""
    return f"## ADDED Requirements\n\n### Requirement: {name}\nThe system SHALL do {name}.{s}\n"


def _modified(name, body="updated"):
    return (
        f"## MODIFIED Requirements\n\n### Requirement: {name}\n"
        f"The system SHALL be {body}.\n\n#### Scenario: S\n- **WHEN** x\n- **THEN** y\n"
    )


# --------------------------------------------------------------------------- P1: parse

def test_parse_spec_requirements():
    spec = parse_spec(BASE)
    assert list(spec.requirements) == ["Login", "Logout", "Profile", "Search"]
    assert spec.requirements["Login"].scenarios == 1
    assert spec.requirements["Logout"].scenarios == 2
    assert "## Requirements" in spec.preamble


def test_parse_spec_no_preamble():
    spec = parse_spec(BASE_NO_PREAMBLE)
    assert spec.preamble == ""
    assert list(spec.requirements) == ["Solo"]
    assert spec.requirements["Solo"].scenarios == 1


def test_parse_spec_no_requirements_normalizes_crlf():
    # Regression: the no-requirements path once returned the raw text, leaving
    # CRLF/mixed newlines un-normalized unlike every other parse path.
    spec = parse_spec("Just preamble.\r\nNo requirements here.\r\n")
    assert "\r" not in spec.preamble
    assert spec.preamble == "Just preamble.\nNo requirements here."
    assert spec.requirements == {}


def test_parse_spec_eof_terminated_block():
    # the last requirement (Search) runs to EOF and keeps its scenario
    spec = parse_spec(BASE)
    assert "#### Scenario: Query" in spec.requirements["Search"].block


def test_parse_spec_trailing_section_not_absorbed():
    # a `## ` header after the requirements must NOT be swallowed into the last block
    spec = parse_spec(BASE_TRAILING)
    assert "## Notes" not in spec.requirements["Search"].block
    assert "## Notes" in spec.trailing


def test_parse_delta_all_four_ops():
    delta = parse_delta(DELTA_HAPPY)
    by_kind = {op.kind: op for op in delta.ops}
    assert set(by_kind) == {"ADDED", "MODIFIED", "REMOVED", "RENAMED"}
    assert by_kind["ADDED"].name == "Dark Mode" and by_kind["ADDED"].scenarios == 1
    assert by_kind["MODIFIED"].name == "Login"
    assert by_kind["REMOVED"].name == "Logout"
    assert by_kind["RENAMED"].from_name == "Profile" and by_kind["RENAMED"].name == "Account"


@pytest.mark.parametrize(
    "text",
    [
        "## Bogus Requirements\n\n### Requirement: X\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n",
        "### Requirement: Stray\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n",
        "Some prose but no recognized delta section at all.\n",
    ],
    ids=["unknown-section", "requirement-outside-section", "nonempty-zero-ops"],
)
def test_parse_delta_failloud(text):
    with pytest.raises(SpecParseError):
        parse_delta(text)


# --------------------------------------------------------------------------- P2: validate

def test_validate_missing_scenario():
    issues = validate(parse_delta(_added("NoScen", scen=False)))
    assert any(i.code == "missing-scenario" for i in issues)


def test_validate_empty_name():
    delta = parse_delta("## ADDED Requirements\n\n### Requirement:\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n")
    assert any(i.code == "empty-requirement-name" for i in validate(delta))


def test_validate_clean_delta_against_base():
    assert [i for i in validate(parse_delta(DELTA_HAPPY), parse_spec(BASE)) if i.severity == "ERROR"] == []


@pytest.mark.parametrize(
    "text,expected_code",
    [
        ("## MODIFIED Requirements\n\n### Requirement: Login\nbody a.\n\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n\n### Requirement: Login\nbody b.\n\n#### Scenario: t\n- **WHEN** c\n- **THEN** d\n", "duplicate-op-target"),
        (_added("Account") + "\n## RENAMED Requirements\n\n- FROM: `### Requirement: Profile`\n- TO: `### Requirement: Account`\n", "duplicate-op-target"),
        ("## RENAMED Requirements\n\n- FROM: `### Requirement: Login`\n- TO: `### Requirement: Login`\n", "rename-to-self"),
        (_added("Login"), "add-existing"),
        (_modified("Ghost"), "modify-missing-target"),
        ("## REMOVED Requirements\n\n### Requirement: Ghost\n", "remove-missing-target"),
        ("## RENAMED Requirements\n\n- FROM: `### Requirement: Ghost`\n- TO: `### Requirement: New`\n", "rename-missing-source"),
        ("## RENAMED Requirements\n\n- FROM: `### Requirement: Profile`\n- TO: `### Requirement: Login`\n", "rename-target-exists"),
    ],
    ids=["dup-op", "rename+add-same", "rename-self", "add-existing", "modify-missing", "remove-missing", "rename-missing-src", "rename-target-exists"],
)
def test_validate_conflicts(text, expected_code):
    issues = validate(parse_delta(text), parse_spec(BASE))
    assert any(i.code == expected_code for i in issues), [i.code for i in issues]


def test_validate_single_delta_has_no_concurrent_conflict():
    # responsibility boundary: concurrent-edit-conflict is merge's job, never validate's
    issues = validate(parse_delta(_modified("Login")), parse_spec(BASE))
    assert all(i.code != "concurrent-edit-conflict" for i in issues)


# --------------------------------------------------------------------------- P3: merge + refusal

def test_merge_applies_all_ops_in_order_and_roundtrips():
    merged = merge(BASE, [DELTA_HAPPY])
    assert "### Requirement: Logout" not in merged          # REMOVED
    assert "secure login with optional 2FA" in merged       # MODIFIED
    assert "### Requirement: Account" in merged             # RENAMED (header rewritten)
    assert "### Requirement: Profile" not in merged
    assert "### Requirement: Dark Mode" in merged           # ADDED
    reparsed = parse_spec(merged)
    assert list(reparsed.requirements) == ["Login", "Account", "Search", "Dark Mode"]  # ADDED appended last
    # round-trip stability: serialize -> parse preserves names + blocks (no drift)
    from spec_delta import _serialize
    again = parse_spec(_serialize(reparsed))
    assert list(again.requirements) == list(reparsed.requirements)
    for name in again.requirements:
        assert again.requirements[name].block.strip() == reparsed.requirements[name].block.strip()


@pytest.mark.parametrize(
    "deltas,code",
    [
        ([_modified("Ghost")], "modify-missing-target"),
        (["## REMOVED Requirements\n\n### Requirement: Logout\n\n## ADDED Requirements\n\n### Requirement: Logout\nThe system SHALL re-add.\n\n#### Scenario: S\n- **WHEN** x\n- **THEN** y\n"], "duplicate-op-target"),
    ],
    ids=["modify-missing", "remove+add-same-name"],
)
def test_merge_refuses(deltas, code):
    with pytest.raises(MergeConflict) as exc:
        merge(BASE, deltas)
    assert any(i.code == code for i in exc.value.issues), [i.code for i in exc.value.issues]


def test_merge_refuses_empty_delta_set():
    # Fail-loud: zero deltas is not a successful no-op merge.
    with pytest.raises(SpecParseError):
        merge(BASE, [])


def test_merge_is_atomic_base_untouched_after_conflict():
    base_before = BASE
    with pytest.raises(MergeConflict):
        merge(BASE, [_modified("Ghost")])
    assert BASE == base_before                       # input string unchanged
    assert "Logout" in parse_spec(BASE).requirements  # base still intact, nothing partially applied


def test_parallel_edit_refused_not_silently_dropped():
    # OpenSpec's bug: two concurrent deltas both MODIFY one requirement -> it silently
    # drops the first. The engine REFUSES instead.
    d1 = _modified("Login", body="variant A")
    d2 = _modified("Login", body="variant B")
    with pytest.raises(MergeConflict) as exc:
        merge(BASE, [d1, d2])
    assert any(i.code == "concurrent-edit-conflict" for i in exc.value.issues)
    # the edit itself is fine; only the *concurrency* is refused
    assert isinstance(merge(BASE, [d1]), str)


# --------------------------------------------------------------------------- P4: CLI

def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def test_cli_merge_ok(tmp_path, capsys):
    base = _w(tmp_path, "base.md", BASE)
    delta = _w(tmp_path, "d.md", DELTA_HAPPY)
    rc = main(["spec_delta.py", "merge", base, delta])
    out = capsys.readouterr().out
    assert rc == 0 and "### Requirement: Dark Mode" in out


def test_cli_merge_concurrent_blocked(tmp_path, capsys):
    base = _w(tmp_path, "base.md", BASE)
    d1 = _w(tmp_path, "d1.md", _modified("Login", "A"))
    d2 = _w(tmp_path, "d2.md", _modified("Login", "B"))
    rc = main(["spec_delta.py", "merge", base, d1, d2])
    err = capsys.readouterr().err
    verdict = json.loads(err)
    assert rc == 1 and verdict["verdict"] == "BLOCKED"
    assert any(e["code"] == "concurrent-edit-conflict" for e in verdict["errors"])


def test_cli_validate_missing_scenario_blocked(tmp_path, capsys):
    delta = _w(tmp_path, "d.md", _added("NoScen", scen=False))
    rc = main(["spec_delta.py", "validate", delta])
    assert rc == 1 and json.loads(capsys.readouterr().err)["verdict"] == "BLOCKED"


def test_cli_validate_ok(tmp_path):
    base = _w(tmp_path, "base.md", BASE)
    delta = _w(tmp_path, "d.md", DELTA_HAPPY)
    assert main(["spec_delta.py", "validate", delta, "--base", base]) == 0


def test_cli_usage_and_missing_file(tmp_path):
    assert main(["spec_delta.py"]) == 2
    assert main(["spec_delta.py", "merge", str(tmp_path / "nope.md"), str(tmp_path / "no2.md")]) == 2


def test_cli_validate_rejects_extra_positional(tmp_path, capsys):
    # Regression: `validate` once silently used only the LAST positional, so a
    # second delta path could validate the wrong file. Now it fails loud.
    d1 = _w(tmp_path, "d1.md", DELTA_HAPPY)
    d2 = _w(tmp_path, "d2.md", _added("NoScen", scen=False))  # would BLOCK if validated
    rc = main(["spec_delta.py", "validate", d1, d2])
    assert rc == 2
    assert "extra argument" in capsys.readouterr().err


def test_cli_validate_rejects_unknown_flag(tmp_path, capsys):
    delta = _w(tmp_path, "d.md", DELTA_HAPPY)
    rc = main(["spec_delta.py", "validate", delta, "--nope"])
    assert rc == 2
    assert "unknown flag" in capsys.readouterr().err


# --------------------------------------------------------------------------- P4: demo

def test_demo_fixtures_refuse():
    root = Path(__file__).resolve().parents[2]
    rel = "openspec-primitives/demos/parallel_edit_silent_drop.py"
    # A design migrates tp-designs/ -> completed-tp-designs/ at /tp-design-complete,
    # so accept either location — archiving the design must not break this fixture.
    candidates = [
        root / "three-pillars-docs/tp-designs" / rel,
        root / "three-pillars-docs/completed-tp-designs" / rel,
    ]
    demo = next((p for p in candidates if p.is_file()), None)
    assert demo is not None, candidates
    proc = subprocess.run([sys.executable, str(demo)], capture_output=True, text=True)
    assert proc.returncode != 0
    assert "REFUSED" in (proc.stdout + proc.stderr)


# --------------------------------------------------- implementation-audit regressions

@pytest.mark.parametrize(
    "text",
    [
        # RENAMED written with `### Requirement:` blocks (wrong syntax) + a valid ADDED section:
        # must NOT silently drop the rename (impl audit — Feynman/Ada).
        "## ADDED Requirements\n\n### Requirement: X\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n\n## RENAMED Requirements\n\n### Requirement: Old\n### Requirement: New\n",
        # dangling FROM with no matching TO
        "## RENAMED Requirements\n\n- FROM: `### Requirement: A`\n- FROM: `### Requirement: B`\n- TO: `### Requirement: C`\n",
        # a section with prose but no requirement
        "## ADDED Requirements\n\njust prose, no requirement here\n",
    ],
    ids=["renamed-wrong-syntax", "dangling-from", "section-no-requirement"],
)
def test_parse_delta_failloud_no_silent_drop(text):
    with pytest.raises(SpecParseError):
        parse_delta(text)


def test_parse_spec_refuses_requirements_after_section_break():
    # a `## ` header splitting the requirements must RAISE, not silently route the rest to trailing
    spec_text = (
        "## Requirements\n\n### Requirement: One\n#### Scenario: s\n- **WHEN** a\n- **THEN** b\n\n"
        "## Interlude\nsome prose\n\n### Requirement: Two\n#### Scenario: t\n- **WHEN** c\n- **THEN** d\n"
    )
    with pytest.raises(SpecParseError):
        parse_spec(spec_text)
