"""test_role_engine_guard.py — every judgment dispatch stays Opus; no local reply signs.

design: local-role-routing (Task 7.1); explainer-agent (Task 7.1) adds the `explainer` role.

The `role_engines` block may route exactly four roles to the local engine —
`model_policy.ENGINE_ROLES` (member, finder, scout, explainer). Everything that *judges*
stays pinned: the gate roles (`GATE_ROLES`), the council synthesizer, the Opus review check,
the certifier and the finalizer's Opus fallback. Every assertion below runs against a
config that sets all four engine keys to `local`, so a role that wrongly read the block
would move:

- `judgment_is_opus` is the guard's predicate (a row with a non-`opus` engine, or a model
  whose Agent alias is not `opus`, is refused) and `local_engine_role` names the only
  roles the block may carry.
- `ENGINE_ROLES` is exactly the four; a judgment role has no engine key at all (`validate`
  drops it with a warning, `resolve` raises).
- each `GATE_ROLES` floor, the synthesizer agent and the certifier agent resolve `opus`.
- the finalizer's dispatch spec is unmoved by the block and its fallback row is `opus`; its
  primary model stays the fable-first-stops one — never a local or downgraded model.
- `finder_round.check_angle` is an Opus confirmer, and no `round_angles` output under
  `local` holds a confirmer that is not Claude-tier.
- `angles.confirmer_ran` is False when the only parseable replies came from `local` entries
  (whatever their `role` label), and True once the Opus check's reply parses (non-vacuity).
- every `agents/council-*.md` keeps `model: opus` — the local override is at the call.

Hermetic: `available` and `resolve_fn` are injected, every config / ledger / manifest is a
tmp_path fixture. No live router, no network, no real subagent, nothing mocked.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
_PR_ITERATE = HERE.parent / "tp-pr-iterate" / "scripts"
if str(_PR_ITERATE) not in sys.path:
    sys.path.insert(0, str(_PR_ITERATE))

import angles  # noqa: E402
import finalizer  # noqa: E402
import finder_round  # noqa: E402
import model_policy  # noqa: E402
import role_engine  # noqa: E402
import round_scratch  # noqa: E402

REPO_ROOT = HERE.parents[1]
COUNCIL_AGENTS = sorted((REPO_ROOT / "agents").glob("council-*.md"))

# Every engine key set to `local`: the config a judgment role must not read.
ALL_LOCAL = {"role_engines": {r: "local" for r in model_policy.ENGINE_ROLES}}
# The synthesizer's own agent (slots 4/6 read-only auditor; slot 8 the impl auditor).
SYNTH_AGENTS = ("tp-readonly-auditor", "tp-impl-auditor")
PARSEABLE = '{"findings": []}\n'
UNPARSEABLE = "I read the diff and it looks fine to me.\n"


@pytest.fixture(autouse=True)
def _run_follows_fixture(monkeypatch):
    """The retired `role_engines` fixtures stand in for a `--local` run."""
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: bool((cfg or {}).get("role_engines")))


def _always() -> bool:
    """The injected backend probe — the local branch forced without touching PATH."""
    return True


# --- the guard's predicate -------------------------------------------------
def local_engine_role(role: str) -> bool:
    """True iff `role` is one the `role_engines` block may carry (the four)."""
    return role in model_policy.ENGINE_ROLES


def judgment_is_opus(row: dict) -> bool:
    """True iff a judgment dispatch `row` is allowed: never a local engine, Opus model.

    `row` is whatever a dispatch site writes from — a `role_engine.resolve` row (with
    `engine`), a `model_policy.agent_spec` row, or a round-manifest angle entry (model
    only). A missing `engine` means the site has no engine key at all, which is the pin.
    """
    if row.get("engine") not in (None, "opus"):
        return False
    return model_policy.agent_alias(row.get("model") or "") == "opus"


# --- the engine vocabulary is closed ---------------------------------------
def test_engine_roles_are_exactly_the_four():
    # Fixed messages: the certifier's RED markers (a bare tuple compare prints no stable text).
    assert model_policy.ENGINE_ROLES == (
        "council_member", "review_finder", "context_scout", "explainer"), (
        "ENGINE_ROLES must be the pinned local-routable role tuple")
    assert role_engine.ENGINE_ROLES is model_policy.ENGINE_ROLES, (
        "role_engine.ENGINE_ROLES must alias the model_policy tuple")
    assert role_engine.ENGINES == ("local", "opus"), (
        "role_engine.ENGINES must be exactly local and opus")


@pytest.mark.parametrize("role", ["synthesizer", "synth", "finalizer", "certifier",
                                 "impl-audit", "audit", "review", "opus-check"])
def test_judgment_roles_have_no_engine_key(role):
    """The block cannot carry a judgment role: `validate` drops it, `resolve` refuses."""
    kept, warnings = role_engine.validate({role: "local"})
    assert kept == {} and len(warnings) == 1, (kept, warnings)
    with pytest.raises(ValueError):
        role_engine.resolve(role, ALL_LOCAL, root=".", available=_always)
    assert not local_engine_role(role)


# --- gates, synth and certifier stay pinned to Opus ------------------------
@pytest.mark.parametrize("role", model_policy.GATE_ROLES)
def test_gate_role_floor_resolves_opus_under_all_local(role):
    spec = model_policy.floor(role, ALL_LOCAL)
    assert spec is not None
    assert judgment_is_opus(spec), spec
    assert spec["model"] == "opus", spec


@pytest.mark.parametrize("agent", SYNTH_AGENTS + ("tp-certifier", "tp-review-confirmer",
                                                 "tp-review-confirmer-deep"))
def test_synth_and_certifier_agent_specs_resolve_opus(agent):
    spec = model_policy.agent_spec(agent, ALL_LOCAL)
    assert judgment_is_opus(spec), spec
    assert spec == model_policy.agent_spec(agent, None), (
        f"the role_engines block moved {agent}'s spec")


def test_finalizer_dispatch_spec_is_unmoved_and_falls_back_to_opus(tmp_path):
    """The finalizer is a judgment: the block cannot route it local and its fallback is
    Opus. Its primary model is the fable-first-stops one — never a local or downgraded model."""
    stop = {"source": "halt", "signal": "guard", "target": "slug", "detail": "x"}
    resolve_fn = lambda name: f"three-pillars:{name}"  # noqa: E731 — injected seam
    out = finalizer.prepare(stop, tmp_path / "finalizer-ledger.json",
                            resolve_fn=resolve_fn)
    assert out["status"] == "dispatch", out
    assert model_policy.agent_alias(out["model"]) in ("fable", "opus"), out["model"]
    assert judgment_is_opus(out["fallback"]), out["fallback"]
    assert out["fallback"] == model_policy.FINALIZER_FALLBACK
    spec = model_policy.agent_spec(finalizer.FINALIZER_AGENT, ALL_LOCAL)
    assert spec == model_policy.agent_spec(finalizer.FINALIZER_AGENT)
    assert model_policy.agent_alias(spec["model"]) in ("fable", "opus"), spec


# --- the RED evidence: the predicate rejects a local synth row -------------
def test_predicate_rejects_a_synth_row_set_to_local():
    """A synthesizer row routed to the local engine is the failure this guard exists for."""
    local_synth = {"role": "synthesizer", "engine": "local", "model": "haiku",
                   "effort": role_engine.row_effort("council_member", "local"), "note": None}
    assert not judgment_is_opus(local_synth)
    assert not local_engine_role(local_synth["role"])
    # and the same row for an engine role is allowed — the predicate is not a blanket ban.
    member = role_engine.resolve("council_member", ALL_LOCAL, root=".", available=_always)
    assert member["engine"] == "local" and local_engine_role(member["role"])


# --- the review check is Opus, and a local reply cannot sign ---------------
def test_check_angle_is_an_opus_confirmer():
    check = finder_round.check_angle("rulings.md")
    assert check["role"] == "confirmer"
    assert check["name"] == finder_round.CHECK_NAME
    assert angles.tier(check) == "claude"
    assert judgment_is_opus(check), check


def test_round_angles_under_local_has_no_non_claude_confirmer(tmp_path):
    out = finder_round.round_angles(ALL_LOCAL, root=tmp_path, rulings_path="rulings.md",
                                    available=_always)
    confirmers = [a for a in out if a["role"] == "confirmer"]
    assert [a["name"] for a in confirmers] == [finder_round.CHECK_NAME], out
    for a in confirmers:
        assert angles.tier(a) == "claude", a
        assert judgment_is_opus(a), a
    for a in out:
        if a["name"] != finder_round.CHECK_NAME:
            assert a["role"] == "finder" and a.get("advisory") is True, a


def test_round_manifest_name_is_the_one_both_sides_read():
    assert finder_round.MANIFEST == round_scratch.MANIFEST == "angles.json"


def _round_dir(tmp_path, entries) -> Path:
    """A fixture round: one reply file per `(role, model, text)` plus its manifest."""
    round_dir = tmp_path / "rounds" / "pr-1" / "R1"
    round_dir.mkdir(parents=True)
    manifest = []
    for i, (role, model, text) in enumerate(entries):
        slot = f"a{i}"
        (round_dir / slot).mkdir()
        (round_dir / slot / "reply.md").write_text(text, encoding="utf-8")
        manifest.append({"name": slot, "role": role, "model": model, "prompt": "p",
                         "reply_path": f"{slot}/reply.md"})
    (round_dir / round_scratch.MANIFEST).write_text(
        json.dumps({"angles": manifest}), encoding="utf-8")
    return round_dir


def _manifest(round_dir: Path) -> dict:
    return json.loads((round_dir / round_scratch.MANIFEST).read_text(encoding="utf-8"))


def test_a_local_reply_never_signs_the_proof_even_marked_confirmer(tmp_path):
    """The signing predicate is the tier, not the manifest's `role` label: a round whose
    only parseable reply came from a `local` model refuses, even if that entry is labelled
    `confirmer` (a consumer manifest or a hand-written round envelope can say so)."""
    round_dir = _round_dir(tmp_path, [("finder", "local", PARSEABLE),
                                      ("confirmer", "local", PARSEABLE),
                                      ("confirmer", "opus", UNPARSEABLE)])
    manifest = _manifest(round_dir)
    assert angles.tier(manifest["angles"][1]) == "local"
    assert angles.confirmer_ran(manifest, round_dir) is False


def test_the_opus_check_reply_does_sign_the_proof(tmp_path):
    """Non-vacuity control for the test above: the same round signs once the check parses."""
    round_dir = _round_dir(tmp_path, [("finder", "local", PARSEABLE),
                                      ("confirmer", "local", PARSEABLE),
                                      ("confirmer", "opus", PARSEABLE)])
    assert angles.confirmer_ran(_manifest(round_dir), round_dir) is True


# --- council members: the frontmatter stays Opus, the override is at the call
@pytest.mark.parametrize("path", COUNCIL_AGENTS, ids=lambda p: p.stem)
def test_council_member_frontmatter_keeps_opus(path):
    model = re.search(r"^model:\s*(\S+)", path.read_text(encoding="utf-8"), flags=re.M)
    assert model is not None and model.group(1) == "opus", f"{path.name} must keep model: opus"


def test_member_override_happens_at_the_call_not_in_frontmatter():
    """The agent row is cheap (sonnet, no local_cfg), not a judgment; the call routes to `local`."""
    assert model_policy.agent_spec("council-ada", ALL_LOCAL)["model"] == "sonnet"
    row = role_engine.resolve("council_member", ALL_LOCAL, root=".", available=_always)
    assert row["engine"] == "local"
    assert row["effort"] == role_engine.row_effort("council_member", "local")
