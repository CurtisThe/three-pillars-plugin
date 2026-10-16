"""test_launch_design_run_resolver.py — launcher delegates to the shared
cheap_tier_default resolver instead of carrying its own copy of the logic."""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cheap_tier_default  # noqa: E402
import launch_design_run as ldr  # noqa: E402


def test_launcher_reuses_the_shared_resolver():
    assert ldr.default_cheap_tier is cheap_tier_default.default_mode
    assert ldr.cheap_tier_warning is cheap_tier_default.is_drop_warning


def test_launcher_has_one_resolution_path():
    source = inspect.getsource(ldr)
    assert "def default_cheap_tier" not in source
    assert "def cheap_tier_warning" not in source
    assert "cheap_tier_default.resolve(" not in source
    assert "cheap_deprecation.notes(" in source
