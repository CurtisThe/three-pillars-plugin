"""The background-spawn-failed mirror path takes its model and agent from `spec`.

design: cheap-tier-local-routing (operator follow-up, 2026-10-02). `cheap-dispatch.md`
§Local rung step 1 once spawned the mirror with a model literal. A `spec --probe` that keeps a
`local-*` rung now also prints `mirror_rung`, `mirror_agent_ref` and `mirror_model`, and the
doc names only those placeholders. Every case stubs `cheap_route.probe`: nothing live runs.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_ref  # noqa: E402
import cheap_route  # noqa: E402
import cheap_tier  # noqa: E402
import cheap_tier_cli as cli  # noqa: E402
import ladder_rungs  # noqa: E402
from test_cheap_tier_exclusions import CHEAP_PIN_RE  # noqa: E402

DOC = HERE / "cheap-dispatch.md"
# The fallback model is NOT the bare "sonnet": a mirror_model literal "sonnet" must not pass.
MIRROR_MODEL = "claude-sonnet-fixture"
LOCAL = {"enabled": True, "model": "qwen3-coder", "fallback_model": MIRROR_MODEL}
MIRROR_KEYS = {"mirror_rung", "mirror_agent_ref", "mirror_model"}
# Any <spec.…> token: a misspelled one (`<spec.requested-rung>`) and one holding a space
# (`<spec.mirror rung>`) included; only the angle brackets bound a placeholder.
SPEC_RE = re.compile(r"<spec\.([^<>]+)>")
REF_TAG = "probe-ref-fixture/"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.setenv("TP_LOCAL_LOG", str(state / "tp-local" / "router.log"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)


@pytest.fixture
def answer(monkeypatch):
    """Stub `cheap_route.probe` (routed/ok, slot free); a test edits the answer first."""
    ans = {"route_label": "routed/ok", "lease_state": "free", "lease_why": "free",
           "lease_wait_s": 0.0, "measure": "off", "fallback": None}
    monkeypatch.setattr(cheap_route, "probe", lambda *a, **k: dict(ans))
    monkeypatch.setattr(cli.local_lease, "acquire", lambda *a, **k: ("free", "unowned"))
    return ans


def _root(tmp_path: Path, rung: str = "local-medium", slot: str = "docs_draft") -> Path:
    cfg = tmp_path / "repo" / ".three-pillars" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"models": {slot: rung}, "local_implement": LOCAL}),
                   encoding="utf-8")
    return tmp_path / "repo"


def _local_section() -> str:
    m = re.search(r"^## Local rung\n(.*?)(?=^## |\Z)", DOC.read_text(encoding="utf-8"),
                  re.S | re.M)
    assert m, "no ## Local rung section"
    return m.group(1)


@pytest.mark.parametrize("slot, rung", [("docs_draft", "local-medium"),
                                        ("base_sync_splice", "local-xhigh")])
def test_a_kept_local_rung_carries_its_mirror(tmp_path, answer, monkeypatch, slot, rung):
    real_resolve = agent_ref.resolve  # tag every resolution: a ref literal cannot match it
    monkeypatch.setattr(agent_ref, "resolve", lambda a, root=None: REF_TAG + real_resolve(a, root))
    spec = cli.spec(slot, _root(tmp_path, rung, slot), cheap_flag="on", probe=True)
    mirror = cheap_tier.MIRROR[rung]
    assert spec["rung"] == rung
    assert spec["mirror_rung"] == mirror
    want = ladder_rungs.effective_model(mirror, LOCAL, "routed/ok")
    assert want == MIRROR_MODEL != "sonnet", want  # the fixture resolves to a non-literal
    assert spec["mirror_model"] == want, (
        f"mirror_model not resolved from {mirror} for {rung}: got {spec['mirror_model']!r}, "
        f"local model {LOCAL['model']!r}, fallback model {MIRROR_MODEL!r}")
    drafter = cli.DRAFTERS[mirror.rsplit("-", 1)[1]]
    assert spec["mirror_agent_ref"] == REF_TAG + real_resolve(drafter), (
        f"mirror_agent_ref not resolved from {mirror} for {rung}: {spec['mirror_agent_ref']!r}")


def test_a_probe_that_falls_back_carries_no_mirror_keys(tmp_path, answer):
    answer.update(lease_state="busy", fallback="local-busy")
    spec = cli.spec("docs_draft", _root(tmp_path), cheap_flag="on", probe=True)
    assert spec["rung"] == "sonnet-medium" and not MIRROR_KEYS & set(spec)


def test_a_non_probe_spec_carries_no_mirror_keys(tmp_path, answer):
    spec = cli.spec("docs_draft", _root(tmp_path), cheap_flag="on")
    assert not MIRROR_KEYS & set(spec)


def test_dispatch_doc_has_no_cheap_model_literal():
    assert CHEAP_PIN_RE.findall(DOC.read_text(encoding="utf-8")) == []


def test_spawn_failed_fallback_names_the_spec_mirror():
    local = _local_section()
    step1 = re.search(r"^1\. \*\*Spawn\*\*.*$", local, re.M)
    assert step1, "§Local rung has no step 1"
    for needle in ("<spec.mirror_model>", "<spec.mirror_agent_ref>", "<spec.mirror_rung>"):
        assert needle in step1.group(0), needle
    assert "<mirror rung>" not in local
    spawn = [l for l in local.splitlines()
             if "dispatch_log.py record" in l and "background-spawn-failed" in l]
    assert len(spawn) == 1 and "--rung <spec.mirror_rung>" in spawn[0], spawn


def test_every_local_rung_spec_placeholder_is_a_probe_key(tmp_path, answer):
    keys = set(cli.spec("docs_draft", _root(tmp_path), cheap_flag="on", probe=True))
    used = set(SPEC_RE.findall(_local_section()))
    assert MIRROR_KEYS <= used, MIRROR_KEYS - used
    for name in sorted(used):
        assert name in keys, f"placeholder not a spec --probe key: <spec.{name}>"
