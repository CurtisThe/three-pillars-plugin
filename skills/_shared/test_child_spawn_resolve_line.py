"""Tests for `child_spawn_ops._resolve_inner` — the no-transcript line names the polled dirs.

design: child-spawn-profile-inherit task 1.2. When a child's inner transcript never appears, the
`why` the site acts on is the only evidence of where the poll looked. A child that answered under a
sibling profile was invisible to a scan of one config dir, so both no-transcript reasons end by
naming every dir they polled. Examples are spec-derived (oracle: `example`, per
`skills/_shared/test-fragility.md` §5): a plain tmp config dir, a profile dir with a sibling
profile, and a host that exited before any transcript appeared. `TP_CHILD_RESOLVE_S` is short and
no transcript is ever written, so nothing here launches a host, a router or `claude`.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_proc  # noqa: E402
import child_spawn_ops  # noqa: E402

AGENT_REF = "three-pillars:tp-runbook"
MODEL = "haiku"
CHILD = "child0123"


def test_timeout_names_the_config_dir(monkeypatch, tmp_path) -> None:
    """(f) The one config dir polled is named in the reason."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("TP_CHILD_RESOLVE_S", "0.2")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))

    res, why = child_spawn_ops._resolve_inner(CHILD, AGENT_REF, MODEL)

    assert res is None
    assert why.startswith("no inner transcript within 0.2s")
    assert str(tmp_path / "cfg") in why


def test_timeout_names_sibling_profiles(monkeypatch, tmp_path) -> None:
    """(g) A profile config dir means the sibling profiles were polled too, and all are named."""
    profiles = tmp_path / ".claude-profiles"
    aris = profiles / "aris"
    personal = profiles / "personal"
    aris.mkdir(parents=True)
    personal.mkdir(parents=True)
    monkeypatch.setenv("TP_CHILD_RESOLVE_S", "0.2")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(aris))

    res, why = child_spawn_ops._resolve_inner(CHILD, AGENT_REF, MODEL)

    assert res is None
    assert why.startswith("no inner transcript within 0.2s")
    assert str(aris) in why
    assert str(personal) in why


def test_dead_host_names_the_polled_dir(monkeypatch, tmp_path) -> None:
    """(h) The early exit keeps its prefix and still names where it looked."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("TP_CHILD_RESOLVE_S", "0.2")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(child_proc, "alive", lambda *a, **k: False)

    res, why = child_spawn_ops._resolve_inner(CHILD, AGENT_REF, MODEL, pid=1, ticks=1)

    assert res is None
    assert why.startswith("host exited before an inner transcript appeared")
    assert str(tmp_path / "cfg") in why
