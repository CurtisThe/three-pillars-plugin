"""The launcher-session vars a test run unsets live in one place: launcher_env.TEST_LEAK_ENV.

The dev conftest and the release F8 smoke (scripts/consumer-fixture-smoke.sh) both use it, so a
new launcher var cannot be added to one and forgotten in the other (the v2.8.0 F8 failure).
"""
from pathlib import Path

import launcher_env

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def test_the_list_names_the_owned_var():
    assert launcher_env.OWNED_ENV in launcher_env.TEST_LEAK_ENV, "the shared list lost CLAUDE_LAUNCHER_OWNED"


def test_conftest_uses_the_shared_list():
    conftest = HERE / "conftest.py"
    if not conftest.is_file():  # dev-only conftest, absent from a shipped copy
        return
    text = conftest.read_text(encoding="utf-8")
    assert "from launcher_env import TEST_LEAK_ENV" in text, "conftest no longer imports the shared list"
    assert '_LAUNCHER_LEAK_ENV = (' not in text, "conftest redefines its own launcher-var list"


def test_f8_reads_the_shared_list_and_spells_out_no_name():
    smoke = ROOT / "scripts" / "consumer-fixture-smoke.sh"
    if not smoke.is_file():  # dev-only script, absent from a shipped copy
        return
    text = smoke.read_text(encoding="utf-8")
    assert "TEST_LEAK_ENV" in text, "F8 no longer reads launcher_env.TEST_LEAK_ENV"
    spelled = [v for v in launcher_env.TEST_LEAK_ENV if f"-u {v}" in text]
    assert spelled == [], f"F8 hard-codes launcher vars again: {spelled}"
