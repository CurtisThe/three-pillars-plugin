"""Tests for the role_engine CLI — the resolve subcommand and the decisions line.

design: local-role-routing (Task 1.3). `main(["resolve", role, ...])` prints one
JSON line equal to `resolve(...)` and returns 0; a role outside `ENGINE_ROLES`
returns 2. `--root` picks the repo whose `.three-pillars/config.json` is the
default config source (so a bare call reads the repo's own config), and
`load_config` returns `{}` for a missing or unparseable file rather than raising,
so every role resolves `opus`. `--decisions D` appends
`[role-engine] <role> → <engine> (<model>)[: <note>]` once per role: a second
identical call leaves `D` byte-unchanged. The backend probe is read off the
module at call time (`role_engine.available`) and injected — `local_backend`
itself is never mocked.
Run with: TMPDIR=/home/curtis/t python3 -m pytest -n 4 skills/_shared/test_role_engine_cli.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import role_engine as re_  # noqa: E402

YES = lambda: True  # the backend is installed (injected probe, never mocked)
NO = lambda: False

ARROW = "→"  # the decisions line's arrow is U+2192


def _repo(tmp_path, *pairs, local_model=None, block=False):
    """A tmp repo whose own config maybe holds a (deprecated) `role_engines` block."""
    conf = {"role_engines": dict(pairs)} if block else {}
    if local_model is not None:
        conf["local_implement"] = {"enabled": True, "model": local_model}
    (tmp_path / ".three-pillars").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".three-pillars" / "config.json").write_text(
        json.dumps(conf), encoding="utf-8"
    )
    return tmp_path


def _config_file(tmp_path, *pairs):
    """A standalone `--config` file; the `role_engines` pairs are retired, so it is `{}`."""
    path = tmp_path / "role-engines.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_tp_local(monkeypatch):
    """This machine's shell exports TP_LOCAL=on; the flagless default is not under test."""
    monkeypatch.delenv("TP_LOCAL", raising=False)


def _resolve_args(role, config=None, root=None, decisions=None, local=True):
    args = ["resolve", role, "--local" if local else "--no-local"]
    if config is not None:
        args += ["--config", str(config)]
    if root is not None:
        args += ["--root", str(root)]
    if decisions is not None:
        args += ["--decisions", str(decisions)]
    return args


# --- the resolve subcommand: one JSON line, exit 0 ---------------------------

def test_resolve_prints_one_json_line_equal_to_resolve(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    cfg = _config_file(tmp_path, ("council_member", "local"))
    rc = re_.main(_resolve_args("council_member", config=cfg, root=tmp_path))
    expected = re_.resolve(
        "council_member",
        {},
        root=tmp_path,
        available=YES,
        local=True,
    )
    printed = capsys.readouterr().out
    assert rc == 0
    assert printed.strip().splitlines() == [json.dumps(expected)]
    assert json.loads(printed) == expected


def test_a_bare_call_reads_the_repo_s_own_config(tmp_path, capsys, monkeypatch):
    """No `--config`: the config comes from `<root>/.three-pillars/config.json`."""
    monkeypatch.setattr(re_, "available", YES)
    root = _repo(tmp_path, ("council_member", "local"))
    rc = re_.main(_resolve_args("council_member", root=root))
    got = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert (got["engine"], got["model"], got["effort"], got["note"]) == (
        "local",
        "haiku",
        "medium",
        None,
    )


def test_a_role_outside_engine_roles_returns_2(tmp_path, capsys):
    cfg = _config_file(tmp_path, ("synthesizer", "local"))
    assert re_.main(_resolve_args("synthesizer", config=cfg, root=tmp_path)) == 2
    assert capsys.readouterr().out.strip() == ""


# --- the decisions line, written once per role -------------------------------

def test_decisions_line_is_appended_and_not_repeated(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    cfg = _config_file(tmp_path, ("council_member", "local"))
    dec = tmp_path / "decisions.md"
    args = _resolve_args("council_member", config=cfg, root=tmp_path, decisions=dec)
    assert re_.main(args) == 0
    assert dec.read_text(encoding="utf-8") == (
        f"[role-engine] council_member {ARROW} local (haiku)\n"
    )
    once = dec.read_bytes()
    assert re_.main(args) == 0
    assert dec.read_bytes() == once  # the same line is never appended twice


def test_decisions_line_carries_the_note_when_one_is_set(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    root = _repo(tmp_path, ("council_member", "local"), local_model="qwen3-coder")
    dec = tmp_path / "decisions.md"
    rc = re_.main(_resolve_args("council_member", root=root, decisions=dec))
    assert rc == 0
    assert dec.read_text(encoding="utf-8") == (
        f"[role-engine] council_member {ARROW} local (haiku): role-engine: local "
        "model qwen3-coder is not an Agent alias; using haiku\n"
    )


def test_decisions_line_records_the_sonnet_fallback(tmp_path, capsys, monkeypatch):
    """With no backend the resolved engine is still visible in the line."""
    monkeypatch.setattr(re_, "available", NO)
    cfg = _config_file(tmp_path, ("review_finder", "local"))
    dec = tmp_path / "decisions.md"
    rc = re_.main(_resolve_args("review_finder", config=cfg, root=tmp_path, decisions=dec))
    assert rc == 0
    assert dec.read_text(encoding="utf-8") == (
        f"[role-engine] review_finder {ARROW} sonnet (sonnet): "
        "M51: tp-local backend absent; cheap site falls back to sonnet\n"
    )


def test_a_missing_decisions_file_is_created_where_its_parent_is_missing(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(re_, "available", YES)
    cfg = _config_file(tmp_path, ("context_scout", "local"))
    dec = tmp_path / "design-dir" / "decisions.md"
    assert re_.main(_resolve_args("context_scout", config=cfg, root=tmp_path,
                                  decisions=dec)) == 0
    assert dec.read_text(encoding="utf-8") == (
        f"[role-engine] context_scout {ARROW} local (haiku)\n"
    )


def test_an_existing_decisions_file_keeps_its_content(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    cfg = _config_file(tmp_path, ("review_finder", "local"))
    dec = tmp_path / "decisions.md"
    dec.write_text("# decisions\n\n- a prior row\n", encoding="utf-8")
    assert re_.main(_resolve_args("review_finder", config=cfg, root=tmp_path,
                                  decisions=dec)) == 0
    lines = dec.read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["# decisions", "", "- a prior row"]
    assert lines[-1] == f"[role-engine] review_finder {ARROW} local (haiku)"


# --- load_config: raw JSON, missing or unparseable -> {} ---------------------

def test_load_config_reads_the_block_itself(tmp_path):
    root = _repo(tmp_path, ("review_finder", "local"), local_model="haiku", block=True)
    assert re_.load_config(root) == {
        "role_engines": {"review_finder": "local"},
        "local_implement": {"enabled": True, "model": "haiku"},
    }


def test_load_config_returns_empty_dict_when_the_file_is_missing(tmp_path):
    assert re_.load_config(tmp_path) == {}
    assert re_.load_config(tmp_path / "nope") == {}


def test_load_config_returns_empty_dict_when_the_file_is_unparseable(tmp_path):
    conf = tmp_path / ".three-pillars"
    conf.mkdir(parents=True)
    (conf / "config.json").write_text("{not json at all", encoding="utf-8")
    assert re_.load_config(tmp_path) == {}


def test_an_unparseable_config_never_raises_from_the_cli(tmp_path, capsys, monkeypatch):
    """`{}` config means every role follows the run, with no note and exit 0."""
    monkeypatch.setattr(re_, "available", YES)
    conf = tmp_path / ".three-pillars"
    conf.mkdir(parents=True)
    (conf / "config.json").write_text("{not json at all", encoding="utf-8")
    assert re_.main(_resolve_args("council_member", root=tmp_path, local=False)) == 0
    got = json.loads(capsys.readouterr().out)
    assert (got["engine"], got["model"], got["note"]) == ("sonnet", "sonnet", None)
