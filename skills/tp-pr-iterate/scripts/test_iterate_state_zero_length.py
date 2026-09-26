"""A ZERO-LENGTH state file is ABSENT, not corrupt — the seed's last crash window.

`_create_exclusive` claims the name with `open(path, "x")` and only then swaps the
content in via `os.replace`. That ordering is what makes the seed crash-atomic
without an `os.link` (and so without a per-filesystem errno allowlist), but it leaves
one instant where the name exists holding nothing: a real SIGKILL mid-write was
observed to leave `path` at exactly **0 bytes**, with the partial content stranded in
the tmp.

Read as *corrupt*, that residue is a permanent `state-read-failed` wedge — the
bootstrap never overwrites, so no later round can repair it. Read as *absent*, it
self-heals on the next round. This module pins the second reading, and pins its
edges: one byte of garbage still refuses, and a symlink is never "zero-length".

One rule, one module — at BOTH levels: the helper's behaviour, and the same claim at
the `run_round.py` CLI boundary, which is where both SKILL.md files make it to
callers and where the mapping onto `state_bootstrapped` can regress on its own.

Split from `test_iterate_state_atomic_writes.py` at its 300-line soft-warn
(CLAUDE.md §File Size Limits).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import iterate_state  # noqa: E402

_NOW = "2026-09-09T00:00:00+00:00"


def test_a_zero_length_state_file_is_bootstrapped_not_refused(tmp_path):
    """The one window the claim-then-replace shape leaves open, closed on the read.

    A crash between `_create_exclusive`'s claim and its `os.replace` leaves `path`
    at exactly 0 bytes (verified against a real SIGKILL). Treated as *corrupt* that
    is a permanent `state-read-failed` wedge — never-overwrite means no later round
    can repair it. Treated as *absent* it self-heals on the next round.

    This is the module's own forensic rationale applied honestly, not an exception to
    it: corrupt bytes are preserved because they are the only record of what went
    wrong, and an empty file has no bytes to preserve.
    """
    path = tmp_path / "iterate-state.v1.json"
    path.touch()
    assert path.stat().st_size == 0, "precondition: the crash residue is 0 bytes"

    state, bootstrapped = iterate_state.load_or_bootstrap(path, now=_NOW)

    assert bootstrapped is True, (
        "a zero-length state file must be re-seeded, not raise StateReadError — "
        "refusing it wedges every later round with nothing able to repair it"
    )
    assert state == iterate_state.fresh_state(now=_NOW)
    assert json.loads(path.read_text(encoding="utf-8")) == state, (
        "the re-seed must be persisted, not just returned"
    )
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


@pytest.mark.parametrize("kind", ["fifo", "socket"])
def test_a_non_regular_node_is_refused_not_clobbered(tmp_path, kind):
    """`lstat().st_size == 0` is true of every non-regular node, not just crash residue.

    Without the `S_ISREG` half of the test, a FIFO and a bound `AF_UNIX` socket at
    `state_path` were each DESTROYED and replaced by a seeded regular file — rc 0,
    `state_bootstrapped: true`, no diagnostic (measured). That is the never-overwrite
    invariant broken on a path that holds no state at all.

    Refusing is also what keeps the round from HANGING: falling through to the read
    would block on a FIFO until some writer appears, with no envelope and no exit code.
    """
    import os
    import socket
    import stat

    path = tmp_path / "iterate-state.v1.json"
    sock = None
    if kind == "fifo":
        os.mkfifo(path)
        assert stat.S_ISFIFO(path.lstat().st_mode)
    else:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(path))
        assert stat.S_ISSOCK(path.lstat().st_mode)

    try:
        assert path.lstat().st_size == 0, (
            "precondition: the node reports size 0, which is why the size test alone "
            "was not enough"
        )
        assert iterate_state._is_zero_length(path) is False, (
            "a non-regular node must not qualify for the zero-length re-seed"
        )
        with pytest.raises(iterate_state.StateReadError, match="not a regular file"):
            iterate_state.load_or_bootstrap(path)

        mode = path.lstat().st_mode
        assert not stat.S_ISREG(mode), (
            f"the {kind} at state_path was replaced by a regular file — the refusal "
            f"must leave the node exactly as it found it"
        )
    finally:
        if sock is not None:
            sock.close()


def test_a_symlink_to_a_real_state_file_still_reads_through(tmp_path):
    """The non-regular refusal must NOT widen into a symlink refusal.

    Symlink handling is unchanged by the `S_ISREG` guard: `_create_exclusive` refuses
    to seed through one, `write_state_atomic` replaces one, and a link pointing at a
    readable state file still resolves. Only FIFOs / sockets / directories are refused.
    """
    real = tmp_path / "real-state.json"
    real.write_text(json.dumps({"phase": "awaiting-review"}), encoding="utf-8")
    link = tmp_path / "iterate-state.v1.json"
    link.symlink_to(real)

    state, bootstrapped = iterate_state.load_or_bootstrap(link)

    assert bootstrapped is False
    assert state == {"phase": "awaiting-review"}


def test_a_nonempty_unreadable_state_file_still_refuses(tmp_path):
    """The zero-length rule is keyed on LENGTH, not on unreadability.

    One byte of garbage is still a forensic record: it keeps `state-read-failed` and
    is never overwritten. Widening the rule to "does not parse" would silently reset
    a real loop's counters.
    """
    path = tmp_path / "iterate-state.v1.json"
    path.write_text("{", encoding="utf-8")  # one byte, unparseable

    with pytest.raises(iterate_state.StateReadError):
        iterate_state.load_or_bootstrap(path)

    assert path.read_text(encoding="utf-8") == "{", "the evidence must survive"


def test_a_symlink_to_an_empty_file_is_refused_not_re_seeded(tmp_path):
    """`lstat`, not `stat`: the zero-length branch must not reopen the symlink hole.

    Asserted through `load_or_bootstrap`, not against the private `_is_zero_length`:
    the guarantee that matters is that nothing is WRITTEN through the link, and a
    predicate returning False is only evidence for that if the branch it feeds is
    also exercised. (A helper renamed or bypassed would have kept the old assertion
    green while the seed happily wrote to the target.)

    A symlink's own size is its target string's length, never 0, so the link cannot
    take the re-seed branch; the read below then finds an empty document and refuses.
    """
    target = tmp_path / "elsewhere.json"
    target.touch()
    link = tmp_path / "iterate-state.v1.json"
    link.symlink_to(target)

    with pytest.raises(iterate_state.StateReadError):
        iterate_state.load_or_bootstrap(link, now=_NOW)

    assert target.stat().st_size == 0, (
        "nothing may be written through the link to its target"
    )
    assert link.is_symlink(), "the link itself must survive untouched"


# ---------- The same rule at the CLI boundary, where callers meet it ----------


def _run_cli(payload: dict):
    """Invoke run_round.py as a subprocess; return (rc, envelope-or-None, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "run_round.py")],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    try:
        envelope = json.loads(proc.stdout.decode().strip())
    except Exception:
        envelope = None
    return proc.returncode, envelope, proc.stderr.decode(errors="replace")


def test_the_cli_bootstraps_a_zero_length_state_file(tmp_path):
    """The claim both SKILL.md files pin is a CLI-level claim, so pin it there.

    `tp-pr-iterate/SKILL.md` §Cold-resume contract and `tp-run-full-design/SKILL.md`'s
    Tier-7 bullet both promise a caller of `run_round.py` that a zero-length state
    file counts as absent and is re-seeded (exit 0, `state_bootstrapped: true`) rather
    than refused as `state-read-failed`. Everything above tests the helper; this is
    the only test that exercises the boundary the prose actually describes — the
    mapping from `load_or_bootstrap`'s return onto the envelope could regress without
    touching `iterate_state.py` at all.
    """
    state_path = tmp_path / "iterate-state.v1.json"
    state_path.touch()

    rc, envelope, stderr = _run_cli({
        "state_path": str(state_path),
        "head_sha": "abc1234",
        "codereview_findings": [],
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": {"review": {"expects_copilot": False},
                   "ci": {"expects_github_checks": False}},
    })

    assert rc == 0, (
        f"a zero-length state file is the documented start condition, not a "
        f"state-read-failed refusal; got rc={rc}, envelope={envelope!r}, "
        f"stderr={stderr[-300:]!r}"
    )
    assert envelope is not None and envelope.get("state_bootstrapped") is True, (
        "the round that re-seeds must SAY so in the envelope — a silent re-seed is "
        f"indistinguishable from a resumed loop: {envelope!r}"
    )
    assert json.loads(state_path.read_text(encoding="utf-8")), (
        "the file must no longer be empty after the round"
    )


def test_a_symlink_to_a_fifo_is_refused_and_does_not_hang(tmp_path):
    """Invariant 4 states the non-regular refusal UNQUALIFIED — prove it through a link.

    `_reject_non_regular` used to wave every symlink through, so a link to a FIFO
    reached `read_text()` and BLOCKED the round indefinitely: no envelope, no exit
    code, no diagnostic (measured). A hang is the one failure this wrapper promises
    never to have, so the guard now resolves the link. This pins the ONE-hop case;
    `test_iterate_state_symlink_chain.py` pins the multi-hop chain, which the guard
    refuses identically because `Path.stat()` resolves the whole chain.

    Run in a SUBPROCESS with a hard timeout, deliberately: a regression here hangs
    forever, and an in-process assertion would wedge the whole suite rather than fail
    it. `TimeoutExpired` IS the regression signal.
    """
    import os
    import stat

    fifo = tmp_path / "backing-fifo"
    os.mkfifo(fifo)
    link = tmp_path / "iterate-state.v1.json"
    link.symlink_to(fifo)

    probe = (
        "import sys;"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r});"
        "from pathlib import Path;"
        "import iterate_state;"
        "\ntry:\n"
        f"    iterate_state.load_or_bootstrap(Path({str(link)!r}))\n"
        "except iterate_state.StateReadError as e:\n"
        "    print('REFUSED', e)\n"
        "else:\n"
        "    print('ACCEPTED')\n"
    )
    try:
        done = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - the regression itself
        raise AssertionError(
            "load_or_bootstrap BLOCKED on a symlink to a FIFO — the non-regular "
            "refusal must resolve the link, or invariant 4 and "
            "tp-pr-iterate/SKILL.md's unqualified claim are both false."
        ) from None

    assert "REFUSED" in done.stdout, (
        f"a symlink to a FIFO must raise StateReadError, not be accepted: "
        f"stdout={done.stdout!r} stderr={done.stderr[-300:]!r}"
    )
    assert stat.S_ISFIFO(fifo.lstat().st_mode) and link.is_symlink(), (
        "the refusal must leave both the link and its target exactly as it found them"
    )
