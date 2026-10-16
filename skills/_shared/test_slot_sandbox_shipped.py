"""test_slot_sandbox_shipped.py — the router-state sandbox ships with the tests it protects.

design: slot-release-on-attempt-end (plan constraint: tests never touch the real router)
design: review-proof-ambient-gh-identity (the repo-config discovery pin ships the same way)

`attempt_watchdog.py`'s `poll` (on `done`) and `stopped` release through
`local_lease.release_agent`, which loads the real router whenever `tp-local` is on PATH. The
dev-only `_shared/conftest.py` never ships, so a sandbox defined there left the ship copy
(consumer-fixture-smoke F8) writing the operator's live `slot-owner.json`. These tests bind on
the property under the default test env, and on the fixture pytest actually applied to this
test resolving to the shipped `skills/conftest.py`, so dropping, moving or shadowing it goes
red in the ship copy too. `_no_ambient_repo_config` is the second such fixture: it pins the
identity core's repo-config discovery to an empty dir, so no test posts as the repo's bot.
"""
from __future__ import annotations

import inspect
import os
import tempfile
from pathlib import Path

import pytest

import automation_identity
import local_lease

_SKILLS = Path(__file__).resolve().parents[1]
_FIXTURES = ["_no_live_slot_release", "_no_ambient_repo_config"]


def _no_router(_name):
    pytest.fail("the release switch must answer before any router lookup")


def test_a_release_answers_disabled_under_the_default_test_env():
    assert local_lease.release_agent("a0000001-rest-of-id", which=_no_router) == {
        "outcome": "disabled", "endpoints": []}


@pytest.mark.parametrize("name", ["TP_LOCAL_SLOT_STATE", "TP_LOCAL_STOPPED"])
def test_the_router_state_paths_sit_in_this_tests_scratch(name):
    value = os.environ.get(name)
    assert value, f"{name} must be set for every test"
    path = Path(value)
    assert Path(tempfile.gettempdir()) in path.parents
    live = Path(os.path.expanduser("~/.local/state")) / "tp-local"
    assert live not in path.parents


def test_repo_config_discovery_is_pinned_to_an_empty_dir_in_this_tests_scratch():
    root = automation_identity._default_repo_root()
    assert Path(tempfile.gettempdir()) in root.parents
    assert root.is_dir() and not (root / ".three-pillars" / "config.json").exists()
    assert automation_identity.load_repo_config(root) == {}


@pytest.mark.parametrize("fixture", _FIXTURES)
def test_the_applied_sandbox_fixture_is_the_shipped_conftests(request, fixture):
    """pytest resolved the autouse sandbox for this test, and the definition it applied (the
    innermost one, so a same-named fixture in the dev-only `_shared/conftest.py` would show up
    here) is the one in the shipped `skills/conftest.py`."""
    defs = request.node._fixtureinfo.name2fixturedefs.get(fixture) or ()
    assert defs, f"{fixture} is not a fixture visible to this test"
    assert fixture in request.fixturenames, f"{fixture} is not applied (autouse) to this test"
    applied = Path(inspect.getfile(defs[-1].func)).resolve()
    assert applied == (_SKILLS / "conftest.py").resolve()
