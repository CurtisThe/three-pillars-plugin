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
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())


REPO = _repo_root()
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
