#!/usr/bin/env python3
"""test_trust_boundary_brief.py — which brief a reviewed repo gets (Behavior 7).

design: review-convergence (detailed-design-security.md, Task 3.3)

A repo with a `SECURITY.md` at its toplevel gets that file; any other repo gets the
checklist shipped beside the module. The plugin's own checkout is never the source of
a brief, and the shipped checklist is a real brief: one section per surface, the bar
verbatim, and no plugin-internal path named in it.
"""
from __future__ import annotations

from pathlib import Path

import trust_boundary as tb

FORBIDDEN = ("skills/", "ci-local", "review-instructions", "framework-check",
             ".three-pillars")


def _plugin_security_md() -> Path:
    """This repo's own SECURITY.md, if the checkout has one."""
    return Path(tb.__file__).resolve().parents[2] / "SECURITY.md"


def test_repo_without_security_md_gets_the_checklist(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    assert tb.brief_path(root) == tb.CHECKLIST


def test_repo_with_security_md_gets_it(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    security = root / "SECURITY.md"
    security.write_text("# Security\n", encoding="utf-8")
    assert tb.brief_path(root) == security


def test_security_md_as_a_directory_is_not_a_brief(tmp_path):
    root = tmp_path / "repo"
    (root / "SECURITY.md").mkdir(parents=True)
    assert tb.brief_path(root) == tb.CHECKLIST


def test_a_string_root_is_accepted(tmp_path):
    assert tb.brief_path(str(tmp_path)) == tb.CHECKLIST


def test_the_plugin_checkout_is_never_the_brief(tmp_path):
    """repo_root is the reviewed repo, so this repo's own file cannot come back."""
    assert tb.brief_path(tmp_path) != _plugin_security_md()


def test_checklist_is_shipped_next_to_the_module():
    assert tb.CHECKLIST == Path(tb.__file__).resolve().parent / (
        "trust-boundary-checklist.md")
    assert tb.CHECKLIST.is_file()


def test_checklist_has_one_section_per_surface():
    headings = {ln.strip() for ln in tb.CHECKLIST.read_text(encoding="utf-8").split(
        "\n") if ln.startswith("## ")}
    assert headings == {f"## {name}" for name in tb.SURFACES} | {"## The bar"}


def test_checklist_states_the_bar_verbatim_on_one_line():
    lines = tb.CHECKLIST.read_text(encoding="utf-8").split("\n")
    assert tb.SECURITY_BAR in lines
    assert lines.count(tb.SECURITY_BAR) == 1


def test_checklist_names_no_plugin_internal_file():
    text = tb.CHECKLIST.read_text(encoding="utf-8")
    for needle in FORBIDDEN:
        assert needle not in text


def test_checklist_gives_each_surface_a_check_and_a_fix():
    text = tb.CHECKLIST.read_text(encoding="utf-8")
    for label in ("**Attacker controls:**", "**Check:**", "**Fix:**"):
        assert text.count(label) == len(tb.SURFACES)


def test_checklist_stays_a_brief():
    lines = tb.CHECKLIST.read_text(encoding="utf-8").rstrip("\n").split("\n")
    assert len(lines) < 100
    over = [ln for ln in lines if len(ln) > 200]
    assert over == [tb.SECURITY_BAR] or over == []
