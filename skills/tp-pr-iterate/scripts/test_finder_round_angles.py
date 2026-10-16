"""finder_round.check_angle and round_angles (local-role-routing 6.2)."""
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import angles  # noqa: E402
import finder_round  # noqa: E402
import role_engine  # noqa: E402
import strata_spawn  # noqa: E402

LOCAL = {"role_engines": {"review_finder": "local"}}
ANGLES = [{"name": n, "role": "confirmer", "model": "opus", "prompt": f"look at {n}"}
          for n in ("correctness", "security", "perf")]
RULINGS = "/x/rulings.md"


@pytest.fixture(autouse=True)
def _run_follows_fixture(monkeypatch):
    """The retired `role_engines` fixtures stand in for a `--local` run."""
    monkeypatch.setattr(role_engine, "run_local", lambda cfg: bool((cfg or {}).get("role_engines")))


def _yes():
    return True


def _local(**kw):
    cfg = {**LOCAL, "review": {"angles": ANGLES}}
    return finder_round.round_angles(cfg, root=".", available=_yes,
                                     rulings_path=RULINGS, **kw)


def test_unset_key_is_a_cheap_round_over_load_angles():
    for cfg in ({}, None, {"review": {"angles": ANGLES}}):
        got = finder_round.round_angles(cfg, root=".", rulings_path=RULINGS)
        loaded = angles.load_angles(cfg)
        assert [a["name"] for a in got[:-1]] == [a["name"] for a in loaded]
        assert got[-1]["name"] == finder_round.CHECK_NAME


def test_local_makes_advisory_finders_and_appends_check():
    got = _local()
    assert len(got) == len(ANGLES) + 1
    for a, src in zip(got, ANGLES):
        assert a["name"] == src["name"]
        assert (a["role"], a["model"], a["advisory"]) == ("finder", "local", True)
        assert RULINGS in a["prompt"]
        assert a["prompt"].startswith(src["prompt"])
        assert strata_spawn.SLOT_LOSS_SUFFIX in a["prompt"]
    check = got[-1]
    assert check == finder_round.check_angle(RULINGS)
    assert check["name"] == finder_round.CHECK_NAME == "opus-check"
    assert (check["role"], check["model"]) == ("confirmer", "opus")


def test_local_without_backend_falls_back_to_sonnet_round():
    cfg = {**LOCAL, "review": {"angles": ANGLES}}
    got = finder_round.round_angles(cfg, root=".", available=lambda: False,
                                    rulings_path=RULINGS)
    assert [a["model"] for a in got] == ["sonnet"] * len(ANGLES) + ["opus"]


def test_check_prompt_contract():
    p = finder_round.check_angle(RULINGS)["prompt"]
    assert "../" in p and "reply.md" in p
    assert RULINGS in p
    assert "citation" in p
    assert "escape" in p and "from" in p and "disposition" in p
    assert "put-dispositions" in p
    assert "unparseable" in p and "angles.json" in p
    assert "<<'" in p  # quoted heredoc


def test_scope_marks_others_out_of_scope_never_the_check():
    got = _local(scope=["security"])
    by = {a["name"]: a for a in got}
    assert "skipped" not in by["security"]
    assert by["correctness"]["skipped"] == "out-of-scope"
    assert by["perf"]["skipped"] == "out-of-scope"
    assert "skipped" not in by["opus-check"]


def test_scope_applies_on_sonnet_engine_too():
    cfg = {"review": {"angles": ANGLES}}
    got = finder_round.round_angles(cfg, root=".", scope=["perf"], rulings_path=RULINGS)
    assert [a.get("skipped") for a in got] == ["out-of-scope", "out-of-scope", None, None]


def test_unknown_scope_raises_naming_it():
    with pytest.raises(ValueError, match="no-such-angle"):
        _local(scope=["no-such-angle"])


def test_scope_none_keeps_everything_in_scope():
    assert not any(a.get("skipped") for a in _local(scope=None))
