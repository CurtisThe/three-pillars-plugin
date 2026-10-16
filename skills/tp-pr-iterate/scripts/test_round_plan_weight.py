"""round_plan.plan — the `review_weight` stamp into iterate-state (read-modify-write).

design: review-convergence (Task 4.5, detailed-design-pr-loop §D3)

Review bar: the weight a round was planned at has to be recorded in the loop's own
state, because a later round's budget (`round_budget.limits`) reads the weight that
chose these angles. The stamp is deliberately narrow:

* **read-modify-write** — every other key in the state file survives untouched;
* **absent state stays absent** — `plan` never creates a state file (bootstrapping
  iterate-state is `iterate_state.load_or_bootstrap`'s job, not the plan's);
* **no weight, no write** — the file is left byte-identical, so a round planned
  without `--review-weight` cannot rewrite a file it was only reading;
* **a refused round writes nothing** — the stamp happens after the plan is computed,
  so `PlanRefused` leaves the state exactly as it was.

Oracle: example — the exact state document after each call, on a real tmp git repo
with real round dirs (test-fragility).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parents[1] / "_shared"))

import round_plan  # noqa: E402

_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

PR_URL = "https://github.com/o/r/pull/9"
RULINGS = "/x/rulings.md"

BLOCKER = {"source": "code-review", "file": "fix.py", "line_range": [1, 1],
           "summary": "wrong total", "verdict": "structural"}

# A state document with keys the plan must not care about — including one the schema
# does not know, to prove the stamp is a merge and not a rewrite from a known shape.
_SEED = {"phase": "fixing", "iteration": 2, "custom": 1}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path):
    """main: base commit, PR commit `A`, fix commit `B` = head."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    _write(r, "fix.py", "total = 1 + 1\n")
    base = _commit(r, "base")
    _write(r, "fix.py", "total = 1 + 1\nfixed = True\n")
    a = _commit(r, "A pr commit")
    _write(r, "fix.py", "total = 2\nfixed = True\n")
    b = _commit(r, "B fix")
    return {"repo": r, "base": base, "A": a, "B": b}


# The tail envelope `round_scratch._next_ordinal` reads to name the next round.
_ENVELOPE = {"schema": "tp-pr-iterate/round-tail/v1", "round": 1,
             "head_reviewed": "", "head_after": "",
             "tally": {"P": 1, "X": 0, "T": 0, "C": 0, "blocking": 1, "degraded": 0},
             "downgraded": 0, "notes": 0, "action": "fix", "fix_commit": None,
             "terminal": None, "converged": False,
             "budget": {"iteration": 1, "round_cap": 5, "signal": None, "holding": []},
             "finalizer_stop": None, "summary": "r1"}


def _round_dir(rounds_dir, name, head, findings):
    """One completed round: manifest head + tail findings + the envelope `prepare` reads."""
    rd = Path(rounds_dir) / name
    (rd / "tail").mkdir(parents=True, exist_ok=True)
    (rd / "angles.json").write_text(json.dumps({"head": head}), encoding="utf-8")
    (rd / "tail" / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    (rd / "tail" / "envelope.json").write_text(
        json.dumps({**_ENVELOPE, "head_reviewed": head, "head_after": head}),
        encoding="utf-8")
    return rd


def _seed_state(path: Path) -> bytes:
    """Write `_SEED` compact with a trailing newline; return those exact bytes.

    Deliberately NOT the atomic writer's shape (`indent=2`, no trailing newline): a
    file `plan` rewrites comes back with different bytes, so "byte-identical" below
    means "no write happened", not "the same document by luck".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(_SEED) + "\n"
    path.write_text(raw, encoding="utf-8")
    return raw.encode("utf-8")


def _plan(pr, tmp_path, *, round_two=False, **kw):
    """`plan` over the fixture PR — round 1 (empty rounds dir) or round 2."""
    root = tmp_path / "root"
    head = pr["B"]
    if round_two:
        _round_dir(root / "rounds" / "9", "r1", pr["A"], [BLOCKER])
    else:
        (root / "rounds" / "9").mkdir(parents=True, exist_ok=True)
    return round_plan.plan(None, root=root, pr_url=PR_URL, pr_base=pr["base"],
                           head=head, repo=str(pr["repo"]), rulings_path=RULINGS, **kw)


# ---------- the stamp, round 1 ----------


def test_the_stamp_lands_and_every_other_key_survives(tmp_path):
    pr = _repo(tmp_path)
    state = tmp_path / "iterate-state.v1.json"
    _seed_state(state)

    got = _plan(pr, tmp_path, review_weight="light", state_path=state)

    assert got["round"] == 1  # the stamp does not change the plan itself
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "phase": "fixing", "iteration": 2, "custom": 1, "review_weight": "light"}
    assert not list(state.parent.glob(f"{state.name}.tmp.*")), (
        "the stamp left a staging tmp behind — it did not go through "
        "iterate_state.write_state_atomic")


def test_a_second_weight_replaces_the_first(tmp_path):
    pr = _repo(tmp_path)
    state = tmp_path / "iterate-state.v1.json"
    _seed_state(state)
    state.write_text(json.dumps({**_SEED, "review_weight": "light"}), encoding="utf-8")

    _plan(pr, tmp_path, review_weight="just-do-it", state_path=state)

    assert json.loads(state.read_text(encoding="utf-8"))["review_weight"] == "just-do-it"


# ---------- absent state stays absent ----------


def test_an_absent_state_file_stays_absent(tmp_path):
    pr = _repo(tmp_path)
    state = tmp_path / "nested" / "iterate-state.v1.json"
    assert not state.exists()

    _plan(pr, tmp_path, review_weight="full", state_path=state)

    assert not state.exists(), (
        "plan created a state file — bootstrapping iterate-state is "
        "iterate_state.load_or_bootstrap's job, never the round plan's")


# ---------- no weight, no write ----------


def test_no_weight_leaves_the_state_file_byte_identical(tmp_path):
    pr = _repo(tmp_path)
    state = tmp_path / "iterate-state.v1.json"
    before = _seed_state(state)

    _plan(pr, tmp_path, review_weight=None, state_path=state)

    assert state.read_bytes() == before, (
        "plan rewrote a state file it was given no weight for")


def test_no_state_path_touches_nothing(tmp_path):
    pr = _repo(tmp_path)
    got = _plan(pr, tmp_path, review_weight="light")
    assert got["round"] == 1
    assert not list((tmp_path / "root").glob("**/iterate-state*"))


# ---------- the delta round stamps too, and a refusal writes nothing ----------


def test_a_delta_round_stamps_the_weight_too(tmp_path):
    pr = _repo(tmp_path)
    state = tmp_path / "iterate-state.v1.json"
    _seed_state(state)

    got = _plan(pr, tmp_path, round_two=True, review_weight="full", state_path=state)

    assert got["round"] == 2 and got["mode"] == "delta"
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "phase": "fixing", "iteration": 2, "custom": 1, "review_weight": "full"}


def test_a_refused_delta_plan_writes_nothing(tmp_path):
    pr = _repo(tmp_path)
    root = tmp_path / "root"
    # r1 reviewed this very head → no qualifying prior, so the round refuses.
    _round_dir(root / "rounds" / "9", "r1", pr["B"], [BLOCKER])
    state = tmp_path / "iterate-state.v1.json"
    before = _seed_state(state)

    with pytest.raises(round_plan.PlanRefused):
        round_plan.plan(None, root=root, pr_url=PR_URL, pr_base=pr["base"],
                        head=pr["B"], repo=str(pr["repo"]),
                        review_weight="full", state_path=state)

    assert state.read_bytes() == before, (
        "a refused round stamped its weight into iterate-state — the loop kept a "
        "record of a round that never ran")
