"""retro_gate: the design-learn retro step is off unless retro.enabled is true."""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import retro_gate  # noqa: E402


def _write(repo, cfg):
    d = repo / ".three-pillars"
    d.mkdir()
    (d / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


@pytest.mark.parametrize("cfg,code,word", [
    (None, 1, "retro: off"),
    ({"schema_version": 1}, 1, "retro: off"),
    ({"schema_version": 1, "retro": {"enabled": False}}, 1, "retro: off"),
    ({"schema_version": 1, "retro": {"enabled": True}}, 0, "retro: on"),
])
def test_gate_exit_and_output(tmp_path, capsys, cfg, code, word):
    if cfg is not None:
        _write(tmp_path, cfg)
    assert retro_gate.main(["--repo", str(tmp_path)]) == code
    assert word in capsys.readouterr().out


def test_skill_doc_names_gate():
    text = (HERE.parent / "tp-design-learn" / "SKILL.md").read_text(encoding="utf-8")
    assert "retro_gate.py" in text
    assert "retro.enabled" in text
