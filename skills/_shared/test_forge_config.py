"""The `forge` config key: record once, merge, read, prune (Task 1.7).

design: forge-interface (Phase 1). `forge_config.record_kind(repo, info)` writes
the detected forge into `.three-pillars/config.json` exactly once — it MERGES into
an existing `forge` block, so an operator-written `forge.web_base` (the ssh-alias /
custom-port setup) survives a later first-run. `read_kind` / `read_web_base` read
the block back defensively. Every write is atomic (tmp-file-and-rename in the same
dir) and the no-op path rewrites nothing. Hermetic: `tmp_path` repos only.
Run with: python3 -m pytest skills/_shared/test_forge_config.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge  # noqa: E402
import forge_config  # noqa: E402
import repo_config_load as rcl  # noqa: E402

HERE = Path(__file__).resolve().parent
SCHEMA = json.loads((HERE / "repo-config.schema.json").read_text(encoding="utf-8"))

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")


def _info(kind="gitea", host="gitea.lan", web_base="https://gitea.lan"):
    """The `ForgeInfo` a resolve produced for a Gitea origin."""
    return forge.ForgeInfo(kind, host, "acme", "widget", web_base,
                           f"{web_base}/api/v1", "")


def _config_path(repo: Path) -> Path:
    return repo / ".three-pillars" / "config.json"


def _write_config(repo: Path, data: dict) -> None:
    path = _config_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _raw(repo: Path) -> dict:
    return json.loads(_config_path(repo).read_text(encoding="utf-8"))


# --- record_kind: the first write ---------------------------------------------


def test_record_kind_writes_kind_host_recorded_at(tmp_path):
    _write_config(tmp_path, {"schema_version": 1})
    assert forge_config.record_kind(tmp_path, _info()) is True
    block = _raw(tmp_path)["forge"]
    assert block["kind"] == "gitea"
    assert block["host"] == "gitea.lan"
    assert _ISO_RE.match(block["recorded_at"]), block["recorded_at"]
    assert "web_base" not in block, "no web_base argument must not write the key"


def test_record_kind_keeps_every_other_top_level_key(tmp_path):
    before = {
        "schema_version": 1,
        "ci": {"expects_github_checks": False, "gate_command": None},
        "review": {"automation_identities": ["curtisthebot"]},
        "models": {"review": "opus"},
    }
    _write_config(tmp_path, before)
    assert forge_config.record_kind(tmp_path, _info()) is True
    after = _raw(tmp_path)
    assert after["schema_version"] == 1
    for key in ("ci", "review", "models"):
        assert after[key] == before[key], key
    assert after["forge"]["kind"] == "gitea"


def test_record_kind_creates_the_directory_and_a_lone_file(tmp_path):
    assert forge_config.record_kind(tmp_path, _info()) is True
    names = sorted(p.name for p in (tmp_path / ".three-pillars").iterdir())
    assert names == ["config.json"], names
    assert _raw(tmp_path)["forge"]["kind"] == "gitea"


def test_record_kind_writes_web_base_when_given(tmp_path):
    ok = forge_config.record_kind(
        tmp_path, _info(), web_base="https://truenas.home.arpa:30008")
    assert ok is True
    assert _raw(tmp_path)["forge"]["web_base"] == "https://truenas.home.arpa:30008"


# --- record_kind: merge, never replace ----------------------------------------


def test_record_kind_merges_into_an_operator_written_block(tmp_path):
    """The ssh-alias setup: the operator set `web_base` before any first-run."""
    _write_config(tmp_path, {
        "schema_version": 1,
        "review": {"require_human_approval": True},
        "forge": {"web_base": "https://h:30008"},
    })
    assert forge_config.record_kind(tmp_path, _info()) is True
    block = _raw(tmp_path)["forge"]
    assert block["kind"] == "gitea"
    assert block["host"] == "gitea.lan"
    assert _ISO_RE.match(block["recorded_at"]), block["recorded_at"]
    assert block["web_base"] == "https://h:30008", "an operator value must survive"
    assert _raw(tmp_path)["review"] == {"require_human_approval": True}


def test_record_kind_never_writes_web_base_null(tmp_path):
    _write_config(tmp_path, {"schema_version": 1,
                             "forge": {"web_base": "https://h:30008"}})
    assert forge_config.record_kind(tmp_path, _info(), web_base=None) is True
    assert _raw(tmp_path)["forge"]["web_base"] == "https://h:30008"


def test_record_kind_is_a_no_op_once_kind_is_set(tmp_path):
    _write_config(tmp_path, {"schema_version": 1,
                             "forge": {"kind": "gitea", "host": "gitea.lan"}})
    before = _config_path(tmp_path).read_bytes()
    other = _info(kind="github", host="github.com", web_base="https://github.com")
    assert forge_config.record_kind(tmp_path, other) is False
    assert _config_path(tmp_path).read_bytes() == before, "no-op rewrote the file"


# --- read_kind / read_web_base ------------------------------------------------


@pytest.mark.parametrize("config,want", [
    ({"forge": {"kind": "gitea"}}, "gitea"),
    ({"forge": {"kind": "github"}}, "github"),
    ({"forge": {"kind": "other"}}, "other"),
    ({"forge": {"kind": "gitlab"}}, None),
    ({"forge": {"kind": 5}}, None),
    ({"forge": {"web_base": "https://h:30008"}}, None),
    ({"forge": None}, None),
    ({"forge": "gitea"}, None),
    ({}, None),
    (None, None),
])
def test_read_kind_returns_only_a_known_kind_or_none(config, want):
    assert forge_config.read_kind(config) == want


@pytest.mark.parametrize("config,want", [
    ({"forge": {"web_base": "https://h:30008"}}, "https://h:30008"),
    ({"forge": {"web_base": None}}, None),
    ({"forge": {"web_base": 5}}, None),
    ({"forge": {"kind": "gitea"}}, None),
    ({"forge": []}, None),
    ({}, None),
    (None, None),
])
def test_read_web_base_returns_the_string_or_none(config, want):
    assert forge_config.read_web_base(config) == want


# --- schema + prune_invalid ---------------------------------------------------


def test_written_config_validates_and_prune_keeps_the_block(tmp_path):
    pytest.importorskip("jsonschema")
    import jsonschema

    assert forge_config.record_kind(
        tmp_path, _info(), web_base="https://gitea.lan") is True
    cfg = _raw(tmp_path)
    jsonschema.validate(cfg, SCHEMA)
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["forge"] == cfg["forge"], warnings
    assert not warnings, warnings


def test_prune_drops_an_invalid_forge_kind():
    """Per-key degrade: the bad `kind` goes, the valid sibling stays."""
    pruned, warnings = rcl.prune_invalid(
        {"schema_version": 1, "forge": {"kind": "gitlab", "host": "gitlab.lan"}},
        SCHEMA)
    assert pruned["forge"] == {"host": "gitlab.lan"}, pruned
    assert any("forge.kind" in w for w in warnings), warnings
    assert forge_config.read_kind(pruned) is None


def test_web_base_only_block_is_schema_valid():
    """`web_base` with no `kind` is the ssh-alias setup — it must validate."""
    pytest.importorskip("jsonschema")
    import jsonschema

    cfg = {"schema_version": 1, "forge": {"web_base": "https://h:30008"}}
    jsonschema.validate(cfg, SCHEMA)
    pruned, warnings = rcl.prune_invalid(cfg, SCHEMA)
    assert pruned["forge"] == {"web_base": "https://h:30008"}, warnings


def test_schema_forge_block_shape():
    block = SCHEMA["properties"]["forge"]
    assert block["additionalProperties"] is False
    assert set(block["properties"]) == {"kind", "host", "web_base", "recorded_at"}
    assert block["properties"]["kind"]["enum"] == ["github", "gitea", "other"]
    assert "required" not in block
