#!/usr/bin/env python3
"""test_children_route_in_process.py — a direct run's in-process verdict carries a Sonnet model.

design: launch-role-precedence 3.15. In a direct `run` session `children_route.effective_env` makes
the route check report `routed/ok`, which turns the no-Haiku floor off. When `child_spawn.py probe`
then answers `in-process` (smoke failure, `router lacks release_session`, no `/proc`), the S1 and S2
sites run `Agent(model="{model}")` in-process with a `local-*` model, and a direct session has no
`ANTHROPIC_BASE_URL`, so the call would reach Anthropic's real Haiku. `floor_in_process(verdict,
env)` adds `"model": "sonnet"` to an `in-process` verdict of a direct run and leaves every other
verdict alone; `cmd_probe` passes its verdict through it before `write_probe`, so the cached
`probe.json` carries it; `child-spawn.md` step 3 tells a site to run the `Agent(...)` call with that
model. One test per case, example oracle (skills/_shared/test-fragility.md): the assertions name the
`model` key and the observable verdict, never an internal call order. Stdlib only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_spawn  # noqa: E402
import child_state  # noqa: E402
import children_route  # noqa: E402
from attempt_fixture import commit, git  # noqa: E402

DIRECT_ENV = {"CLAUDE_LAUNCHER_BACKEND": "direct"}
HYBRID_ENV = {"CLAUDE_LAUNCHER_BACKEND": "direct", "ANTHROPIC_BASE_URL": "http://127.0.0.1:8123"}
IN_PROCESS = {"mode": "in-process", "why": "router lacks release_session"}
CHILD = {"mode": "child", "why": "smoke passed", "dont_ask": True}
RUN = "floor0123"
DOC = (HERE / "child-spawn.md").read_text(encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """A real tmp repo with one commit, so the probe cache lands inside it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"README.md": "demo\n"}, "base")
    return repo


def _probe(monkeypatch, repo: Path, env: dict) -> tuple[dict, dict | None]:
    """`cmd_probe` with a failing prerequisite check: `(returned verdict, cached verdict)`."""
    monkeypatch.setattr(child_spawn, "_probe_checks", lambda _env: "router lacks release_session")
    verdict = child_spawn.cmd_probe(run=RUN, root=repo, env=env)
    return verdict, child_state.probe_cache(child_state.run_dir(RUN, root=repo))


def test_floor_in_process_exported():
    assert "floor_in_process" in children_route.__all__


def test_in_process_direct_run_gets_sonnet():
    out = children_route.floor_in_process(IN_PROCESS, DIRECT_ENV)
    assert out["model"] == "sonnet"
    assert out["mode"] == "in-process"
    assert out["why"] == IN_PROCESS["why"]


def test_floor_is_a_copy_not_a_mutation():
    verdict = dict(IN_PROCESS)
    out = children_route.floor_in_process(verdict, DIRECT_ENV)
    assert "model" not in verdict
    assert out is not verdict


def test_child_verdict_unchanged():
    assert children_route.floor_in_process(dict(CHILD), DIRECT_ENV) == CHILD


def test_in_process_hybrid_env_unchanged():
    """A hybrid session has a Strata route in-process, so its `local-*` model stays valid."""
    assert children_route.floor_in_process(dict(IN_PROCESS), HYBRID_ENV) == IN_PROCESS


def test_in_process_empty_env_unchanged():
    assert children_route.floor_in_process(dict(IN_PROCESS), {}) == IN_PROCESS


def test_never_raises_on_garbage():
    assert children_route.floor_in_process(None, DIRECT_ENV) is None
    assert children_route.floor_in_process(dict(IN_PROCESS), None) == IN_PROCESS


def test_cmd_probe_direct_env_returns_and_caches_sonnet(monkeypatch, tmp_path):
    verdict, cached = _probe(monkeypatch, _repo(tmp_path), DIRECT_ENV)
    assert verdict["mode"] == "in-process"
    assert verdict["model"] == "sonnet"
    assert cached is not None and cached["model"] == "sonnet"


def test_cmd_probe_non_direct_env_has_no_model(monkeypatch, tmp_path):
    verdict, cached = _probe(monkeypatch, _repo(tmp_path), HYBRID_ENV)
    assert verdict["mode"] == "in-process"
    assert "model" not in verdict
    assert cached is not None and "model" not in cached


def _step3() -> str:
    """The doc's `in-process` step: from its numbered line up to the `child` step."""
    match = re.search(r"3\.\s+\*\*`in-process`\*\*(.*?)\n4\.\s+\*\*`child`\*\*", DOC, re.S)
    assert match, "child-spawn.md lost its step 3 / step 4 shape"
    return " ".join(match.group(1).split())


def test_doc_step3_tells_a_site_to_use_the_probe_model():
    step = _step3()
    assert re.search(r"carries a `model`", step), "step 3 does not mention the probe `model`"
    assert "instead of `{model}`" in step
