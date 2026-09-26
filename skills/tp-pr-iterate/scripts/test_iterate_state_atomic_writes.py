"""Unit-level contract of `iterate_state`: exclusivity, self-healing, atomicity.

Split from `test_run_round_bootstrap_exit_codes.py`, which keeps the *CLI* exit-code
contract (subprocess level). This file exercises the helper directly, so it can reach
the syscall-level behaviour — the seed's exclusive create and the write-back's
`os.replace` — that a subprocess cannot be steered into without a shim.

What the seed does and does not guarantee against a CONCURRENT bootstrap of the same
path lives in `test_iterate_state_concurrency.py`; the zero-length rule in
`test_iterate_state_zero_length.py`.
"""
from __future__ import annotations

import errno
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import iterate_state  # noqa: E402

_ROOT_SKIP = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="chmod-synthesised failure is ineffective for root (CAP_DAC_OVERRIDE)",
)

_NOW = "2026-09-09T00:00:00+00:00"


# ---------- The probe and the seed write are both guarded ----------


@_ROOT_SKIP
def test_probe_failure_raises_state_write_error(tmp_path):
    """An undecidable exists() must fail closed, not fall through to a write.

    Writing on an undecidable probe could clobber a state we merely could not see.
    """
    parent = tmp_path / "notraverse"
    parent.mkdir()
    (parent / "state.json").write_text('{"phase": "fixing"}', encoding="utf-8")
    parent.chmod(0o000)
    try:
        with pytest.raises(iterate_state.StateWriteError):
            iterate_state.load_or_bootstrap(parent / "state.json")
    finally:
        parent.chmod(0o700)
    # The state it could not see must survive untouched.
    assert json.loads((parent / "state.json").read_text(encoding="utf-8")) == {
        "phase": "fixing"
    }


@_ROOT_SKIP
def test_write_failure_raises_state_write_error_not_os_error(tmp_path):
    """The seed write's OSError is mapped, so no caller sees a bare OSError."""
    parent = tmp_path / "readonly"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        with pytest.raises(iterate_state.StateWriteError):
            iterate_state.load_or_bootstrap(parent / "state.json")
    finally:
        parent.chmod(0o700)


def test_state_write_error_is_not_a_state_read_error():
    """`state-read-failed` keeps its narrow meaning (exists + unparseable), so the
    write failure must NOT be catchable as StateReadError — run_round.py maps the two
    onto different tokens."""
    assert not issubclass(iterate_state.StateWriteError, iterate_state.StateReadError)
    assert not issubclass(iterate_state.StateReadError, iterate_state.StateWriteError)


# ---------- Atomicity + exclusivity of the seed write ----------


def test_bootstrap_creates_missing_parents_several_levels_deep(tmp_path):
    """`parents=True` is load-bearing and must be exercised.

    Every other bootstrap test uses exactly ONE missing level, which plain
    `mkdir(exist_ok=True)` also satisfies — so dropping `parents=True` left the whole
    suite green. Three missing levels makes the flag's absence fail.
    """
    path = tmp_path / "a" / "b" / "c" / "iterate-state.v1.json"
    assert not path.parent.exists()

    state, bootstrapped = iterate_state.load_or_bootstrap(path, now=_NOW)

    assert bootstrapped is True
    assert path.exists(), "the bootstrap must create every missing parent level"
    assert json.loads(path.read_text(encoding="utf-8")) == state


def test_bootstrap_leaves_nothing_but_the_state_file(tmp_path):
    """A successful seed leaves exactly one file — no scratch, no residue."""
    path = tmp_path / "run" / "iterate-state.v1.json"
    iterate_state.load_or_bootstrap(path, now=_NOW)
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_bootstrap_does_not_write_through_a_dangling_symlink(tmp_path):
    """`exists()` follows symlinks, so a dangling one reported absent and a plain
    write landed the seed at the link TARGET — outside the named path — while still
    reporting success. Exclusive create refuses the symlink instead."""
    target = tmp_path / "elsewhere.json"
    link = tmp_path / "state.json"
    link.symlink_to(target)
    assert not link.exists(), "precondition: a dangling symlink reports absent"

    with pytest.raises((iterate_state.StateReadError, iterate_state.StateWriteError)):
        iterate_state.load_or_bootstrap(link)

    assert not target.exists(), (
        "the seed must not be written through the symlink to its target"
    )


def test_a_failed_seed_self_heals_by_leaving_no_file(tmp_path, monkeypatch):
    """A write that dies part-way must leave the path ABSENT, not truncated.

    Truncated-plus-never-overwrite is the permanent `state-read-failed` wedge this
    module exists to remove: every later round would refuse and none could repair it.
    The exclusive create always unlinks its tmp, and unlinks the claimed NAME only
    while that name is still this call's own EMPTY claim — an unconditional unlink
    would delete a concurrent round's live state file. Here the claim is still empty,
    so the path is removed and the next round bootstraps again.
    ENOSPC is injected at `os.fsync`, i.e. AFTER the create and the write — the
    hardest moment, where a partial file actually exists on disk.
    """
    path = tmp_path / "run" / "iterate-state.v1.json"

    def boom(fd):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "fsync", boom)

    with pytest.raises(iterate_state.StateWriteError):
        iterate_state.load_or_bootstrap(path)

    assert not path.exists(), (
        "a failed seed must leave NO file — a truncated one would wedge every later "
        "round against the never-overwrite invariant"
    )
    assert list(path.parent.iterdir()) == [], "nothing partial may survive"


def test_the_seed_never_overwrites_an_existing_file(tmp_path):
    """`open(path, "x")` is O_CREAT|O_EXCL, so for a file that already has CONTENT the
    kernel enforces never-overwrite, not the `exists()` probe above it.

    That closes the probe's TOCTOU for this case only. The zero-length window is still
    open BY DESIGN: between the claim and the content swap the name exists holding
    nothing, and `load_or_bootstrap` reads that as absent. See its "Serial callers
    only" note — the race is documented, not fixed.
    """
    path = tmp_path / "iterate-state.v1.json"
    path.write_text('{"phase": "fixing", "iteration": 7}', encoding="utf-8")

    assert iterate_state._create_exclusive(path, '{"clobbered": true}') is False
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "phase": "fixing",
        "iteration": 7,
    }


def test_the_seed_stages_the_bytes_off_the_named_path(tmp_path):
    """The claim and the content arrive by two different routes.

    `open(path, "x")` claims the name and writes NOTHING; the JSON goes to a sibling
    tmp and lands via `os.replace`. That ordering is what makes the seed crash-atomic
    without an `os.link` (and so without a per-filesystem errno allowlist): the
    unlink-on-exception below cannot run on SIGKILL/OOM/power-loss, so any bytes
    written *through* the claimed handle would be a truncated `state.json`.

    Pinned by observing the file at the moment `os.replace` is called: `path` must
    exist (claimed) and be EMPTY (uncontaminated), with the payload in the tmp.
    """
    path = tmp_path / "run" / "iterate-state.v1.json"
    observed = {}
    real_replace = os.replace

    def spy(src, dst):
        observed["path_size"] = Path(dst).stat().st_size
        observed["tmp_size"] = Path(src).stat().st_size
        observed["tmp_is_sibling"] = Path(src).parent == Path(dst).parent
        return real_replace(src, dst)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(os, "replace", spy)
    try:
        assert iterate_state._create_exclusive(path, '{"seeded": true}') is True
    finally:
        monkey.undo()

    assert observed["path_size"] == 0, (
        "the claimed name must hold NO bytes until the replace — a partial write at "
        f"`path` is the truncation this shape exists to prevent (got "
        f"{observed['path_size']} bytes)"
    )
    assert observed["tmp_size"] > 0 and observed["tmp_is_sibling"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"seeded": True}
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name], (
        "the replace consumes the tmp; nothing may be left lying around"
    )


# ---------- write_state_atomic: the per-round write-back ----------


def test_write_state_atomic_replaces_and_leaves_no_tmp(tmp_path):
    """The write-back OVERWRITES by design — os.replace, not the seed's exclusive create."""
    path = tmp_path / "run" / "state.json"
    iterate_state.write_state_atomic(path, {"phase": "fixing", "iteration": 1})
    iterate_state.write_state_atomic(path, {"phase": "fixing", "iteration": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"phase": "fixing",
                                                          "iteration": 2}
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_write_state_atomic_leaves_prior_bytes_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    iterate_state.write_state_atomic(path, {"iteration": 1})
    before = path.read_bytes()

    def boom(src, dst):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        iterate_state.write_state_atomic(path, {"iteration": 2})

    assert path.read_bytes() == before, "a failed write-back must not truncate"
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


# ---------- The DEFAULT started_at — the branch production actually takes ----------


def test_default_started_at_is_timezone_aware():
    """Pin the branch that ships: `run_round.py` always calls `fresh_state()` with no
    `now=`, so the default IS production. It must be timezone-AWARE.

    `round_budget.tick` reads `started_at` on every round and fails closed on a naive
    value (`budget-error`). And `started_at` is persisted and never rewritten, so a
    naive default wedges every LATER round, wall-clock guard included. Nothing else in the suite constrained the default:
    mutating it to a bare `datetime.now()` left the whole suite green, while the
    deleted `now=` validation guarded only an injected seam production never uses.
    """
    started_at = iterate_state.fresh_state()["started_at"]
    parsed = datetime.fromisoformat(started_at)

    assert parsed.tzinfo is not None and parsed.utcoffset() is not None, (
        f"the default started_at must be timezone-aware; got {started_at!r}"
    )


def test_caps_documented_as_enforced_by_round_budget_tick():
    """iterate-convergence-budget Task 3.6: the cap is informational state, enforced by
    `round_budget.tick` (limits from config), not "nothing" / the deleted guards."""
    src = Path(iterate_state.__file__).read_text(encoding="utf-8")
    assert iterate_state.DEFAULT_MAX_ITERATIONS == 6
    assert "round_budget.tick" in src
    assert "_check_guards" not in src and "run_loop" not in src
    assert "nothing on the shipped" not in src
