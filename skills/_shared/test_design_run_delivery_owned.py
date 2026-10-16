"""launch-role-precedence 1.7: the delivery report waits whenever a launcher is on PATH."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import design_run_delivery as drd  # noqa: E402
import design_run_routing as drr  # noqa: E402


def launcher_path(tmp_path):
    """A PATH dir whose `claude` resolves into a launcher tree (bin/ + lib/launcher/plan.py)."""
    home = tmp_path / "launcher"
    (home / "bin").mkdir(parents=True)
    (home / "lib" / "launcher").mkdir(parents=True)
    (home / "bin" / "claude").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (home / "bin" / "claude").chmod(0o755)
    (home / "lib" / "launcher" / "plan.py").write_text("", encoding="utf-8")
    pdir = tmp_path / "pathdir"
    pdir.mkdir()
    (pdir / "claude").symlink_to(home / "bin" / "claude")
    return str(pdir)


def plain_path(tmp_path):
    pdir = tmp_path / "plain"
    pdir.mkdir()
    (pdir / "claude").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (pdir / "claude").chmod(0o755)
    return str(pdir)


def owned_seen(monkeypatch, env):
    seen = []
    monkeypatch.setattr(drr, "wait_for_run",
                        lambda runner, slug, timeout, **k: seen.append(k.get("owned")) or None)
    drd.report("slug", None, 5.0, env=env)
    return seen


def test_a_launcher_on_path_without_the_marker_is_waited_for(tmp_path, monkeypatch):
    assert owned_seen(monkeypatch, {"PATH": launcher_path(tmp_path)}) == [True]


def test_no_launcher_and_no_marker_is_not_waited_for(tmp_path, monkeypatch):
    assert owned_seen(monkeypatch, {"PATH": plain_path(tmp_path)}) == [False]
    assert owned_seen(monkeypatch, {"PATH": str(tmp_path / "empty")}) == [False]


def test_the_marker_alone_still_means_owned(tmp_path, monkeypatch):
    env = {"PATH": plain_path(tmp_path), "CLAUDE_LAUNCHER_OWNED": "FOO"}
    assert owned_seen(monkeypatch, env) == [True]
