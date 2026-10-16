"""test_child_state_cache.py — where a probe verdict and a smoke pass are cached.

strata-session-isolation task 2.3, plus strata-classifier-cost-followups task 1.4: a smoke **pass**
is cached per `claude --version` **and** the permission mode it was earned in (`mode=`) in
`<common>/tp-children/smoke.json`, so a later run on the same claude does not smoke again, and a
pass recorded under `auto` never answers a `dontAsk` probe. A probe
result — and a smoke *failure* — is cached only in the run's own `probe.json`, so the next run has
no verdict of its own and re-smokes. Both caches go through `write`/`read`, so a missing, corrupt or
foreign-version entry answers `None` (re-probe), never a crash and never a stale verdict. The two
files also stay out of the sweep view: `children` ignores the run's `probe.json`, `all_run_dirs`
ignores `smoke.json` because it sits beside the run dirs, not inside one. `at` is a timestamp — the
test only proves one is recorded, never its value.

No repo, no `claude`, no GPU here: a run dir and a common dir are `tmp_path` subdirs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import child_state  # noqa: E402

VERSION = "2.1.296"
OTHER = "2.1.297"
RUN8 = "abcdef01"


def test_probe_cache_roundtrip(tmp_path: Path) -> None:
    run = tmp_path / RUN8
    run.mkdir()
    empty = tmp_path / "empty"
    empty.mkdir()

    child_state.write_probe(run, {"mode": "child", "why": "smoke ok"})

    assert child_state.probe_cache(run) == {"mode": "child", "why": "smoke ok"}
    assert (run / child_state.PROBE_CACHE).is_file()
    assert child_state.probe_cache(empty) is None
    assert child_state.probe_cache(tmp_path / "absent") is None


def test_smoke_pass_keyed_by_version_and_mode(tmp_path: Path) -> None:
    """task 1.4: the key is `claude --version` AND the permission mode the pass was earned in."""
    common = tmp_path / "common"
    (common / child_state.CHILDREN_DIR).mkdir(parents=True)

    child_state.write_smoke(common, VERSION, {"ok": True, "why": "token + exit 0"},
                            mode="dontAsk")

    got = child_state.smoke_cache(common, VERSION, mode="dontAsk")
    assert got is not None
    assert set(got) == {"claude_version", "permission_mode", "ok", "why", "at"}
    assert got["claude_version"] == VERSION
    assert got["permission_mode"] == "dontAsk"
    assert got["ok"] is True
    assert child_state.smoke_cache(common, OTHER, mode="dontAsk") is None
    assert child_state.smoke_cache(common, VERSION, mode="auto") is None
    assert (common / child_state.CHILDREN_DIR / child_state.SMOKE_CACHE).is_file()
    assert child_state.all_run_dirs(common) == []


def test_smoke_pass_written_before_the_mode_key_is_a_miss(tmp_path: Path) -> None:
    """An entry with no `permission_mode` key (written before task 1.4) never answers a probe."""
    common = tmp_path / "common"
    children = common / child_state.CHILDREN_DIR
    children.mkdir(parents=True)
    (children / child_state.SMOKE_CACHE).write_text(
        json.dumps({"claude_version": VERSION, "ok": True, "why": "token + exit 0",
                    "at": "2026-10-01T00:00:00+00:00"}), encoding="utf-8")

    assert child_state.smoke_cache(common, VERSION, mode="dontAsk") is None
    assert child_state.smoke_cache(common, VERSION, mode="auto") is None


def test_failed_smoke_not_in_smoke_json(tmp_path: Path) -> None:
    common = tmp_path / "common"
    children = common / child_state.CHILDREN_DIR
    children.mkdir(parents=True)
    run = children / RUN8
    run.mkdir()

    child_state.write_smoke(common, VERSION, {"ok": False, "why": "inner tools"}, mode="dontAsk")

    assert child_state.smoke_cache(common, VERSION, mode="dontAsk") is None
    assert not (children / child_state.SMOKE_CACHE).exists()

    child_state.write_probe(run, {"mode": "in-process", "why": "smoke failed: inner tools"})

    assert child_state.probe_cache(run)["why"] == "smoke failed: inner tools"
    assert child_state.smoke_cache(common, VERSION, mode="dontAsk") is None
    assert [p.name for p in child_state.children(run)] == []
