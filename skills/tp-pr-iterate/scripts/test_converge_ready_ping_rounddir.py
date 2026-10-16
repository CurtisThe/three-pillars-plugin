"""Ready-ping wiring on the converge `--round-dir` path (pr-ready-ping Task 1.8).

The audit finding: the ready ping was wired only on the legacy `--angle-file`
tail of `converge_cli.main`, so the primary `--round-dir` path finished a clean
round with no ping at all. With no seams, the CLI hands `converge_rounddir.run`
a seams dict whose `ready_ping_fn` is the real `ready_ping.ping_ready`; with an
explicit seams dict the dict reaches `run` unchanged (no `ready_ping_fn` added).

Hermetic — `converge_rounddir.run` is replaced by a recorder; no gh, no network.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_SHARED = HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import converge_cli  # noqa: E402
import ready_ping  # noqa: E402 — skills/_shared, on sys.path via converge's shim


def _config_file(tmp_path) -> str:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({}), encoding="utf-8")
    return str(config_file)


def _recorder(monkeypatch):
    captured = {}

    def fake_run(round_dir, *, config, state_arg=None, class_log_path=None, seams=None):
        captured["round_dir"] = round_dir
        captured["seams"] = seams
        return 0

    monkeypatch.setattr(converge_cli.converge_rounddir, "run", fake_run)
    return captured


def test_round_dir_with_no_seams_wires_ping_ready(tmp_path, monkeypatch):
    captured = _recorder(monkeypatch)
    rc = converge_cli.main(["--round-dir", str(tmp_path),
                            "--config", _config_file(tmp_path)])
    assert rc == 0
    seams = captured["seams"]
    assert isinstance(seams, dict)
    assert seams["ready_ping_fn"] is ready_ping.ping_ready


def test_round_dir_with_explicit_seams_passes_them_through(tmp_path, monkeypatch):
    captured = _recorder(monkeypatch)
    seams = {"out": io.StringIO()}
    rc = converge_cli.main(["--round-dir", str(tmp_path),
                            "--config", _config_file(tmp_path)], seams=seams)
    assert rc == 0
    assert captured["seams"] == seams
    assert "ready_ping_fn" not in captured["seams"]
