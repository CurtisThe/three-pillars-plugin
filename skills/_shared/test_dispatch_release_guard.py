"""test_dispatch_release_guard.py — doc guard: every local exit path releases with the agent id.

design: slot-release-on-attempt-end (Task 1.6; design.md Behavior 4 "Doc backstop").
`local_lease.py release --agent-id <id>` is the doc-level backstop for the release the watchdog
makes in code at `poll`'s terminal transitions, so every release step in `local-dispatch.md` §3
and `cheap-dispatch.md` §Local rung carries the id — except the spawn-failed path (no agent
exists) and the unconfirmed-orphan path (never release an agent that may still be running:
Behavior 2). Pinned by token per site, scoped by heading and step marker, never by line number
(`skills/_shared/test-fragility.md`).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
RELEASE = "local_lease.py release"
AGENT_ID = "--agent-id <agent id>"
SPAWN_FAILED = "background-spawn-failed"

LOCAL_DOC = (HERE / "local-dispatch.md").read_text(encoding="utf-8")
CHEAP_DOC = (HERE / "cheap-dispatch.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace collapsed, backticks dropped: a token check ignores markdown code spans."""
    return " ".join(text.replace("`", "").split())


def _local_rung() -> str:
    """`local-dispatch.md` §3 only — §2 step 2's one-line summary stays out of scope."""
    start = LOCAL_DOC.index("\n## 3.")
    return LOCAL_DOC[start:LOCAL_DOC.index("\n## 4.", start)]


def _cheap_local_rung() -> str:
    """`cheap-dispatch.md`'s `## Local rung` section, split by `## ` headings."""
    m = re.search(r"^## Local rung\n(.*?)(?=^## |\Z)", CHEAP_DOC, re.S | re.M)
    assert m, "no ## Local rung section"
    return m.group(1)


SLICES = {"local-dispatch.md §3": _local_rung(), "cheap-dispatch.md §Local rung": _cheap_local_rung()}


def _step(sl: str, n: int) -> str:
    """Step `n` of the slice's numbered local-rung steps, up to step `n + 1` — by list marker,
    the slicer `test_local_reaper_pointers.py` uses, never a line number."""
    start = sl.index(f"\n{n}. ")
    end = sl.find(f"\n{n + 1}. ", start + 1)
    return sl[start:end if end != -1 else len(sl)]


def _release_lines(sl: str) -> list[str]:
    lines = [ln for ln in sl.splitlines() if RELEASE in ln]
    assert lines, "no release step in this slice"
    return lines


def _has_id_release(step: str) -> bool:
    return any(AGENT_ID in ln for ln in step.splitlines() if RELEASE in ln)


ID_SUFFIX = f" {AGENT_ID}"  # the id attached to the command, not merely present on the line


def _release_occurrences(flat: str) -> list:
    return list(re.finditer(re.escape(RELEASE), flat))


@pytest.mark.parametrize("name", sorted(SLICES))
def test_every_release_line_carries_the_id_or_names_the_spawn_failure(name):
    """Behavior 4: the id-less release survives only where no agent was spawned.

    audit c6 (impl-audit retry 2): the id must be attached to the release command, not
    merely somewhere on the line — a bare `local_lease.py release` with `--agent-id <agent
    id>` moved into the aside on the same line passes a per-line token check while the
    documented command loses the id. So every release occurrence on a non-spawn-failed line
    is followed immediately by ` --agent-id <agent id>`."""
    for line in _release_lines(SLICES[name]):
        if SPAWN_FAILED in line:
            continue
        flat = _flat(line)
        occ = _release_occurrences(flat)
        assert occ, (name, flat)
        for m in occ:
            assert flat[m.end():m.end() + len(ID_SUFFIX)] == ID_SUFFIX, (name, flat)


@pytest.mark.parametrize("name", sorted(SLICES))
def test_spawn_failed_release_stays_id_less(name):
    step = _step(SLICES[name], 2 if name.startswith("local") else 1)
    assert SPAWN_FAILED in step and RELEASE in step
    assert not any(AGENT_ID in ln for ln in step.splitlines() if RELEASE in ln), step


@pytest.mark.parametrize("name", sorted(SLICES))
def test_done_release_carries_the_id(name):
    step = _step(SLICES[name], 4)
    assert "On `done`" in step and RELEASE in step
    assert _has_id_release(step), (name, step)


@pytest.mark.parametrize("name", sorted(SLICES))
def test_runaway_release_follows_the_stop_and_carries_the_id(name):
    step = _step(SLICES[name], 5)
    assert "TaskStop" in step and RELEASE in step
    assert step.index("TaskStop") < step.index(RELEASE), (name, step)
    assert _has_id_release(step), (name, step)


@pytest.mark.parametrize("name", sorted(SLICES))
def test_runaway_release_is_conditioned_on_a_successful_stop(name):
    """Audit advice (Task 1.8): the id-carrying release is worded as following a *successful*
    stop, as `cheap-dispatch.md` step 5 already words it — a stop that was missing or refused
    takes the id-less orphan-mark branch instead, so the ordering is a rule, not a sequence."""
    flat = _flat(_step(SLICES[name], 5))
    cond = "After a successful TaskStop"
    assert cond in flat, (name, flat)
    assert flat.index(cond) < flat.index(f"{RELEASE} {AGENT_ID}"), (name, flat)


def test_watchdog_error_release_follows_the_stop_and_carries_the_id():
    step = _step(_cheap_local_rung(), 6)
    assert "watchdog error" in step and "TaskStop" in step and "orphan-mark" in step
    assert step.index("TaskStop") < step.index(RELEASE)
    assert _has_id_release(step), step


@pytest.mark.parametrize("name", sorted(SLICES))
def test_unconfirmed_orphan_release_stays_id_less(name):
    """A `TaskStop` that was missing or refused marks the orphan; its release must not name the
    agent (it may still be running — the backstop and the reaper handle it)."""
    flat = _flat(_step(SLICES[name], 5))
    assert "orphan-mark" in flat and "id-less" in flat, name


@pytest.mark.parametrize("name", sorted(SLICES))
def test_doc_states_the_code_release_makes_the_doc_step_a_backstop(name):
    """`poll`'s `done` releases in code (`attempt_release.release_once`); the doc step is the
    second line of defence, and the docs say so where the release step lives."""
    flat = _flat(_step(SLICES[name], 4))
    for token in ("poll", "done", "released", "code", "backstop"):
        assert token in flat, (name, token)


def test_watchdog_state_writers_include_polls_released_stamp():
    """The W sentence lists every writer; `poll`'s one-time `released` record is one (Behavior 1)."""
    line = [ln for ln in _local_rung().splitlines() if "write it" in ln and "orphan-mark" in ln]
    assert len(line) == 1, line
    flat = _flat(line[0])
    for token in ("arm", "orphan-mark", "stopped", "released"):
        assert token in flat, token
