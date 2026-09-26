"""Prose-contract guards for the FREE-_shared-script resolution adoption.

Plan Tasks 2.1 (the canonical snippet in first-run.md) and 2.2 (the 3 executed
github_pr_author.py call sites). Every assertion reads the SHIPPED file via
``git rev-parse --show-toplevel`` — never a transcribed copy — so a regression
in the real prose (e.g. a call site reverting to the bare ``$TP_ROOT`` pattern
this design removes) fails the guard.

Run with: python -m pytest skills/_shared/test_resolve_script_prose.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

#: Anchored on THIS FILE, like every sibling module in this suite.
#:
#: This used to shell out to `git rev-parse --show-toplevel` with check=True at
#: MODULE IMPORT — against the pytest process cwd, not the file. So collection
#: of this module depended on where pytest was launched from and on git being
#: installed: run it from outside a repo and the whole module raised
#: CalledProcessError during collection rather than failing an assertion. The
#: shipped files it reads sit at a FIXED offset from this file, so nothing here
#: ever needed the cwd or a subprocess.
REPO = Path(__file__).resolve().parents[2]
FIRST_RUN = REPO / "skills" / "_shared" / "first-run.md"

# The 3 EXECUTED github_pr_author.py call sites (plan Task 2.2), each mapped to
# the --context it must preserve byte-for-byte (Behavior 6).
CALL_SITES = {
    "skills/tp-run-full-design/SKILL.md": "autonomous",
    "skills/tp-design-complete/SKILL.md": "manual",
    "skills/tp-revert/SKILL.md": "manual",
}

# The bare, broken pattern this design removes — github_pr_author.py invoked
# directly off $TP_ROOT (which can land on a pro cache lacking the FREE module).
_BARE_GHPA = re.compile(
    r'python3\s+"\$TP_ROOT"/skills/_shared/github_pr_author\.py'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Task 2.1 — canonical snippet in first-run.md
# --------------------------------------------------------------------------- #
def test_first_run_has_free_script_resolution_section():
    text = _read(FIRST_RUN)
    assert "Resolve a FREE _shared script" in text


def test_snippet_reaches_resolver_git_toplevel_first():
    """(a) The snippet reaches resolve_script.py via git toplevel FIRST."""
    text = _read(FIRST_RUN)
    top_idx = text.index("git rev-parse --show-toplevel")
    rs_idx = text.index("skills/_shared/resolve_script.py")
    # The git-toplevel probe is documented and precedes a resolve_script.py reach.
    assert top_idx >= 0 and rs_idx >= 0
    assert top_idx < rs_idx


def test_snippet_falls_back_to_tp_root():
    """(b) The snippet falls back to "$TP_ROOT"/skills/_shared/resolve_script.py."""
    text = _read(FIRST_RUN)
    assert re.search(
        r'"\$TP_ROOT"/skills/_shared/resolve_script\.py', text
    )


def test_snippet_delegates_to_resolver():
    """(c) The snippet delegates to the resolver to obtain the target path."""
    text = _read(FIRST_RUN)
    assert re.search(r'python3\s+"\$RS"', text)


def test_snippet_is_not_bare_tp_root_only():
    """The buggy pattern (reach the resolver via a bare $TP_ROOT only) is gone.

    A git-toplevel-first reach MUST be present; if the only way the snippet
    names resolve_script.py were under $TP_ROOT, this design's fix is absent.
    """
    text = _read(FIRST_RUN)
    assert "git rev-parse --show-toplevel" in text
    # The dogfood branch names resolve_script.py under $TOP, not only $TP_ROOT.
    assert re.search(r'"\$TOP"/skills/_shared/resolve_script\.py', text)


# --------------------------------------------------------------------------- #
# Task 2.2 — the 3 executed github_pr_author.py call sites adopt the resolver
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel_path", sorted(CALL_SITES))
def test_call_site_has_no_bare_github_pr_author(rel_path):
    """No call site still invokes bare python3 "$TP_ROOT"/.../github_pr_author.py."""
    text = _read(REPO / rel_path)
    assert not _BARE_GHPA.search(text), (
        f"{rel_path} still invokes the bare $TP_ROOT chokepoint pattern"
    )


@pytest.mark.parametrize("rel_path", sorted(CALL_SITES))
def test_call_site_resolves_via_helper(rel_path):
    """Each site reaches the chokepoint through resolve_script.py ... github_pr_author.py."""
    text = _read(REPO / rel_path)
    # The resolver is reached and delegated the github_pr_author.py basename.
    assert "resolve_script.py" in text
    assert re.search(r'python3\s+"\$RS"\s+github_pr_author\.py', text), (
        f"{rel_path} does not delegate github_pr_author.py resolution to $RS"
    )
    # And the resolved path is what gets invoked (python3 "$GHPA" ...).
    assert re.search(r'python3\s+"\$GHPA"\s+create', text), (
        f"{rel_path} does not invoke the resolved chokepoint via $GHPA"
    )


@pytest.mark.parametrize("rel_path,ctx", sorted(CALL_SITES.items()))
def test_call_site_preserves_context_tail(rel_path, ctx):
    """The create --context {manual|autonomous} -- tail is preserved unchanged."""
    text = _read(REPO / rel_path)
    assert re.search(rf'"\$GHPA"\s+create\s+--context\s+{ctx}\s+--', text), (
        f"{rel_path} lost its 'create --context {ctx} --' invocation tail"
    )


def test_call_site_resolution_is_git_toplevel_first():
    """Each site's resolution snippet reaches resolve_script.py git-toplevel-first."""
    for rel_path in CALL_SITES:
        text = _read(REPO / rel_path)
        top_idx = text.index("git rev-parse --show-toplevel")
        ghpa_idx = text.index('python3 "$RS" github_pr_author.py')
        assert top_idx < ghpa_idx, (
            f"{rel_path} resolves the chokepoint before probing the git toplevel"
        )


# --------------------------------------------------------------------------- #
# Task 5.1 — the exit guard at every call site
# --------------------------------------------------------------------------- #
# resolve_script.py fails LOUD (exit 1, diagnostic on stderr), but a command
# substitution swallows that: `GHPA="$(...)"` leaves $GHPA empty and execution
# walks on to `python3 "" create ...`. The fail-loud contract is only worth
# something if the call site actually stops. Two separate lines are required:
#
#   GHPA="$(python3 "$RS" github_pr_author.py)" || exit 1
#   [ -n "$GHPA" ] || exit 1
#
# NOT a `cmd && [ -n "$GHPA" ] || exit 1` chain — that mis-binds. When the
# capture SUCCEEDS but returns empty, the `&&` arm evaluates the test, which
# fails, and only then does `||` fire; but when the capture FAILS, the `&&`
# arm is skipped and `||` fires on the capture's own status. The two cases
# collapse into one branch that reads as if it covers both and does not.
_CAPTURE_GUARDED = re.compile(
    r'^[ \t]*GHPA="\$\(python3 "\$RS" github_pr_author\.py\)"[ \t]*\|\|[ \t]*exit 1[ \t]*$',
    re.M,
)
_NONEMPTY_GUARD = re.compile(r'^[ \t]*\[ -n "\$GHPA" \][ \t]*\|\|[ \t]*exit 1[ \t]*$', re.M)
_INVOCATION = re.compile(r'^[ \t]*python3 "\$GHPA" create\b', re.M)


@pytest.mark.parametrize("rel_path", sorted(CALL_SITES))
def test_call_site_has_exit_guard(rel_path):
    """Both guard lines are present, and BETWEEN the capture and the invocation."""
    text = _read(REPO / rel_path)

    capture = _CAPTURE_GUARDED.search(text)
    assert capture, (
        f"{rel_path}: the github_pr_author.py capture is not guarded with "
        "'|| exit 1' — a failed resolve leaves $GHPA empty and execution continues"
    )
    guard = _NONEMPTY_GUARD.search(text)
    assert guard, (
        f"{rel_path}: missing the separate '[ -n \"$GHPA\" ] || exit 1' line — "
        "a capture can succeed and still yield an empty path"
    )
    invocation = _INVOCATION.search(text)
    assert invocation, f"{rel_path}: no 'python3 \"$GHPA\" create' invocation"

    assert capture.start() < guard.start() < invocation.start(), (
        f"{rel_path}: the guards must sit BETWEEN the capture and the "
        "invocation — a guard after the invocation guards nothing"
    )

    for line in text.splitlines():
        if "$GHPA" in line and "&&" in line and "|| exit 1" in line:
            raise AssertionError(
                f"{rel_path}: guards are chained with && — that mis-binds; "
                f"use two separate lines. Offending line: {line.strip()!r}"
            )


def test_first_run_snippet_guards_target():
    """The canonical §Resolve a FREE _shared script snippet guards $TARGET too.

    This snippet is what every future call site is copied from, so an unguarded
    version propagates the bug rather than the fix.
    """
    text = _read(FIRST_RUN)
    idx = text.index("Resolve a FREE _shared script")
    match = re.search(r"```bash\n(.*?)```", text[idx:], re.DOTALL)
    assert match, "no bash snippet under §Resolve a FREE _shared script"
    snippet = match.group(1)

    capture = re.search(
        r'^TARGET="\$\(python3 "\$RS" "\$NAME"\)"[ \t]*\|\|[ \t]*exit 1', snippet, re.M
    )
    assert capture, "the canonical snippet's TARGET capture is not guarded with '|| exit 1'"
    guard = re.search(r'^\[ -n "\$TARGET" \][ \t]*\|\|[ \t]*exit 1', snippet, re.M)
    assert guard, "the canonical snippet lacks a separate '[ -n \"$TARGET\" ] || exit 1'"
    invocation = re.search(r'^python3 "\$TARGET"', snippet, re.M)
    assert invocation, "the canonical snippet no longer invokes python3 \"$TARGET\""
    assert capture.start() < guard.start() < invocation.start()

    for line in snippet.splitlines():
        if "$TARGET" in line and "&&" in line and "|| exit 1" in line:
            raise AssertionError(
                f"the canonical snippet chains its guards with &&: {line.strip()!r}"
            )


# --------------------------------------------------------------------------- #
# Task 5.2 — audit A6 is closed, in the resolver and in the living docs
# --------------------------------------------------------------------------- #
KNOWN_ISSUES = REPO / "three-pillars-docs" / "known_issues.md"
RESOLVER = REPO / "skills" / "_shared" / "resolve_script.py"


def _known_issues_section(heading: str) -> str:
    """Return one `### <heading>...` entry, up to the next `### ` heading."""
    text = _read(KNOWN_ISSUES)
    match = re.search(rf"^### {re.escape(heading)}\b.*?(?=^### |\Z)", text, re.M | re.S)
    assert match, f"known_issues.md has no {heading} entry"
    return match.group(0)


def test_a6_note_removed_from_resolver():
    """The A6 scope disclaimer is gone from resolve_script.py.

    Already green off Task 2.5 — it stands here as the regression pin. The
    resolver now probes both override roots, so a NOTE saying it does not
    would be a lie in the file most likely to be trusted.
    """
    text = _read(RESOLVER)
    assert "NOTE (scope, audit A6)" not in text
    assert "audit A6" not in text


def test_known_issues_m2_no_longer_defers_overrides():
    """M2 records the override roots as RESOLVED, not deferred.

    M2 is the entry an operator actually reads to find out whether their
    $CLAUDE_PLUGIN_ROOT / --skill-dir install is covered. Leaving the scope
    note in place after shipping the fix is worse than never having written
    it — it sends someone to a follow-up that already landed.
    """
    section = _known_issues_section("M2")
    assert "out of scope" not in section.lower(), (
        "M2 still defers the override roots to a follow-up that has now landed"
    )
    assert "resolve-script-override-roots" in section, (
        "M2 does not record which design closed the override-root gap"
    )
    # The project_context.py residual is a DIFFERENT, still-open deferral —
    # closing A6 must not sweep it away.
    assert "project_context.py" in section
