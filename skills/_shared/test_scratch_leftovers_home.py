"""The $HOME scan reports a new entry inside the config, cache and share dirs (run-scratch-in-fence B1).

`$HOME` is scanned at depth 2 for new entries only, and a new entry inside an
already existing home directory was skipped. That skip hid `~/.config/foo` (made
through a link the create fence could not see yet). The three directories a link
usually aims at (`~/.config`, `~/.cache`, `~/.local/share`) are now judged one level
deeper: a NEW entry directly in them is reported, an old one is not, and any other
existing home directory keeps the stated new-entries-only gap.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_scratch_leftovers_noise import fx  # noqa: E402,F401  (fixture)

DEEP = [".config", ".cache", ".local/share"]


@pytest.mark.parametrize("rel", DEEP)
def test_a_new_entry_directly_inside_a_deep_home_dir_is_reported(fx, rel):
    (fx.home / rel).mkdir(parents=True)
    fx.run("provision")
    (fx.home / rel / "foo").mkdir()
    rc, out = fx.run("check")
    assert rc == 1 and str(fx.home / rel / "foo") in out, out


@pytest.mark.parametrize("rel", DEEP)
def test_an_old_entry_inside_a_deep_home_dir_is_not_reported(fx, rel):
    (fx.home / rel / "old").mkdir(parents=True)
    fx.run("provision")
    (fx.home / rel / "old" / "f").write_text("x")
    rc, out = fx.run("check")
    assert rc == 0, out


def test_another_existing_home_dir_keeps_the_new_entries_only_gap(fx):
    (fx.home / "olddir").mkdir()
    fx.run("provision")
    (fx.home / "olddir" / "new").mkdir()
    rc, out = fx.run("check")
    assert rc == 0, out


def test_the_claude_noise_name_is_this_users_dir_only(fx):
    fx.run("provision")
    (fx.tmp / ("claude-%d" % os.getuid())).mkdir()
    assert fx.run("check")[0] == 0
    (fx.tmp / "claude-other").mkdir()
    rc, out = fx.run("check")
    assert rc == 1 and str(fx.tmp / "claude-other") in out
    assert str(fx.tmp / ("claude-%d" % os.getuid())) not in out
