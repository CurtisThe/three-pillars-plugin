"""A symlink CHAIN to a FIFO is refused — the gap between the code and its description.

`_reject_non_regular` calls `Path.stat()`, which resolves the **entire** symlink chain,
so `link -> link -> FIFO` is refused just like `link -> FIFO`. The prose used to say the
guard "resolves one symlink level", which UNDERSTATED it — safe-side, but untested, and
that combination is the dangerous one: `test_iterate_state_zero_length.py` exercises a
single link only, so a maintainer who "corrected" the code to match the old one-level
description with an explicit single `readlink` would silently reopen the chain-to-FIFO
hang with the whole suite still green.

This module closes that gap from both sides. The behaviour is pinned by the subprocess
tests below; the DESCRIPTION is pinned by
:func:`test_both_shipped_descriptions_say_whole_chain`, because until round 15 reverting
the prose to "one level" left the whole suite green — behaviour pinned, description not,
which is precisely the asymmetry that made the understatement dangerous in the first
place. Measured on the round-14 tree: reverting `SKILL.md`'s refusal sentence → **527
passed**; reverting `iterate_state.py`'s invariant 4 → **527 passed**. With the pin, each
is 1 failed.

Run in a SUBPROCESS with a hard timeout, deliberately — same reasoning as the one-hop
sibling: the regression is an INDEFINITE BLOCK inside `read_text()`, and an in-process
assertion would wedge the entire suite rather than fail it. `TimeoutExpired` IS the
regression signal.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_TIMEOUT_SEC = 20

# The two SHIPPED descriptions of the resolution, each as (file, anchor, window chars).
# The anchor opens the sentence that describes the refusal; the window is sized to stay
# INSIDE that sentence, so a whole-chain phrase somewhere else in the file — this test's
# own sibling docstrings included — cannot satisfy the claim.
_DESCRIPTION_SITES = (
    (_SCRIPTS.parent / "SKILL.md", "is **refused**, never replaced", 300),
    (_SCRIPTS / "iterate_state.py",
     "4. A non-regular node at ``state_path`` is **refused**, never replaced", 220),
)
_WHOLE_CHAIN = re.compile(r"whole (symlink )?chain|entire chain", re.I)


def _probe_source(target: Path) -> str:
    """A one-shot `load_or_bootstrap` call that prints its verdict and exits."""
    return (
        "import sys;"
        f"sys.path.insert(0, {str(_SCRIPTS)!r});"
        "from pathlib import Path;"
        "import iterate_state;"
        "\ntry:\n"
        f"    iterate_state.load_or_bootstrap(Path({str(target)!r}))\n"
        "except iterate_state.StateReadError as e:\n"
        "    print('REFUSED', e)\n"
        "else:\n"
        "    print('ACCEPTED')\n"
    )


def test_a_symlink_chain_to_a_fifo_is_refused_and_does_not_hang(tmp_path):
    """`state_path -> mid -> FIFO`: refused, not blocked, and nothing is mutated."""
    fifo = tmp_path / "backing-fifo"
    os.mkfifo(fifo)
    mid = tmp_path / "mid-link"
    mid.symlink_to(fifo)
    entry = tmp_path / "iterate-state.v1.json"
    entry.symlink_to(mid)

    # Precondition: the chain really is two hops, and lstat alone cannot see the FIFO.
    assert stat.S_ISLNK(entry.lstat().st_mode) and stat.S_ISLNK(mid.lstat().st_mode), (
        "this test is only meaningful over a MULTI-hop chain; one of the links is not "
        "a symlink, so it would duplicate the one-hop sibling instead of extending it"
    )

    try:
        done = subprocess.run(
            [sys.executable, "-c", _probe_source(entry)],
            capture_output=True, text=True, timeout=_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - the regression itself
        raise AssertionError(
            "load_or_bootstrap BLOCKED on a symlink CHAIN to a FIFO. The non-regular "
            "refusal must resolve the WHOLE chain, not one hop — `Path.stat()` does "
            "this for free, so the likely cause is someone replacing it with a single "
            "explicit readlink to match a 'resolves one level' description. That "
            "description was the thing that was wrong; the guard was not."
        ) from None

    assert "REFUSED" in done.stdout, (
        f"a symlink chain ending at a FIFO must raise StateReadError, not be accepted: "
        f"stdout={done.stdout!r} stderr={done.stderr[-300:]!r}"
    )
    assert stat.S_ISFIFO(fifo.lstat().st_mode) and entry.is_symlink() \
        and mid.is_symlink(), (
        "the refusal must leave the whole chain and its target exactly as it found them"
    )


def test_a_symlink_chain_to_a_real_state_file_still_reads_through(tmp_path):
    """The chain refusal must not become a blanket ban on links.

    Without this, "refuse anything reached through more than one link" would pass the
    test above while breaking every legitimate indirection (a state path reached through
    a symlinked run directory, say). The guard's subject is the RESOLVED NODE TYPE, not
    the depth of the chain, and that distinction is what this pins.
    """
    real = tmp_path / "real-state.json"
    real.write_text('{"schema": "iterate-state.v1", "iteration": 3}', encoding="utf-8")
    mid = tmp_path / "mid-link"
    mid.symlink_to(real)
    entry = tmp_path / "iterate-state.v1.json"
    entry.symlink_to(mid)

    sys.path.insert(0, str(_SCRIPTS))
    import iterate_state

    state, bootstrapped = iterate_state.load_or_bootstrap(entry)
    assert bootstrapped is False, (
        "a chain resolving to a real, non-empty state file must be READ, not re-seeded"
    )
    assert state["iteration"] == 3, f"read the wrong document through the chain: {state}"


def test_both_shipped_descriptions_say_whole_chain():
    """The prose pin: reverting either shipped description to "one level" fails here.

    Scope, stated no wider than it is: this asserts that each of the two sites in
    :data:`_DESCRIPTION_SITES` — `tp-pr-iterate/SKILL.md`'s refusal sentence and
    `iterate_state.py`'s invariant 4 — says WHOLE CHAIN inside the sentence that
    describes the resolution. It does NOT assert that the phrase "one level" is absent
    anywhere: both FILES deliberately carry that phrase inside a do-not-narrow-the-guard
    warning, so banning the string would forbid the warning that exists to prevent the
    very change this pin is here to catch.

    Why a prose pin at all, when the behaviour is already pinned above: the two are
    guarded independently. Through round 14 the tests above were green while the
    description understated the guard, and reverting the description alone stayed green —
    so nothing stopped the next maintainer from "correcting" the code to match the weaker
    prose and reopening the chain-to-FIFO hang. The failure this catches is the prose
    moving first.
    """
    for path, anchor, window in _DESCRIPTION_SITES:
        flat = " ".join(path.read_text(encoding="utf-8").split())
        assert flat.count(anchor) == 1, (
            f"{path.name}: expected exactly one description opening with {anchor!r}; "
            f"found {flat.count(anchor)}. This pin reads the FIRST occurrence, so a "
            f"duplicate would let it pass on a copy while the live sentence says "
            f"something else — retarget the anchor in the same commit that moves the prose."
        )
        sentence = flat[flat.index(anchor):][:window]
        assert _WHOLE_CHAIN.search(sentence), (
            f"{path.name} no longer describes the refusal as resolving the WHOLE symlink "
            f"chain: {sentence!r}\n\n"
            "`_reject_non_regular` uses `Path.stat()`, which is fully resolving, so "
            "`link -> link -> FIFO` is refused exactly like `link -> FIFO`. A 'resolves "
            "one level' description understates that, and the understatement is what "
            "talks a maintainer into narrowing the guard to a single explicit readlink — "
            "which reopens the indefinite `read_text()` hang the tests above exist to "
            "prevent. Correct the code or correct this pin; do not weaken the prose."
        )
