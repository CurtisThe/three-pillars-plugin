"""Tests for role_engine under the one cheap-engine rule.

design: one-cheap-engine (Task 2.2). `resolve` follows the run (`local`), not the
retired `role_engines` block: no `--local` -> sonnet; `--local` with a backend ->
`local`; `--local` without one -> sonnet plus a note. A set `role_engines` key
changes nothing and adds one deprecation line. The CLI takes `--local` /
`--no-local`; with neither, `local` follows `TP_LOCAL` / the repo default.
Run with: TMPDIR=/home/curtis/t python3 -m pytest -n 4 skills/_shared/test_role_engine_cheap.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cheap_tier_default  # noqa: E402
import role_engine as re_  # noqa: E402

YES = lambda: True
NO = lambda: False


def test_no_local_is_sonnet():
    got = re_.resolve("review_finder", {}, available=YES, local=False)
    assert (got["engine"], got["model"], got["note"]) == ("sonnet", "sonnet", None)
    assert got["role"] == "review_finder"


def test_local_with_backend_is_local(tmp_path):
    got = re_.resolve("review_finder", {}, root=tmp_path, available=YES, local=True)
    assert (got["engine"], got["model"], got["effort"], got["note"]) == (
        "local", "haiku", "medium", None)


def test_local_no_backend_is_sonnet_with_note(tmp_path):
    got = re_.resolve("council_member", {}, root=tmp_path, available=NO, local=True)
    assert (got["engine"], got["model"]) == ("sonnet", "sonnet")
    assert got["note"] and "backend" in got["note"]


def test_role_engines_key_ignored_with_deprecation():
    cfg = {"role_engines": {"review_finder": "local"}}
    got = re_.resolve("review_finder", cfg, available=YES, local=False)
    assert got["engine"] == "sonnet"
    assert got["note"].count("deprecated:") == 1
    assert "role_engines" in got["note"]


def test_cli_local_flag(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TP_LOCAL", raising=False)
    monkeypatch.setattr(re_, "available", YES)
    assert re_.main(["resolve", "review_finder", "--root", str(tmp_path), "--local"]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "local"


def test_cli_without_flag_reads_tp_local(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    # the machine-global capability gate is not under test here
    monkeypatch.setattr(cheap_tier_default, "_gates_allow", lambda block: True)
    monkeypatch.setenv("TP_LOCAL", "on")
    assert re_.main(["resolve", "review_finder", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "local"
    monkeypatch.delenv("TP_LOCAL")
    assert re_.main(["resolve", "review_finder", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "sonnet"


def test_cli_no_local_overrides_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(re_, "available", YES)
    monkeypatch.setenv("TP_LOCAL", "on")
    assert re_.main(["resolve", "review_finder", "--root", str(tmp_path),
                     "--no-local"]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "sonnet"
