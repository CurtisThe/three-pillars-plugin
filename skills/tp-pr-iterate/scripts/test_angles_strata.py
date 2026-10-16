"""angles.dispatch_model and the digest markers (local-role-routing 6.1)."""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import model_policy  # noqa: E402
import role_engine  # noqa: E402

CFG = {"role_engines": {"review_finder": "local"}}


def test_claude_tier_maps_to_alias():
    assert angles.dispatch_model({"model": "opus"}) == model_policy.agent_alias("opus")
    assert angles.dispatch_model({"model": "claude-opus-4-1"}) == "opus"


def test_local_uses_role_engine_model():
    want = role_engine.resolve("review_finder", CFG)["model"]
    assert angles.dispatch_model({"model": "local"}, CFG) == want


def test_local_without_config_loads_root(tmp_path):
    (tmp_path / ".three-pillars").mkdir()
    (tmp_path / ".three-pillars" / "config.json").write_text(json.dumps(CFG))
    cfg = role_engine.load_config(tmp_path)
    want = role_engine.resolve("review_finder", cfg, root=tmp_path)["model"]
    assert angles.dispatch_model({"model": "local"}, root=tmp_path) == want


def test_non_alias_model_is_none():
    assert angles.dispatch_model({"model": "qwen"}) is None


def test_skipped_is_none_whatever_model():
    for m in ("opus", "local", "qwen"):
        assert angles.dispatch_model({"model": m, "skipped": "out-of-scope"}, CFG) is None


def _labels(entry):
    return angles.digest_labels({"angles": [entry]}, {})[0][0]


def test_out_of_scope_label():
    e = {"name": "a", "model": "local", "role": "finder", "skipped": "out-of-scope"}
    assert _labels(e) == "a[local/finder] [not run: out of scope]"


def test_unparseable_label():
    e = {"name": "a", "model": "local", "role": "finder",
         "unparseable": "re-covered-by-opus-check"}
    assert _labels(e) == "a[local/finder] [unparseable: re-covered by opus-check]"


def test_backend_absent_label_unchanged():
    e = {"name": "a", "model": "qwen", "role": "finder", "skipped": "local backend absent"}
    assert _labels(e) == "a[qwen/finder] [skipped: no local backend]"


def test_tier_and_validate_unchanged():
    assert angles.tier({"model": "local"}) == "local"
    assert angles.tier({"model": "opus"}) == "claude"
    out = angles._validate({"name": "n", "role": "finder", "model": "local", "prompt": "p"}, set())
    assert out["model"] == "local"
    assert angles.confirmer_ran({"angles": []}) is False
