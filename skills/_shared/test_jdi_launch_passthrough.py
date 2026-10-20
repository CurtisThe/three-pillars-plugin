"""Hermetic tests for the weight-class pass-through: the class rides design.md.

A design run is launched with no class on the command line at all — the
launcher has no class option, the slash command it builds carries none, and
Tier 1 reads the class back out of ``design.md``'s frontmatter. So the class
can never be argued into a run by launch args; the artifact is the only carrier.

No fixture repo is needed (nothing here shells out to git). Entry points:
``launch_design_run.build_parser``, ``design_run_command.slash_command`` and
``weight_class.read_class``.
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design_run_command as drc  # noqa: E402
import launch_design_run as ldr  # noqa: E402
import weight_class as wc  # noqa: E402


def _jdi_design(tmp_path: Path) -> Path:
    """A tmp design dir whose design.md declares just-do-it."""
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "design.md").write_text(
        "---\nweight-class: just-do-it\nslug: fixture\n---\n\n"
        "# fixture — design\n",
        encoding="utf-8",
    )
    return d


# --- the launcher has no class option --------------------------------------


def test_launch_parser_rejects_a_weight_class_flag():
    try:
        ldr.build_parser().parse_args(["foo", "--weight-class", "just-do-it"])
    except SystemExit:
        return
    raise AssertionError("launch_design_run accepted a --weight-class flag")


def test_launch_parser_has_no_class_shaped_option():
    # The rejection above is about the class flag, not a broken parser: no
    # option name mentions the class or its weight, in any spelling.
    names = []
    for action in ldr.build_parser()._actions:
        names.extend(action.option_strings)
    forbidden = ("--weight-class", "--class", "--weight", "--jdi")
    assert not [n for n in names if n in forbidden], names


def test_launch_parser_still_parses_a_plain_slug():
    # The rejection above is about the class flag, not a broken parser.
    ns = ldr.build_parser().parse_args(["foo"])
    assert ns.slug == "foo"


# --- the slash command carries no class ------------------------------------


def test_slash_command_carries_no_class_with_skip_design():
    assert shlex.split(drc.slash_command("foo", skip_design=True)) == [
        "/tp-run-full-design", "foo", "--skip-design",
    ]


def test_slash_command_bare_has_no_class():
    assert shlex.split(drc.slash_command("foo")) == ["/tp-run-full-design", "foo"]


def test_slash_command_never_names_the_class_in_any_combination():
    for skip_design in (False, True):
        for local in (False, True):
            for cheap in (None, "on", "ab"):
                cmd = drc.slash_command(
                    "foo", mode="M", skip_design=skip_design, local=local,
                    cheap_tier=cheap,
                )
                assert "weight-class" not in cmd and "just-do-it" not in cmd, cmd


# --- Tier 1 reads the class from design.md ---------------------------------


def test_read_class_reads_just_do_it_from_frontmatter(tmp_path):
    assert wc.read_class(_jdi_design(tmp_path)) == ("just-do-it", "frontmatter")


def test_read_class_without_design_md_fails_safe_to_full(tmp_path):
    assert wc.read_class(tmp_path / "absent") == ("full", "default")
