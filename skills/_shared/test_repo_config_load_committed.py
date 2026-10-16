"""test_repo_config_load_committed.py — what the fail-open config readers get back.

PR #170 r1 regressions, on a real committed `.three-pillars/config.json`:
  * a non-UTF-8 file (UTF-16 + BOM from a PowerShell 5 `>`, a stray latin-1 byte)
    raised UnicodeDecodeError — a ValueError, not the OSError caught — through every
    reader that documents fail-open (`load_repo_config` "never raises");
  * `review.living_doc_handres_preserves_approval` was not in the schema, so the
    gate's HEAD read pruned it and the documented `false` opt-out was ignored.

Stdlib + pytest only; repos built with the shared `fixtures/base_sync_repo` helper.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "skills" / "_shared" / "fixtures", ROOT / "skills" / "tp-pr-iterate" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deterministic_gate  # noqa: E402
import living_doc_carry  # noqa: E402
import repo_config_load  # noqa: E402
import run_round  # noqa: E402
from base_sync_repo import write_bytes_and_commit  # noqa: E402


@pytest.fixture
def committed(tmp_path, monkeypatch):
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "t@t")

    def build(data: bytes) -> Path:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        write_bytes_and_commit(tmp_path, ".three-pillars/config.json", data, "config")
        return tmp_path
    return build


def _run_round_cli(repo: Path):
    payload = json.dumps({"state": {}, "head_sha": "abc", "codereview_findings": [],
                          "unresolved_actionable": 0, "pr_url": "https://github.com/o/r/pull/1"})
    proc = subprocess.run([sys.executable, str(Path(run_round.__file__))], input=payload,
                          cwd=repo, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)["status"]


READERS = {
    "worktree": (lambda r: repo_config_load.load_repo_config(r).status, "unreadable"),
    "head": (lambda r: repo_config_load.load_repo_config(r, source="head").status, "unreadable"),
    "gate": (lambda r: deterministic_gate._load_repo_config(repo_root=str(r)), {}),
    "run_round": (run_round._load_repo_config, None),
    "run_round_cli": (_run_round_cli, (0, "ok")),
}


@pytest.mark.parametrize("data", ['{"schema_version": 1}'.encode("utf-16"),
                                  b'{"schema_version": 1, "ci": {"gate_command": "caf\xe9"}}'],
                         ids=["utf16", "latin1"])
@pytest.mark.parametrize("reader", sorted(READERS))
def test_non_utf8_config_fails_open(committed, reader, data):
    read, expected = READERS[reader]
    assert read(committed(data)) == expected


@pytest.mark.parametrize("value,enabled", [(False, False), ("no", True)])
def test_gate_config_load_keeps_the_handres_opt_out(committed, value, enabled):
    repo = committed(json.dumps({"schema_version": 1, "review": {
        "approval_survives_safe_base_sync": True,
        "living_doc_handres_preserves_approval": value}}).encode())
    gate_cfg = deterministic_gate._load_repo_config(str(repo))
    assert living_doc_carry.carry_livingdoc_handres_enabled(gate_cfg) is enabled
