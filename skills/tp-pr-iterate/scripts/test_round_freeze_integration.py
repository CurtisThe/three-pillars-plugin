"""The freeze surviving the loop — the tail writes it, the seed keeps it.

design: review-convergence (Task 5.5, detailed-design-pr-loop §D5 + §D2)

Review bar: a round with 0 blocking findings and no degraded sentinel is the loop's
signal that the diff is understood, so `round_freeze.mark_if_clean` stamps
`frozen_at` = that round's head. The mark is only worth writing if it reaches the
NEXT round: `converge._seed_state` rebuilds iterate-state.v1.json before shelling
`run_round.py`, and a rebuild that keeps only the budget keys silently throws the
freeze away — Behavior 9 would then never fire in a real loop.

Pinned here, through the real `reproduce` CLI rather than a mock:

1. a clean round stamps `frozen_at` = the reviewed head, and the mark plus
   `review_weight` / `reproduced_blockers` survive `_seed_state`, still valid
   against `iterate-state.v1.json`;
2. a round that keeps a reproduced blocker stamps nothing (the freeze is earned by
   a clean tail, not by the round having run);
3. the tail never bootstraps state: a round with no state file leaves none, and a
   manifest with no `paths` (a `round_scratch` caller) is not an error.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import converge  # noqa: E402
import iterate_state  # noqa: E402
import reproduce  # noqa: E402
import round_freeze  # noqa: E402
import round_tail  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "iterate-state.v1.json"
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}

# A command reproducer whose exit violates its `expect` → `reproduced` (the
# expectation describes correct behaviour), so the claim stays a real blocker.
FAILING = {"kind": "command", "argv": [sys.executable, "-c", "raise SystemExit(1)"],
           "expect": {"exit": 0}}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _reply(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```\n"


def _note(n=1):
    return {"file": "src/a.py", "line_range": [n, n], "summary": f"nit {n}",
            "class": "C", "blocking": False}


def _blocker():
    return {"file": "src/a.py", "line_range": [1, 1], "summary": "real defect",
            "class": "P", "blocking": True, "reproducer": FAILING}


def _round(tmp_path, findings, state_path=None):
    """A round dir + a real one-commit repo, shaped like `round_scratch prepare`."""
    repo = tmp_path / "wt"
    rd = tmp_path / "proof" / "rounds" / "pr1" / "r2"
    log = tmp_path / "proof" / "iterate-log.2.md"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, ".three-pillars/config.json", "{}\n")
    _write(repo, "src/a.py", "a = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD")
    rp = rd / "angle0" / "reply.md"
    _write(rp.parent, rp.name, _reply(findings))
    paths = {"proof_root": str(tmp_path / "proof"), "log_path": str(log)}
    if state_path is not None:
        paths["state_path"] = str(state_path)
    manifest = {"pr_url": "https://github.com/o/r/pull/1", "round": 2, "ordinal": "r2",
                "base": "BASE", "paths": paths,
                "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                            "tier": "claude", "reply_path": str(rp)}]}
    _write(rd, "angles.json", json.dumps(manifest))
    return repo, head, rd, manifest


def _prior_state(**extra):
    """A state a mid-loop round leaves behind: required keys + budget counters."""
    state = {
        "phase": "awaiting-copilot", "iteration": 3, "max_iterations": 8,
        "max_wall_clock_sec": 14400, "started_at": "2026-10-01T00:00:00+00:00",
        "transitions": [], "original_diff_lines": 120,
        "consecutive_codereview_structural_rounds": 0,
    }
    state.update(extra)
    return state


def _schema_errors(state: dict) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    return [e.message for e in sorted(validator.iter_errors(state), key=str)]


def _read(state_path) -> dict:
    """The loop's own read half — the state the next round starts from."""
    state, bootstrapped = iterate_state.load_or_bootstrap(Path(state_path))
    assert not bootstrapped, "the read re-seeded a state that should have survived"
    return state


# --------------------------------------------------------------------------
# 1. A clean round's mark reaches the next round, through _seed_state
# --------------------------------------------------------------------------

def test_clean_round_marks_frozen_at_on_the_loop_state(tmp_path):
    """§D2 wiring: `reproduce` exits 0 on a 0-blocker round and stamps the head."""
    state_path = tmp_path / "proof" / "s.json"
    _write(tmp_path / "proof", "s.json", json.dumps(_prior_state(
        review_weight="light", reproduced_blockers=2), indent=2) + "\n")
    repo, head, rd, _ = _round(tmp_path, [_note()], state_path=state_path)

    assert reproduce.main(["--round-dir", str(rd), "--cwd", str(repo),
                           "--head", head]) == 0
    state = _read(state_path)
    assert state["frozen_at"] == head
    assert round_freeze.is_frozen(state)


def test_freeze_and_counters_survive_the_seed(tmp_path):
    """§D5: `_seed_state` keeps `frozen_at`, `review_weight`, `reproduced_blockers`.

    This is the whole point of the seed being two-sided: `converge` rebuilds the
    state before shelling `run_round.py`, so a key it drops is a key the loop loses
    at exactly the moment a clean round earned it.
    """
    state_path = tmp_path / "proof" / "s.json"
    _write(tmp_path / "proof", "s.json", json.dumps(_prior_state(
        review_weight="light", reproduced_blockers=2), indent=2) + "\n")
    repo, head, rd, _ = _round(tmp_path, [_note()], state_path=state_path)
    assert reproduce.main(["--round-dir", str(rd), "--cwd", str(repo),
                           "--head", head]) == 0

    converge._seed_state(state_path, head=head, now_iso="2026-10-02T00:00:00+00:00")
    seeded = _read(state_path)

    assert round_freeze.is_frozen(seeded), (
        "_seed_state dropped the freeze mark round_tail wrote on a clean round"
    )
    assert seeded["frozen_at"] == head
    assert seeded["review_weight"] == "light"
    assert seeded["reproduced_blockers"] == 2
    # The seed stays inside the shipped schema (additionalProperties: false).
    assert _schema_errors(seeded) == []
    # ...and the pre-existing two-sided behaviour is unchanged by the new keys.
    assert seeded["iteration"] == 3
    assert seeded["started_at"] == "2026-10-01T00:00:00+00:00"
    assert seeded["original_diff_lines"] == 120
    assert seeded["last_verdict"] == "minor-only"


# --------------------------------------------------------------------------
# 2. The freeze is earned by a clean tail, not by the round having run
# --------------------------------------------------------------------------

def test_reproduced_blocker_does_not_mark_frozen(tmp_path):
    """A blocker a reproducer demonstrated still blocks → no `frozen_at`."""
    state_path = tmp_path / "proof" / "s.json"
    _write(tmp_path / "proof", "s.json", json.dumps(_prior_state(
        review_weight="light"), indent=2) + "\n")
    repo, head, rd, _ = _round(tmp_path, [_blocker()], state_path=state_path)

    summary = reproduce.run_cli(rd, str(repo), head)
    assert summary["blocking"] == 1 and summary["tally"]["reproduced"] == 1
    state = _read(state_path)
    assert not round_freeze.is_frozen(state)
    assert "frozen_at" not in state


# --------------------------------------------------------------------------
# 3. The tail never bootstraps a state file
# --------------------------------------------------------------------------

def test_round_with_no_state_file_leaves_none(tmp_path, capsys):
    """`run_round` owns the bootstrap — the tail must not become a second writer."""
    state_path = tmp_path / "proof" / "s.json"
    repo, head, rd, _ = _round(tmp_path, [], state_path=state_path)
    assert not state_path.exists()

    assert reproduce.main(["--round-dir", str(rd), "--cwd", str(repo),
                           "--head", head]) == 0
    capsys.readouterr()
    assert not state_path.exists(), (
        "the round tail created an iterate-state file it does not own"
    )


def test_manifest_without_paths_is_not_an_error(tmp_path):
    """`round_scratch` callers pass a manifest with no `paths` — the tail still runs."""
    findings = [_note()]
    out = round_tail.annotate(findings, manifest={"round": 1}, cwd=str(tmp_path),
                              head="abc123", rounds_dir=None)
    assert [f["verdict"] for f in out] == ["minor"]
    assert not (tmp_path / "proof").exists(), "the tail invented a proof tree"
