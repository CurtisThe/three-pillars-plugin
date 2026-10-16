"""strata-members.md gives the serial Strata member discipline; throughput names the engine."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOC = HERE / "strata-members.md"
THROUGHPUT = HERE.parent / "tp-run-full-design" / "throughput.md"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_names_the_discipline_steps():
    text = _doc()
    for needle in (
        "role_engine.py resolve council_member",
        "strata_spawn.py wait",
        "mark",
        "Agent(",
        "verify",
        "release",
        "decide",
    ):
        assert needle in text, needle


def test_model_comes_from_resolve_output():
    text = _doc()
    assert "model from role_engine resolve" in text
    assert 'model="sonnet"' not in text and 'model="haiku"' not in text


def test_wait_defers_to_strata_spawn_doc():
    text = _doc()
    assert "skills/_shared/strata-spawn.md" in text
    assert any(
        "strata_spawn.py wait" in ln and "skills/_shared/strata-spawn.md" in ln
        for ln in text.splitlines()
    )


def test_serial_and_respawn_rule():
    text = _doc().lower()
    assert "serially" in text
    assert "fallback-busy" in text
    assert "accepted" in text
    assert "respawn" in text


def test_sonnet_rerun_and_synth_ledger():
    text = _doc()
    assert "--rung sonnet-xhigh --reason slot-lost" in text
    assert 'member_engine="local"' in text
    assert "escape_ledger.py append-audit" in text
    assert "sonnet-busy" in text
    assert "Slot 8" in text


def test_standalone_council_ledger_rule():
    text = _doc()
    assert "standalone" in text.lower()
    assert "coordinator" in text
    assert "known design dir" in text


def test_throughput_row_mentions_role_engine_key():
    rows = [
        ln
        for ln in THROUGHPUT.read_text(encoding="utf-8").splitlines()
        if "audit-member" in ln and "council-*" in ln
    ]
    assert rows and "role_engines.council_member" in rows[0]
