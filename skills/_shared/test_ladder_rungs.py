import pytest

import ladder_rungs as lr


def test_rungs_and_spawn():
    assert len(lr.RUNGS) == 6
    assert lr.SPAWN_RUNGS == lr.RUNGS  # Q4: every rung spawns its variant, opus-* too
    assert lr.LADDER == ("local", "sonnet", "opus")


def test_family_effort_agent_rank():
    assert lr.family("sonnet-xhigh") == "sonnet" and lr.effort("sonnet-xhigh") == "xhigh"
    assert lr.agent("local-medium") == "tp-task-worker-local-medium"
    assert lr.agent("opus-xhigh") == "tp-task-worker-opus-xhigh"
    assert lr.agent("opus-medium") != lr.agent("opus-xhigh") and lr.agent("bogus") is None
    assert lr.rank("opus-medium") == (2, 0) and lr.rank("local-xhigh") == (0, 1)


@pytest.mark.parametrize("a,b", [
    ("local-medium", "local-xhigh"), ("local-xhigh", "sonnet-xhigh"),
    ("sonnet-medium", "sonnet-xhigh"), ("sonnet-xhigh", "opus-xhigh"),
    ("opus-medium", "opus-xhigh"), ("opus-xhigh", None)])
def test_quality_next(a, b):
    assert lr.quality_next(a) == b


def test_quality_path_skips_opus_medium():
    seen, r = [], "local-medium"
    while r:
        seen.append(r)
        r = lr.quality_next(r)
    assert "opus-medium" not in seen


@pytest.mark.parametrize("a,b", [
    ("local-medium", "sonnet-medium"), ("local-xhigh", "sonnet-xhigh"),
    ("sonnet-medium", "opus-medium"), ("sonnet-xhigh", "opus-xhigh"),
    ("opus-medium", None), ("opus-xhigh", None)])
def test_unavailable_next(a, b):
    assert lr.unavailable_next(a) == b


def test_jump_is_max_by_rank():
    assert lr.jump("local-medium", "opus-medium") == "opus-medium"
    assert lr.jump("sonnet-medium", "local-medium") == "sonnet-xhigh"
    assert lr.jump("opus-xhigh", "opus-medium") is None


def test_legacy():
    assert lr.LEGACY == {"local": "local-medium", "sonnet": "sonnet-xhigh", "opus": "opus-xhigh"}


@pytest.mark.parametrize("row,rung", [
    ({"tier": "local"}, "local-medium"),
    ({"tier": "local", "kind": "clerical"}, "local-medium"),
    ({"tier": "local", "reasons": []}, "local-medium"),
    ({"tier": "local", "reasons": ["too-many-files"]}, "local-xhigh"),
    ({"tier": "local", "reasons": ["target-missing"]}, "local-xhigh"),
    ({"tier": "local", "reasons": ["unparsed-file", "collides:1.2"]}, "local-xhigh"),
    ({"tier": "local", "reasons": ["collides:1.2"]}, "local-medium"),
    ({"tier": "local", "reasons": ["no-runner"]}, "local-xhigh"),  # no oracle: Strata, xhigh
    ({"tier": "local", "reasons": ["test-not-runnable:targets-none"]}, "local-xhigh"),
    ({"tier": "local", "kind": "clerical", "reasons": ["no-runner"]}, "local-medium"),
    ({"tier": "local", "kind": "clerical", "reasons": ["too-many-files"]}, "local-medium"),
    ({"tier": "sonnet", "kind": "clerical"}, "sonnet-medium"),
    ({"tier": "sonnet", "kind": None}, "sonnet-xhigh"),
    ({"tier": "sonnet"}, "sonnet-xhigh"),
    ({"tier": "opus", "kind": "clerical"}, "opus-medium"),
    ({"tier": "opus", "kind": "logic"}, "opus-xhigh"),
    ({"tier": "opus"}, "opus-xhigh")])
def test_task_start(row, rung):
    r, reason = lr.task_start(row)
    assert r == rung and reason
