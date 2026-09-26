"""What the seed guarantees against a COMPETITOR — and, precisely, what it does not.

`_create_exclusive` claims the name with `open(path, "x")` and only then swaps the
content in via `os.replace`. `O_EXCL` is a real guarantee, but its reach is exactly
"a name that already exists": between the claim and the replace the name exists
holding NOTHING, and `load_or_bootstrap`'s zero-length rule reads nothing as *absent*.

So there are two different situations, and this module keeps them apart:

* a competitor whose file already has CONTENT — the loser reads it and must not
  claim `state_bootstrapped`. **Guaranteed**, by the kernel;
* a competitor whose CLAIM is still in flight (0 bytes) — indistinguishable from the
  residue of a crash mid-seed, so it is re-seeded. **Not guaranteed, and not
  fixable in this shape**; pinned here as the limitation it is, next to the
  guarantee it is so easily mistaken for.

Concurrency was measured, not assumed: interleaving a second `load_or_bootstrap` at
the first one's `os.replace` yields two `bootstrapped=True` results and a final
`iteration: 0` even when the second round advanced the loop to 7. The proposed
"unlink then re-claim with O_EXCL" was implemented and run against the same
interleave: identical `iteration: 0`, because the re-claim trivially succeeds against
the claim it just unlinked and the first caller's `os.replace` overwrites the winner
regardless. It only adds a way to delete another round's claim. Mutual exclusion (a
lock, or an atomic exclusive create *with* the content) is the only real fix, and
nothing in the loop runs rounds concurrently — `run_round.py` is shelled out one
round at a time.

Split from `test_iterate_state_atomic_writes.py` (277 lines, at its soft-warn) —
one concern, one module (CLAUDE.md §File Size Limits).
"""
from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import iterate_state  # noqa: E402


def test_a_competitor_with_content_is_never_overwritten(tmp_path, monkeypatch):
    """The guarantee: a file that appears WITH CONTENT between the probe and the
    create is read, not clobbered, and the loser does not claim `state_bootstrapped`.

    `O_EXCL` enforces this in the kernel, so it holds however the file got there.
    A second `state_bootstrapped: true` would mean a round silently reset the loop's
    counters. Note what carries the guarantee: the winner's bytes. The empty-claim
    case below is a different situation with a different answer.
    """
    path = tmp_path / "iterate-state.v1.json"
    winner = {"phase": "fixing", "iteration": 7}

    real_create = iterate_state._create_exclusive

    def racing_create(p, text):
        p.write_text(json.dumps(winner), encoding="utf-8")  # the other round wins
        return real_create(p, text)

    monkeypatch.setattr(iterate_state, "_create_exclusive", racing_create)

    state, bootstrapped = iterate_state.load_or_bootstrap(path)

    assert bootstrapped is False, "the loser must not claim state_bootstrapped"
    assert state == winner, "the winner's state must survive, not be overwritten"


def test_a_claim_still_in_flight_is_re_seeded_this_is_the_documented_limit(tmp_path):
    """The limitation, interleaved AT THE CLAIM rather than at the write.

    This pins the behaviour `load_or_bootstrap`'s "Serial callers only" note
    describes, so nobody rediscovers it as a surprise and nobody reads the test above
    as a concurrency guarantee it is not. A second call that arrives while the first
    is between its claim and its `os.replace` sees 0 bytes, cannot tell a live claim
    from crash residue, and re-seeds: BOTH calls report `bootstrapped=True`, and the
    first caller's replace lands last, so a loop the second round had advanced to
    `iteration: 7` ends at `iteration: 0`.

    That is a wrong answer, not a refusal, and the fix is mutual exclusion — out of
    reach of this seam (see the module docstring for the measured "unlink then
    re-claim" attempt, which does not change this outcome). What the loop relies on
    instead is that it never runs two rounds against one `state_path`.

    If a later change DOES make concurrent bootstrap safe, this test is the one to
    delete — deliberately, with the docstrings that describe the limit.
    """
    path = tmp_path / "iterate-state.v1.json"
    real_replace = os.replace
    observed: dict = {}

    def interleave_at_the_claim(src, dst):
        # Runs ONCE (the flag is set before re-entering), while `path` is the first
        # caller's still-empty claim.
        if not observed.get("entered"):
            observed["entered"] = True
            _, observed["second"] = iterate_state.load_or_bootstrap(path)
            # ...and that second round then does a round's work and persists it.
            iterate_state.write_state_atomic(path, {"phase": "fixing", "iteration": 7})
        return real_replace(src, dst)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(os, "replace", interleave_at_the_claim)
    try:
        _, first = iterate_state.load_or_bootstrap(path)
    finally:
        monkey.undo()

    assert first is True and observed["second"] is True, (
        "both calls bootstrap: the second cannot tell a live 0-byte claim from the "
        "residue of a crash mid-seed"
    )
    assert json.loads(path.read_text(encoding="utf-8"))["iteration"] == 0, (
        "the last replace wins, so the second round's advanced state is lost — the "
        "documented cost of running two bootstraps against one state_path"
    )


def test_a_failed_seed_does_not_delete_bytes_it_did_not_write(tmp_path):
    """The cleanup unlinks OUR empty claim, not whatever happens to be at the name.

    `os.replace` is atomic: if it raised, the swap never happened, so content at
    `path` cannot be ours. Unlinking unconditionally therefore deleted a *valid*
    state file that another writer had put there in the meantime — turning a failed
    seed into data loss. Zero-length (still our claim) is the only case worth
    cleaning up.
    """
    path = tmp_path / "iterate-state.v1.json"
    live = json.dumps({"phase": "fixing", "iteration": 7})

    def fill_then_fail(src, dst):
        Path(dst).write_text(live, encoding="utf-8")  # another writer lands first
        raise OSError(errno.ENOSPC, "No space left on device")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(os, "replace", fill_then_fail)
    try:
        with pytest.raises(OSError):
            iterate_state._create_exclusive(path, '{"seeded": true}')
    finally:
        monkey.undo()

    assert path.exists() and path.read_text(encoding="utf-8") == live, (
        "the failure path must not delete a state file it did not write"
    )
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name], (
        "our own tmp is still cleaned up"
    )
