"""Task 1.4: the `review.proof_neutral_carry` config key (default ON).

`proof_neutral_carry.proof_neutral_carry_enabled` mirrors `living_doc_carry.carry_livingdoc_handres_enabled`:
it is False only on a literal `False`, and True for every other shape, including a malformed
config. The opt-out must also survive the gate's committed-HEAD load, which prunes any key the
schema does not declare. The oracle is example-based.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures"))
import deterministic_gate  # noqa: E402
import proof_neutral_carry as pnc  # noqa: E402
from base_sync_repo import write_bytes_and_commit  # noqa: E402

SCHEMA_PATH = HERE / "repo-config.schema.json"


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


@pytest.mark.parametrize("config", [
    None, {}, [], {"review": {}}, {"review": "x"}, {"review": []},
    {"review": {"proof_neutral_carry": True}},
    {"review": {"proof_neutral_carry": "false"}},
    {"review": {"proof_neutral_carry": 0}},
    {"review": {"proof_neutral_carry": None}},
    "false", 0,
], ids=repr)
def test_reader_is_on_for_everything_but_a_literal_false(config):
    assert pnc.proof_neutral_carry_enabled(config) is True


def test_reader_is_off_only_for_a_literal_false():
    assert pnc.proof_neutral_carry_enabled({"review": {"proof_neutral_carry": False}}) is False


def test_reader_never_raises_on_a_hostile_config():
    class Boom(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")
    assert pnc.proof_neutral_carry_enabled(Boom()) is True


def test_schema_declares_the_key_as_a_boolean():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    spec = schema["properties"]["review"]["properties"]["proof_neutral_carry"]
    assert spec["type"] == "boolean"
    assert spec["description"]


@pytest.mark.parametrize("value,enabled", [(False, False), (True, True), ("no", True)])
def test_gate_config_load_keeps_the_opt_out(committed, value, enabled):
    repo = committed(json.dumps({"schema_version": 1, "review": {
        "proof_neutral_carry": value}}).encode())
    gate_cfg = deterministic_gate._load_repo_config(str(repo))
    assert pnc.proof_neutral_carry_enabled(gate_cfg) is enabled
