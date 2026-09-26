"""task_targets.py — the plan **Targets** field: the one grammar for a task's pytest oracle.

design: local-implement-and-review (operator rulings on #165, ruling 1 "C3")

A plan task declares what its oracle runs in one strict field; the **Test** field is prose
for humans and is never parsed::

    **Targets**: `pkg/test_a.py::test_one`, `pkg/test_a.py::TestB::test_two`, `pkg/test_c.py` (new)

* ``field := "none" | item ("," item)*`` (whitespace around a comma is free);
* ``item := "`" path ("::" name)* "`" [" (new)"]``;
* ``path``: repo-relative POSIX path to a ``.py`` file; segments of ``[A-Za-z0-9_.-]``,
  never ``.`` or ``..``, no leading ``/``;
* ``name``: a Python identifier (``[A-Za-z_]\\w*``); no parametrize ids, no globs;
* ``(new)``: the task creates that file. Every item of one file carries it, or none does;
* ``none``: the task has no runnable target (canonical, but not runnable).

A missing field is **non-canonical** (``targets-missing``); a malformed one is
``targets-malformed``. Both are not runnable: eligibility routes the task to opus, the
Tier 3.5 re-run reports it unverified, and neither is ever case f or a hard FAIL.

Order never matters: specs are sorted and a bare file item runs the whole file (its node
items are subsumed). Duplicate items are an error. Stdlib only; used by ``task_scope``
(re-exported), eligibility, ``task_verify``, the re-run, and ``audit_plan``.
"""
from __future__ import annotations

import re

MISSING = "targets-missing"
MALFORMED = "targets-malformed"
NONE = "targets-none"
NON_CANONICAL = frozenset({MISSING, MALFORMED})

_ITEM_RE = re.compile(r"`([^`]*)`(?:[ \t]+\((new)\))?")
_SEP_RE = re.compile(r"\s*,\s*")
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
_IDENT_RE = re.compile(r"[A-Za-z_]\w*\Z")


def _item_errors(content: str) -> list[str]:
    """Why one backticked item is not ``path(::name)*`` (empty → well-formed)."""
    path, *names = content.split("::")
    segments = path.split("/")
    if not path.endswith(".py") or not all(
            _SEGMENT_RE.match(s) and s not in (".", "..") for s in segments):
        return [f"bad path {path!r} (a repo-relative .py path)"]
    return [f"bad node {n!r} in {content!r} (a Python identifier)"
            for n in names if not _IDENT_RE.match(n)]


def _split(text: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """``text`` → ``([(content, new)], errors)``, consuming the whole field."""
    items: list[tuple[str, bool]] = []
    pos = 0
    while True:
        m = _ITEM_RE.match(text, pos)
        if not m:
            return items, [f"expected a backticked target at {text[pos:pos + 24]!r}"]
        items.append((m.group(1), bool(m.group(2))))
        pos = m.end()
        if pos == len(text):
            return items, []
        sep = _SEP_RE.match(text, pos)
        if not sep or sep.end() == len(text):
            return items, [f"expected ', ' then a target at {text[pos:pos + 24]!r}"]
        pos = sep.end()


def validate(field: str | None) -> list[str]:
    """Every grammar error of a present **Targets** field ([] = valid; None = missing)."""
    if field is None:
        return []
    text = field.strip()
    if text == "none":
        return []
    items, errors = _split(text)
    for content, _new in items:
        errors += _item_errors(content)
    seen: set[str] = set()
    marker: dict[str, bool] = {}
    for content, new in items:
        if content in seen:
            errors.append(f"duplicate target {content!r}")
        seen.add(content)
        path = content.split("::", 1)[0]
        if marker.setdefault(path, new) != new:
            errors.append(f"(new) marks some but not all targets of {path!r}")
    return errors


def _result(kind: str, reason: str, errors=(), specs=(), files=(), new=()) -> dict:
    return {"kind": kind, "canonical": reason not in NON_CANONICAL, "reason": reason,
            "errors": list(errors), "specs": list(specs), "files": list(files),
            "new_files": list(new)}


def parse_targets(field: str | None) -> dict:
    """A task's **Targets** field → ``{kind, canonical, reason, errors, specs, files,
    new_files}``.

    ``kind`` is ``pytest-node`` (every spec names a node), ``pytest-file`` (at least one
    whole file) or ``not-runnable`` (reason ``targets-missing`` / ``targets-malformed`` /
    ``targets-none``). ``specs`` are the sorted runner arguments, ``files`` the sorted
    distinct paths, ``new_files`` those marked ``(new)``.
    """
    if field is None:
        return _result("not-runnable", MISSING)
    errors = validate(field)
    if errors:
        return _result("not-runnable", MALFORMED, errors)
    if field.strip() == "none":
        return _result("not-runnable", NONE)
    items, _ = _split(field.strip())
    nodes: dict[str, set[str] | None] = {}
    new = set()
    for content, is_new in items:
        path, _, node = content.partition("::")
        if is_new:
            new.add(path)
        if not node:
            nodes[path] = None  # a bare file runs whole: its node items are subsumed
        elif nodes.get(path, set()) is not None:
            nodes.setdefault(path, set()).add(node)
    specs = sorted(p if n is None else f"{p}::{x}" for p, n in nodes.items()
                   for x in ([None] if n is None else n))
    kind = "pytest-node" if all("::" in s for s in specs) else "pytest-file"
    return _result(kind, "", specs=specs, files=sorted(nodes), new=sorted(new))
