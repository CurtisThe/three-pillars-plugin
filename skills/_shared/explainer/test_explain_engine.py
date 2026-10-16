"""test_explain_engine.py — the explainer's drafter engine, check pin and exhaustion map.

Covers explainer-agent plan Task 7.3 (detailed-design §Interfaces, `explain_engine`), as
absorbed by one-cheap-engine (the explainer drafter is a cheap site; base-sync 2026-10-10):
  - with no `--local` the drafter is sonnet with no note, for every kind; under `--local`
    with a backend it is the Strata (local) engine; under `--local` with no backend it is
    sonnet with a note that names sonnet and not opus (role_engine's M51 note);
  - `role_engines.explainer: local` is deprecated and changes nothing: the row equals the
    unset row under either run (only the deprecation note differs);
  - `role_engines.explainer: opus` still acts (the design's honest switch): opus for every
    kind (auto-ruling included) with a note that names opus;
  - every drafter row is busy `fallback` (busy -> Sonnet);
  - a `drafter_override` of opus wins for its kind only;
  - an invalid value (`sonnet`) is dropped by `role_engine.validate` with one warning and
    drafts as unset;
  - `strata_spawn.decide` answers `sonnet` on exhaustion (never Opus) and `on_exhausted`
    passes it through, still mapping a legacy `opus` to `sonnet`;
  - `CHECK_MODEL` is opus; `needs_check` is True for pr-brief and human-escalation.

The run is pinned through `role_engine.run_local` (the module seam one-cheap-engine's own
tests use), so no test reads `TP_LOCAL` or the repo config; the backend probe is injected
(`available=`) or monkeypatched on `local_backend`, so none depends on `tp-local` being on
PATH. Roots are tmp dirs; no repo doc tree is read. Assertions are on the returned row's
fields (skills/_shared/test-fragility.md).
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest  # noqa: E402

import explain_engine  # noqa: E402
import explain_envelope  # noqa: E402
import local_backend  # noqa: E402
import model_policy  # noqa: E402
import role_engine  # noqa: E402
import strata_spawn  # noqa: E402

KINDS = explain_envelope.KINDS
CHECKED_KINDS = ("pr-brief", "human-escalation")


def _config(engine=None, override=None) -> dict:
    """A full repo config with `role_engines.explainer` and/or a drafter override."""
    config: dict = {}
    if engine is not None:
        config[role_engine.CONFIG_KEY] = {"explainer": engine}
    if override is not None:
        config["explainer"] = {"drafter_override": override}
    return config


def _yes():
    return True


def _no():
    return False


@pytest.fixture
def plain_run(monkeypatch):
    """A run without `--local`."""
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: False)


@pytest.fixture
def local_run(monkeypatch):
    """A `--local` run."""
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: True)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("available", [_yes, _no])
def test_without_local_drafts_on_sonnet_with_no_note(plain_run, tmp_path, kind, available):
    row = explain_engine.resolve_drafter(kind, _config(), tmp_path, available=available)
    assert row["engine"] == "sonnet", f"kind={kind}: no --local must draft on sonnet"
    assert row["model"] == "sonnet"
    assert row["note"] is None
    assert row["busy"] == "fallback"


@pytest.mark.parametrize("kind", KINDS)
def test_local_run_with_backend_drafts_on_strata(local_run, tmp_path, kind):
    row = explain_engine.resolve_drafter(kind, _config(), tmp_path, available=_yes)
    assert row["engine"] == "local", f"kind={kind}: --local with a backend must draft on Strata"
    assert row["model"] in model_policy.AGENT_ALIASES
    assert row["busy"] == "fallback"


@pytest.mark.parametrize("kind", KINDS)
def test_local_run_without_backend_drafts_on_sonnet_and_says_so(local_run, tmp_path, kind):
    row = explain_engine.resolve_drafter(kind, _config(), tmp_path, available=_no)
    assert row["engine"] == "sonnet", f"kind={kind}: no backend must fall back to sonnet"
    assert row["model"] == "sonnet"
    assert row["note"] is not None
    assert "sonnet" in row["note"]
    assert "opus" not in row["note"]
    assert row["busy"] == "fallback"


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("available", [_yes, _no])
def test_local_key_is_deprecated_and_changes_nothing(monkeypatch, tmp_path, on, available):
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: on)
    for kind in KINDS:
        unset = explain_engine.resolve_drafter(kind, _config(), tmp_path, available=available)
        keyed = explain_engine.resolve_drafter(kind, _config("local"), tmp_path,
                                               available=available)
        assert (keyed["engine"], keyed["model"]) == (unset["engine"], unset["model"]), kind
        assert keyed["note"] is not None and "deprecated" in keyed["note"]
        assert "opus" not in keyed["note"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("on", [False, True])
def test_explicit_opus_drafts_every_kind_on_opus(monkeypatch, tmp_path, kind, on):
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: on)
    row = explain_engine.resolve_drafter(kind, _config("opus"), tmp_path, available=_yes)
    assert row["engine"] == "opus", f"kind={kind}: explainer=opus must draft on opus"
    assert row["model"] == "opus"
    assert row["note"] is not None and "opus" in row["note"]
    assert row["busy"] == "fallback"


@pytest.mark.parametrize("on", [False, True])
def test_every_row_has_the_dispatch_fields(monkeypatch, tmp_path, on):
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: on)
    for engine in (None, "opus", "local"):
        for available in (_yes, _no):
            row = explain_engine.resolve_drafter(
                "pr-brief", _config(engine), tmp_path, available=available)
            assert {"engine", "model", "effort", "note", "busy"} <= set(row)
            assert row["effort"] in model_policy.EFFORTS


def test_default_probe_is_looked_up_at_call_time(local_run, tmp_path, monkeypatch):
    monkeypatch.setattr(local_backend, "available", _yes)
    row = explain_engine.resolve_drafter("auto-ruling", _config(), tmp_path)
    assert row["engine"] == "local"
    monkeypatch.setattr(local_backend, "available", _no)
    row = explain_engine.resolve_drafter("auto-ruling", _config(), tmp_path)
    assert row["engine"] == "sonnet"


def test_override_wins_for_its_kind_only(local_run, tmp_path):
    config = _config(None, {"pr-brief": "opus"})
    brief = explain_engine.resolve_drafter("pr-brief", config, tmp_path, available=_yes)
    ruling = explain_engine.resolve_drafter("auto-ruling", config, tmp_path, available=_yes)
    escalation = explain_engine.resolve_drafter(
        "human-escalation", config, tmp_path, available=_yes)
    assert brief["engine"] == "opus" and brief["model"] == "opus"
    assert ruling["engine"] == "local"
    assert escalation["engine"] == "local"


def test_override_wins_over_the_sonnet_default(plain_run, tmp_path):
    config = _config(None, {"human-escalation": "opus"})
    row = explain_engine.resolve_drafter("human-escalation", config, tmp_path, available=_no)
    assert row["engine"] == "opus"
    other = explain_engine.resolve_drafter("pr-brief", config, tmp_path, available=_no)
    assert other["engine"] == "sonnet"


def test_invalid_engine_value_is_dropped_and_drafts_as_unset(plain_run, tmp_path):
    block = {"explainer": "sonnet"}
    kept, warnings = role_engine.validate(block)
    assert "explainer" not in kept
    assert len(warnings) == 1
    for kind in KINDS:
        row = explain_engine.resolve_drafter(
            kind, {role_engine.CONFIG_KEY: block}, tmp_path, available=_yes)
        assert (row["engine"], row["model"]) == ("sonnet", "sonnet")
        # The set (if invalid) block earns role_engine's deprecation line, nothing else.
        assert row["note"] is None or row["note"].startswith("deprecated:")
        assert "opus" not in (row["note"] or "")


def test_on_exhausted_maps_opus_to_sonnet_and_passes_others():
    assert explain_engine.on_exhausted("opus") == "sonnet"
    for answer in ("accept", "respawn", "halt", "proceed-empty", "sonnet"):
        assert explain_engine.on_exhausted(answer) == answer


def test_decide_names_sonnet_on_exhaustion_and_on_exhausted_passes_it_through():
    exhausted = strata_spawn.decide(strata_spawn.RESPAWN_MAX, "fallback", "explainer")
    assert exhausted == "sonnet"
    assert explain_engine.on_exhausted(exhausted) == "sonnet"


def test_check_model_is_pinned_to_opus():
    assert explain_engine.CHECK_MODEL == "opus"


@pytest.mark.parametrize("kind", KINDS)
def test_needs_check_for_brief_and_escalation_only(kind):
    assert explain_engine.needs_check(kind) is (kind in CHECKED_KINDS)
