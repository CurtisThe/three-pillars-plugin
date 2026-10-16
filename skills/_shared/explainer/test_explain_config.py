"""test_explain_config.py — the top-level `explainer` config block and its loader.

Covers explainer-agent plan Task 7.2 (detailed-design §Interfaces:
"explain_config.load(root) -> {"enabled": True, "publish_artifact": True,
"drafter_override": {}} merges config over defaults with drop-and-warn. Override
values may only be "opus", for pr-brief/human-escalation"):
  - no config file (or no `explainer` block) gives the defaults, silently;
  - `enabled: false` / `publish_artifact: false` turn their switch off;
  - `drafter_override: {"pr-brief": "opus"}` is kept; `{"auto-ruling": "opus"}` and
    `{"pr-brief": "sonnet"}` are dropped, each with one stderr warning; a non-bool
    `enabled` is dropped with one warning (drop-and-warn, never raise);
  - the schema has a top-level `explainer` object after the
    `local_implement`/`role_engines` pair, whose keys are the loader's keys and whose
    override kinds take only `opus`;
  - repo-config.md documents the block, its keys and its off switch.

Configs are built here in a tmp root; the schema and doc ship in skills/_shared and are
found from this file's own path, so no repo doc tree is read. Assertions are on the
returned dict, the warning count and the schema structure (skills/_shared/test-fragility.md).
"""
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_config  # noqa: E402

BLOCK = "explainer"
SCHEMA_PATH = _SHARED_DIR / "repo-config.schema.json"
DOC_PATH = _SHARED_DIR / "repo-config.md"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
DEFAULTS = {"enabled": True, "publish_artifact": True, "drafter_override": {}}


def _root(tmp_path, config) -> Path:
    """A repo root whose `.three-pillars/config.json` holds `config` (str = raw text)."""
    cfg_dir = tmp_path / ".three-pillars"
    cfg_dir.mkdir()
    text = config if isinstance(config, str) else json.dumps(config)
    (cfg_dir / "config.json").write_text(text, encoding="utf-8")
    return tmp_path


def _load(tmp_path, capsys, block):
    """`load` over a config holding `block` as `explainer`, plus the stderr lines."""
    got = explain_config.load(_root(tmp_path, {"schema_version": 1, BLOCK: block}))
    return got, capsys.readouterr().err.splitlines()


# --- load: defaults --------------------------------------------------------------

def test_no_config_file_gives_the_defaults(tmp_path, capsys):
    assert explain_config.load(tmp_path) == DEFAULTS
    assert capsys.readouterr().err == ""


def test_config_without_the_block_gives_the_defaults(tmp_path, capsys):
    root = _root(tmp_path, {"schema_version": 1, "role_engines": {"explainer": "local"}})
    assert explain_config.load(root) == DEFAULTS
    assert capsys.readouterr().err == ""


def test_each_load_returns_a_fresh_override_map(tmp_path):
    first = explain_config.load(tmp_path)
    first["drafter_override"]["pr-brief"] = "opus"
    assert explain_config.load(tmp_path) == DEFAULTS


# --- load: merge over defaults -----------------------------------------------------

@pytest.mark.parametrize("key", ["enabled", "publish_artifact"])
def test_a_false_switch_is_honoured(tmp_path, capsys, key):
    got, err = _load(tmp_path, capsys, {key: False})
    assert got == {**DEFAULTS, key: False}
    assert err == []


@pytest.mark.parametrize("kind", ["pr-brief", "human-escalation"])
def test_an_opus_override_for_a_checked_kind_is_kept(tmp_path, capsys, kind):
    got, err = _load(tmp_path, capsys, {"drafter_override": {kind: "opus"}})
    assert got == {**DEFAULTS, "drafter_override": {kind: "opus"}}
    assert err == []


# --- load: drop-and-warn -----------------------------------------------------------

@pytest.mark.parametrize("override, dropped", [
    ({"auto-ruling": "opus"}, "auto-ruling"),
    ({"pr-brief": "sonnet"}, "pr-brief"),
    ({"human-escalation": "local"}, "human-escalation"),
])
def test_a_bad_override_is_dropped_with_one_warning(tmp_path, capsys, override, dropped):
    got, err = _load(tmp_path, capsys, {"drafter_override": override})
    assert got == DEFAULTS
    assert len(err) == 1
    assert dropped in err[0] and BLOCK in err[0]


def test_a_bad_override_drops_only_itself(tmp_path, capsys):
    got, err = _load(tmp_path, capsys, {"drafter_override": {
        "pr-brief": "opus", "auto-ruling": "opus"}})
    assert got["drafter_override"] == {"pr-brief": "opus"}
    assert len(err) == 1


@pytest.mark.parametrize("key", ["enabled", "publish_artifact"])
@pytest.mark.parametrize("value", ["false", 0, None, [False]])
def test_a_non_bool_switch_is_dropped_with_one_warning(tmp_path, capsys, key, value):
    got, err = _load(tmp_path, capsys, {key: value})
    assert got == DEFAULTS
    assert len(err) == 1
    assert key in err[0]


def test_an_unknown_key_is_dropped_with_one_warning(tmp_path, capsys):
    got, err = _load(tmp_path, capsys, {"enabled": False, "drafter": "opus"})
    assert got == {**DEFAULTS, "enabled": False}
    assert len(err) == 1
    assert "drafter" in err[0]


@pytest.mark.parametrize("bad", ["opus", ["pr-brief"], None])
def test_a_non_object_override_map_is_dropped_with_one_warning(tmp_path, capsys, bad):
    got, err = _load(tmp_path, capsys, {"drafter_override": bad})
    assert got == DEFAULTS
    assert len(err) == 1


@pytest.mark.parametrize("bad", [False, "off", ["enabled"]])
def test_a_non_object_block_gives_the_defaults_with_one_warning(tmp_path, capsys, bad):
    got, err = _load(tmp_path, capsys, bad)
    assert got == DEFAULTS
    assert len(err) == 1


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_an_unreadable_config_fails_open_with_one_warning(tmp_path, capsys, text):
    # repo-config.md §Fail-open: a parse error warns once and reads as missing.
    assert explain_config.load(_root(tmp_path, text)) == DEFAULTS
    assert len(capsys.readouterr().err.splitlines()) == 1


# --- schema ------------------------------------------------------------------------

def _schema_block() -> dict:
    assert BLOCK in SCHEMA["properties"], "schema has no top-level explainer block"
    return SCHEMA["properties"][BLOCK]


def test_schema_block_shape_matches_the_loader():
    block = _schema_block()
    assert block["type"] == "object"
    assert block["additionalProperties"] is False
    assert set(block["properties"]) == set(DEFAULTS)
    for switch in ("enabled", "publish_artifact"):
        assert block["properties"][switch]["type"] == "boolean"
    override = block["properties"]["drafter_override"]
    assert override["type"] == "object"
    assert override["additionalProperties"] is False
    assert set(override["properties"]) == set(explain_config.OVERRIDE_KINDS)
    assert set(explain_config.OVERRIDE_KINDS) == {"pr-brief", "human-escalation"}
    for kind in explain_config.OVERRIDE_KINDS:
        assert override["properties"][kind]["type"] == "string"
        assert override["properties"][kind]["enum"] == ["opus"]


def test_schema_block_follows_the_local_implement_role_engines_pair():
    names = list(SCHEMA["properties"])
    pair = (names.index("local_implement"), names.index("role_engines"))
    assert abs(pair[0] - pair[1]) == 1, "local_implement and role_engines split apart"
    assert names.index(BLOCK) > max(pair)


@pytest.fixture(scope="module")
def validator():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    return jsonschema.Draft202012Validator(SCHEMA)


def _cfg(block) -> dict:
    return {"schema_version": 1, BLOCK: block}


def test_validator_accepts_legal_blocks(validator):
    validator.validate(_cfg({}))
    validator.validate(_cfg({"enabled": False, "publish_artifact": False}))
    validator.validate(_cfg({"drafter_override": {
        "pr-brief": "opus", "human-escalation": "opus"}}))


@pytest.mark.parametrize("bad", [
    {"enabled": "false"},
    {"publish_artifact": 1},
    {"drafter_override": {"auto-ruling": "opus"}},
    {"drafter_override": {"pr-brief": "sonnet"}},
    {"drafter_override": "opus"},
    {"drafter": "opus"},
    ["enabled"],
])
def test_validator_rejects_bad_blocks(validator, bad):
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(_cfg(bad))


# --- doc ---------------------------------------------------------------------------

def _doc_bullet() -> str:
    """The top-level `explainer` bullet of repo-config.md and its indented lines."""
    lines = DOC_PATH.read_text(encoding="utf-8").splitlines()
    head = f"- `{BLOCK}`"
    start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
    assert start is not None, f"repo-config.md has no top-level {head} bullet"
    section = [lines[start]]
    for ln in lines[start + 1:]:
        if not ln[:1].isspace():
            break
        section.append(ln)
    return "\n".join(section)


def test_doc_names_every_key_and_the_loader():
    text = _doc_bullet()
    for key in _schema_block()["properties"]:
        assert f"`{key}`" in text, f"doc bullet does not name `{key}`"
    for kind in explain_config.OVERRIDE_KINDS:
        assert f"`{kind}`" in text, f"doc bullet does not name `{kind}`"
    assert "skills/_shared/explainer/explain_config.py" in text


def test_doc_states_the_off_switch():
    # One clause (a sentence or a `;` part) carries `enabled`, `false` and "off".
    flat = " ".join(_doc_bullet().split()).lower()
    clauses = re.split(r"(?<=[.;])\s+", flat)
    assert any(all(t in c for t in ("`enabled`", "`false`", "off")) for c in clauses)
