"""Subprocess tests for the round_scratch.py CLI (prepare|flush|remove|tail-check).

design: iterate-convergence-budget (Task 6.2)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "round_scratch.py"
PR = "https://github.com/o/r/pull/42"


def _run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=60)


def _prepare(tmp_path):
    return _run("prepare", "--root", str(tmp_path), "--pr-url", PR, "--base", "b0",
                "--head", "h1", "--state", str(tmp_path / "s.json"),
                "--log", str(tmp_path / "log.md"), cwd=tmp_path)


def test_prepare_prints_round_dir(tmp_path):
    p = _prepare(tmp_path)
    assert p.returncode == 0, p.stderr
    r = Path(p.stdout.strip())
    assert r == tmp_path / "rounds" / "42" / "r1"
    m = json.loads((r / "angles.json").read_text(encoding="utf-8"))
    assert [e["model"] for e in m["angles"]] == ["opus"] * 3


def test_prepare_tail_failed_exit_2(tmp_path):
    assert _prepare(tmp_path).returncode == 0
    p = _prepare(tmp_path)
    assert p.returncode == 2
    assert json.loads(p.stdout)["reason"] == "tail-failed"


def test_prepare_rerun_limit_exit_2(tmp_path):
    for _ in range(2):
        r = Path(_prepare(tmp_path).stdout.strip())
        (r / "tail" / "envelope.json").write_text('{"action":"rerun-review"}', encoding="utf-8")
    p = _prepare(tmp_path)
    assert p.returncode == 2
    assert json.loads(p.stdout)["reason"] == "rerun-limit"


def test_prepare_bad_config_exit_2(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"review": {"angles": [
        {"name": "a", "prompt": "p", "role": "confirmer", "model": "sonnet"}]}}),
        encoding="utf-8")
    p = _run("prepare", "--root", str(tmp_path), "--pr-url", PR, "--base", "b0", "--head", "h1",
             "--state", "s", "--log", "l", "--config", str(cfg), cwd=tmp_path)
    assert p.returncode == 2
    assert json.loads(p.stdout)["reason"] == "angles-invalid"


def test_flush(tmp_path):
    log, dec = tmp_path / "log.md", tmp_path / "dec.md"
    log.write_text("a\nb\n", encoding="utf-8")
    p = _run("flush", "--log", str(log), "--decisions", str(dec), cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    assert dec.read_text(encoding="utf-8") == "a\nb\n" and log.read_text(encoding="utf-8") == ""


def test_remove_ok_and_refused(tmp_path):
    r = Path(_prepare(tmp_path).stdout.strip())
    bad = _run("remove", "--target", str(tmp_path), "--owner", str(tmp_path), cwd=tmp_path)
    assert bad.returncode == 2 and "refused" in json.loads(bad.stdout)
    ok = _run("remove", "--target", str(r), "--owner", str(tmp_path), cwd=tmp_path)
    assert ok.returncode == 0, ok.stdout
    assert not r.exists()


def test_tail_check_missing_exit_2(tmp_path):
    r = Path(_prepare(tmp_path).stdout.strip())
    p = _run("tail-check", "--round-dir", str(r), cwd=tmp_path)
    assert p.returncode == 2
    assert json.loads(p.stdout) == {"terminal": "needs-human-attention", "reason": "tail-failed"}


def _prepare_with(tmp_path, pr_url, cfg):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return _run("prepare", "--root", str(tmp_path / "root"), "--pr-url", pr_url,
                "--base", "a", "--head", "b", "--state", str(tmp_path / "s.json"),
                "--log", str(tmp_path / "l.log"), "--config", str(cfg_path), cwd=tmp_path)


def test_prepare_unsafe_angle_name_refuses_with_json_exit_2(tmp_path):
    # "my angle" passes load_angles (minLength 1) but not prepare's scratch-dir rule.
    cfg = {"review": {"angles": [{"name": "my angle", "prompt": "p",
                                  "role": "confirmer", "model": "opus"}]}}
    proc = _prepare_with(tmp_path, PR, cfg)
    assert proc.returncode == 2, proc.stderr[-300:]
    doc = json.loads(proc.stdout.strip().splitlines()[-1])
    assert doc["terminal"] == "needs-human-attention" and doc["reason"] == "prepare-refused"


def test_prepare_non_pr_url_refuses_with_json_exit_2(tmp_path):
    proc = _prepare_with(tmp_path, "not-a-pr-url", {})
    assert proc.returncode == 2, proc.stderr[-300:]
    doc = json.loads(proc.stdout.strip().splitlines()[-1])
    assert doc["terminal"] == "needs-human-attention" and doc["reason"] == "prepare-refused"
