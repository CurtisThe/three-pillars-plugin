"""finder_round CLIs: mark-unparseable and put-dispositions (local-role-routing 6.4)."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import finder_round  # noqa: E402


def _round(tmp_path):
    entries = [
        {"name": "security", "advisory": True},
        {"name": "style", "advisory": True},
        {"name": "plain"},
        {"name": "opus-check", "role": "confirmer"},
    ]
    (tmp_path / "angles.json").write_text(json.dumps({"angles": entries}), encoding="utf-8")
    return tmp_path


def _manifest(r):
    return json.loads((r / "angles.json").read_text(encoding="utf-8"))["angles"]


def test_mark_unparseable_only_that_entry(tmp_path):
    r = _round(tmp_path)
    rc = finder_round.main(["mark-unparseable", "--round-dir", str(r), "--angle", "security"])
    assert rc == 0
    m = {e["name"]: e for e in _manifest(r)}
    assert m["security"]["unparseable"] == "re-covered-by-opus-check"
    assert all("unparseable" not in e for n, e in m.items() if n != "security")
    assert sorted(os.listdir(r)) == ["angles.json"]


@pytest.mark.parametrize("angle", ["opus-check", "plain", "nope"])
def test_mark_unparseable_refuses(tmp_path, angle, capsys):
    r = _round(tmp_path)
    before = (r / "angles.json").read_bytes()
    rc = finder_round.main(["mark-unparseable", "--round-dir", str(r), "--angle", angle])
    assert rc != 0
    assert (r / "angles.json").read_bytes() == before
    assert capsys.readouterr().err.strip()
    assert sorted(os.listdir(r)) == ["angles.json"]


def test_put_dispositions_writes_sidecar(tmp_path, monkeypatch):
    payload = {"dropped": [{"from": "security#0", "class": "P"}, "style#1"]}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rc = finder_round.main(["put-dispositions", "--round-dir", str(tmp_path)])
    assert rc == 0
    out = tmp_path / "opus-check" / "dispositions.json"
    assert json.loads(out.read_text(encoding="utf-8")) == payload
    assert os.listdir(tmp_path / "opus-check") == ["dispositions.json"]


@pytest.mark.parametrize("bad", ["{not json", "[]", '{"dropped": 3}', '{"dropped": [3]}'])
def test_put_dispositions_bad_input(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(sys, "stdin", io.StringIO(bad))
    rc = finder_round.main(["put-dispositions", "--round-dir", str(tmp_path)])
    assert rc != 0
    assert not (tmp_path / "opus-check" / "dispositions.json").exists()


def test_subprocess_put_dispositions(tmp_path):
    script = Path(finder_round.__file__)
    p = subprocess.run(
        [sys.executable, str(script), "put-dispositions", "--round-dir", str(tmp_path)],
        input='{"dropped": []}', text=True, capture_output=True,
    )
    assert p.returncode == 0
    assert (tmp_path / "opus-check" / "dispositions.json").exists()
