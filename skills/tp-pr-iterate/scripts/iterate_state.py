"""Cold-start bootstrap for the tp-pr-iterate loop state (iterate-state.v1).

``run_round.py`` used to read ``state_path`` with a bare ``open()``, so an **absent**
state file and a **corrupt** one were indistinguishable and round 0 of every loop
escalated exit 2 unless an operator hand-seeded a file. This module supplies the
absent-vs-invalid split:

* absent  → seed a schema-valid round-0 state, write it, report ``bootstrapped=True``;
* present → read it, and raise :class:`StateReadError` if it will not parse.

Invariants:

1. **Claim the name, then stage the content in** (:func:`_create_exclusive`).
2. **Never overwrite an existing file that has content** from the bootstrap path.
3. **Zero length means absent** — but only for a REGULAR file (see
   :func:`_is_zero_length`).
4. A non-regular node at ``state_path`` is **refused**, never replaced — including one
   reached through a symlink, of any depth: the guard resolves the **whole symlink
   chain**, not one hop (:func:`_reject_non_regular`).

Design rationale, measurements and the options that were rejected live in
``three-pillars-docs/completed-tp-designs/pr-iterate-state-bootstrap/decisions.md``,
not here.

Stdlib-only by contract: ``run_round.py`` is C1-clean (stdlib + sibling modules only),
so schema validation of the bootstrapped state lives in the tests, not here.
"""
from __future__ import annotations

import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Loop caps for a fresh state — INFORMATIONAL. The schema requires the fields, so they
# are written, but nothing reads them: ``round_budget.tick`` (called by
# ``loop_driver.run_round`` on every ``run_round.py`` round) enforces the round cap and
# the wall clock from ``round_budget.limits(config)`` (``pdw.guards.*`` over its
# defaults: ``round_cap`` 3 by review weight, ``wall_clock_sec`` 14400) and counts
# ``iteration`` itself.
DEFAULT_MAX_ITERATIONS = 6
DEFAULT_MAX_WALL_CLOCK_SEC = 14400


class StateReadError(Exception):
    """The state at ``path`` could not be read as a JSON object.

    Covers three cases, all of which fail closed onto ``run_round.py``'s pre-existing
    ``event_token="state-read-failed"`` / exit 2:

    * ``path`` exists with content that will not parse, or parses to a non-object;
    * ``path`` is a **dangling symlink** — ``lstat`` succeeds, the read raises
      ``FileNotFoundError``. So this is NOT "raised only for a path that exists":
      ``Path.exists()`` answers False there while ``_create_exclusive`` still refuses
      to write through the link;
    * ``path`` is — or resolves through a symlink chain of any depth to — a
      **non-regular** node (FIFO, socket, directory); see :func:`_reject_non_regular`.

    Absence of an ordinary file is a start condition, not an error.
    """


class StateWriteError(Exception):
    """The bootstrap could not establish a state file at ``path``.

    Covers both halves of the seed that can fail against the filesystem:

    * the **existence probe** — ``Path.exists()`` is not total. ``EACCES`` is not in
      pathlib's ``_IGNORED_ERRNOS``, so a state file inside a non-traversable
      directory makes ``exists()`` itself raise and absence is *undecidable*;
    * the **seed write** — ``mkdir(parents=True)`` and the create both raise
      ``OSError`` subtypes.

    ``run_round.py`` maps this to ``event_token="state-write-failed"`` / exit 2. A probe
    that cannot decide existence must NOT fall through to a write — that would risk
    clobbering a state we simply could not see — so the undecidable case fails closed.
    """


def fresh_state(*, now: str | None = None) -> dict:
    """Return a schema-valid round-0 iterate-state.

    ``converge.py::_seed_state`` is a COUSIN, not a superset or a subset — the two seeds
    answer to the same schema and diverge on purpose, so do not "restore parity" between
    them in either direction. This one is the *cold* seed: ``last_verdict`` is ``None``
    (not ``"minor-only"``) and ``iteration`` is 0, so a bootstrapped round 0 is *not*
    convergence-eligible and cannot converge a PR that no reviewer has looked at. It also
    carries three fields ``_seed_state`` does not write at all (``resolved_thread_ids``,
    ``seen_thread_ids``, ``reviewed_head_shas``) and opens in ``phase="awaiting-review"``
    where the convergence seed opens in ``"awaiting-copilot"``. What the two DO share is
    the schema: `test_state_bootstrap_siblings.py` validates both against
    ``schemas/iterate-state.v1.json``, which is the only parity that is load-bearing.

    ``now`` is a test seam (ISO-8601 string) taken **verbatim and unvalidated**;
    production never passes it. The default is timezone-AWARE
    (``datetime.now(tz=timezone.utc)``), which the wall-clock check needs:
    ``round_budget.tick`` subtracts ``started_at`` from an aware ``now`` on every round and
    fails closed (``budget-exhausted`` / ``budget-error``) on a naive or unparseable
    value, so a naive injected ``now`` stops the loop. Pass an aware ISO-8601 string or
    nothing.
    """
    return {
        "phase": "awaiting-review",
        "iteration": 0,
        "max_iterations": DEFAULT_MAX_ITERATIONS,
        "max_wall_clock_sec": DEFAULT_MAX_WALL_CLOCK_SEC,
        "started_at": now if now is not None else datetime.now(tz=timezone.utc).isoformat(),
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": None,
        "consecutive_structural_rounds": 0,
        "last_verdict": None,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "resolved_thread_ids": [],
        "seen_thread_ids": [],
        "reviewed_head_shas": [],
        "last_codereview_findings": [],
        "last_codereview_head_sha": None,
    }


def _create_exclusive(path: Path, text: str) -> bool:
    """Create ``path`` containing ``text``. Return False if it already existed.

    Two steps, in this order — **claim the name, then swap the content in**:

    1. ``open(path, "x")`` (``O_CREAT | O_EXCL``) to claim the name, immediately
       closed. Nothing is written through this handle.
    2. write ``text`` to a sibling tmp, ``flush``, ``fsync``, then ``os.replace``
       the tmp onto the name already claimed in step 1.

    Step 1 buys exclusivity and **symlink refusal**: ``exists()`` follows symlinks, so a
    *dangling* one reports absent and a plain write would land the seed at the link
    target while reporting success. ``O_EXCL`` raises ``FileExistsError`` on a symlink,
    dangling or not, and creates nothing.

    Step 2 buys crash-atomicity: writing the JSON *through* the exclusive handle left a
    TRUNCATED ``state.json`` when the process was killed mid-write, and
    truncated-plus-never-overwrite is a permanent ``state-read-failed`` wedge no later
    round can repair. Staging in the tmp means a kill mid-write leaves ``path`` at
    **zero length**, which :func:`load_or_bootstrap` treats as absent and re-seeds.

    On a raised failure the tmp is unlinked, and ``path`` is unlinked ONLY while it is
    still this call's EMPTY claim — so a failed seed leaves the path absent and the next
    round bootstraps again.

    Not concurrency-safe for two bootstraps of ONE path: between step 1 and step 2 the
    name exists holding nothing, which :func:`load_or_bootstrap` reads as absent. See
    that function's "Serial callers only".

    Raises:
        OSError: the parent could not be created, or the write/replace failed.
            Genuine write failures (ENOSPC, EDQUOT, EROFS, EACCES, EIO...) propagate
            and escalate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        open(path, "x", encoding="utf-8").close()  # claim the name; write nothing
    except FileExistsError:
        # Already there (or a symlink): someone else's bytes win, untouched.
        return False
    tmp = path.parent / f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(tmp, "x", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)  # atomic content swap onto the name we already own
    except BaseException:
        # Best-effort: leave nothing partial behind. The tmp is always ours. ``path``
        # is unlinked ONLY while it is still this call's empty claim: ``os.replace``
        # is atomic, so if it raised the swap never happened and none of OUR bytes can
        # be at ``path`` — content there is someone else's, and deleting it would
        # destroy a live state file rather than clean up after us.
        try:
            tmp.unlink()
        except OSError:
            pass
        if _is_zero_length(path):
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return True


def write_state_atomic(path: Path, state: dict) -> None:
    """Overwrite ``path`` with ``state`` atomically (stage to tmp, fsync, replace).

    The per-round write-back counterpart of :func:`_create_exclusive`, and the re-seed
    path for a zero-length file. Here an overwrite IS intended, so there is no
    exclusive-create step and the never-overwrite invariant does not apply.

    ``os.replace`` is atomic within a directory on POSIX and on Windows, so a crash at
    any instant leaves ``path`` holding either the whole old document or the whole new
    one — never a prefix of either.

    **What ``os.replace`` does NOT preserve — a contract change from the truncating
    ``open(path, "w")`` this replaced.** The name is rebound to a freshly created inode,
    so the target's **mode, ownership, ACLs and xattrs are discarded** and any
    **hardlinks are broken** (the other links keep the OLD content). Measured: a state
    file at ``0444`` with one extra hardlink is overwritten and comes back ``0664`` with
    ``nlink=1``, where the truncating write raised ``PermissionError`` and the round
    exited 2. A read-only state file is therefore **no longer a write barrier**. That is
    the price of crash-atomicity and it is accepted: nothing in the loop sets a mode on
    the state, and a short file from a failed truncating write wedges every later round.

    **Symlinks: this function does not refuse them, and its sibling does.**
    :func:`_create_exclusive` REFUSES a symlinked ``path`` outright. Here ``os.replace``
    renames the tmp ONTO the name, which **destroys** the symlink and leaves a regular
    file where the link used to be — it never writes THROUGH the link to its target, but
    neither does it leave the link standing.

    Raises:
        OSError: the tmp write or the replace failed. The caller escalates
            ``state-write-failed`` exactly as it did for the plain write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    try:
        with open(tmp, "x", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass  # already replaced into place, or never created


def _is_zero_length(path: Path) -> bool:
    """True when the entry AT ``path`` is a **regular** file of 0 bytes.

    ``lstat``, not ``stat``: a symlink's own size is the length of its target string,
    never 0, so a symlink can never take the zero-length branch and the seed keeps
    refusing to write through one.

    ``S_ISREG`` confines the rule to the crash residue it was written for. Every
    non-regular node also answers ``st_size == 0``: without this check a FIFO and a
    bound ``AF_UNIX`` socket at ``state_path`` were each destroyed and replaced by a
    seeded regular file (rc 0, ``state_bootstrapped: true``, no diagnostic) — the
    never-overwrite invariant broken on a path that held no state to overwrite.

    A stat that fails (the file vanished under us) answers False and lets the read
    below produce the real error.
    """
    try:
        st = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size == 0


def _reject_non_regular(path: Path) -> None:
    """Refuse a ``state_path`` that does not resolve to a regular file.

    Refusing is not merely tidier than falling through to the read: a FIFO would BLOCK
    the read until some writer appears, hanging the round with no envelope and no exit
    code. A socket raises ``ENXIO`` and a directory ``IsADirectoryError``, which would
    at least escalate, but with an errno the operator has to decode. One honest refusal
    covers all three.

    A symlink is **resolved** rather than waved through, because the hang this guard
    exists to prevent reaches ``read_text()`` through a link just as well as directly: a
    symlink to a FIFO used to block the round indefinitely (measured — no envelope, no
    exit code), which is the one failure mode this wrapper promises never to have. So
    the check is on what ``path`` *resolves to*, and the refusal in invariant 4 holds
    unqualified. A symlink to a real state file still reads through; a **dangling** one
    is left to the read, which raises ``FileNotFoundError`` and lands on the same
    ``state-read-failed`` token (see :class:`StateReadError`).

    Resolution follows the **entire chain**, not one hop — ``Path.stat()`` is fully
    resolving, so ``link -> link -> FIFO`` is refused exactly like ``link -> FIFO``
    (measured: mode ``prw-rw-r--``, ``S_ISREG`` False, refused). Do **not** "fix" this
    to a single explicit ``readlink`` to match a one-level description: the chain case
    is the same indefinite ``read_text()`` hang, and a one-hop guard reopens it.
    ``test_iterate_state_zero_length.py`` pins the chain case under a subprocess timeout
    so that regression fails the suite instead of wedging it.

    Raises:
        StateReadError: ``path`` is — or resolves to — a FIFO, socket, device or
            directory.
    """
    try:
        st = path.lstat()
    except OSError:
        return  # vanished or unstattable: let the read below produce the real error
    if stat.S_ISLNK(st.st_mode):
        try:
            # Follows the WHOLE chain, not one hop: a link to a FIFO — however many
            # links deep — still blocks read_text(). Keep it fully resolving.
            st = path.stat()
        except OSError:
            return  # dangling / unresolvable: the read produces the real error
    if stat.S_ISREG(st.st_mode):
        return
    raise StateReadError(
        f"state_path is not a regular file (mode {stat.filemode(st.st_mode)}) — "
        f"refusing to read or replace it"
    )


def load_or_bootstrap(path: Path, *, now: str | None = None) -> "tuple[dict, bool]":
    """Read the state at ``path``, seeding a fresh one when the file is absent.

    Returns ``(state, bootstrapped)`` where ``bootstrapped`` is True only when this
    call created the file.

    The existence check happens **before** any open, which is the whole point: a bare
    ``open()`` conflates ``FileNotFoundError`` (a legitimate cold start) with a parse
    failure (a real problem a human must look at).

    **Never writes to a path that already exists and has CONTENT.** What it refuses, it
    preserves: a file whose bytes raise :class:`StateReadError` is left byte-identical,
    the round exits 2, and it never reaches the write-back. Note the limit of that
    promise — it is a property of the REFUSAL, not of the file. A state that PARSES as a
    JSON object but is schema-invalid is *accepted* here, and the write-back at the end
    of the round then overwrites it (measured). So the preserved-forensics guarantee
    covers exactly the inputs this function rejects.

    The single exception to never-overwrite is a **zero-length regular** file, which is
    treated as ABSENT and re-seeded: it has no bytes to preserve, refusing it would wedge
    the loop permanently, and it is the exact residue of a crash between
    :func:`_create_exclusive`'s two steps — so this rule is what makes that window
    self-healing. A non-regular node does NOT qualify (see :func:`_is_zero_length`).

    **Serial callers only — two concurrent bootstraps of ONE path are not supported,
    and the zero-length rule is where that shows.** The self-heal is against CRASH
    RESIDUE, not against a competitor: a claim still in flight is also 0 bytes, so a
    second call in that window re-seeds a LIVE claim, both calls report
    ``bootstrapped=True``, and whichever ``os.replace`` lands last wins. What is lost is
    the losing round's accumulated state: ``transitions``, ``last_codereview_head_sha``
    and ``last_codereview_findings`` (the currency fields
    ``loop_driver._independent_review_ran`` reads to decide whether a review covers the
    current head), and ``degraded_review_retries`` (the committed retry count the
    orchestrator bounds its re-runs on). ``iteration`` is **not** among the losses —
    nothing on this path increments it.

    Closing the window needs mutual exclusion the stdlib does not expose portably;
    ``run_round.py`` is shelled one round at a time by ``converge.py`` and by the Tier-7
    loop, both serial, so it is documented rather than fixed. A caller that parallelises
    MUST give each loop its own ``state_path``. The reset is at least *reported*: the
    round that re-seeds emits ``state_bootstrapped: true``.

    Raises:
        StateReadError: ``path`` holds content that is not a JSON object, is a dangling
            symlink, or is a non-regular node.
        StateWriteError: existence could not be probed, or the seed / zero-length
            re-seed could not be written. Fails closed — the caller escalates rather
            than proceeding on a state it never persisted.

    Only the two *expected* filesystem outcomes are named here. Anything else is left to
    the catch-all at ``run_round.py``'s CLI boundary, which turns any exception into an
    escalate envelope — enumerating exception types one at a time is what left exit-1
    holes.
    """
    # The probe is fallible: guard it so an undecidable answer escalates instead of
    # escaping as a traceback (exit 1 / no envelope), which run_round.py's contract
    # forbids — it uses only 0 and 2.
    try:
        exists = path.exists()
    except OSError as exc:
        raise StateWriteError(
            f"could not determine whether the state file exists: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    if not exists:
        state = fresh_state(now=now)
        try:
            created = _create_exclusive(path, json.dumps(state, indent=2))
        except OSError as exc:
            raise StateWriteError(
                f"could not seed a round-0 state: {type(exc).__name__}: {exc}"
            ) from exc
        if created:
            return state, True
        # It appeared underneath us (concurrent round, or a symlink `exists()`
        # reported absent). Fall through and read whatever is actually there.

    # A FIFO / socket / directory is refused before either the zero-length branch (which
    # would REPLACE it) or the read (which would BLOCK on a FIFO).
    _reject_non_regular(path)

    # Present but EMPTY → treated as absent. Zero bytes are no forensic record, and this
    # is the residue a crash between _create_exclusive's claim and its replace leaves
    # behind. Re-seed rather than wedge forever.
    if _is_zero_length(path):
        state = fresh_state(now=now)
        try:
            write_state_atomic(path, state)
        except OSError as exc:
            raise StateWriteError(
                f"could not re-seed a zero-length state file: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return state, True

    # Present, with content. Read-only from here on — no branch below writes.
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # OSError, UnicodeDecodeError, JSONDecodeError
        raise StateReadError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(state, dict):
        raise StateReadError(
            f"state file must contain a JSON object, got {type(state).__name__}"
        )
    return state, False
