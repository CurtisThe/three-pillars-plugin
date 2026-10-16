"""plan_files.py — the plan **File** field: the one grammar for a task's declared paths.

design: consumer-repo-parity (H4, Phase 3)

A plan task declares which repo paths it touches in one strict field::

    **File**: `skills/_shared/task_targets.py` (modify), `Makefile` (new), `README.md`

* ``field := "none" | item ("," item)*`` (whitespace around a comma is free);
* ``item := "`" path "`" [" (" (new|modify) "]`` — the marker is optional and per item;
* ``path``: a repo-relative POSIX path of any extension (dotfiles and ``Makefile``
  included); segments of ``[A-Za-z0-9_.-]``, never ``.`` or ``..``, no leading ``/``,
  and **no** ``::`` (a File path is a path, not a test node);
* a marker of ``(new)`` means the task creates the path, ``(modify)`` that it edits one
  that exists, and **no marker** means it merely touches the path (still canonical);
* ``none``: the task declares no file (canonical and empty).

Anything else is **non-canonical** and carries at least one error. A non-canonical field
is never a failure: the caller (audit) then falls back to a lenient parse for coverage and
emits one NOTE. The grammar deliberately mirrors ``task_targets._split``/``_item_errors``
so the two fields share one shape, with the two relaxations above. Stdlib only.

``check_file_existence`` (task 3.2) judges existence against the disk **plus** the
paths earlier tasks create; a non-canonical **File** field falls back to the lenient
``task_scope_files.parse_files`` (one NOTE, its paths treated as unmarked "touches"),
so a legacy plan gets NOTEs, never WARNs, and a canonical all-``(new)`` greenfield
plan gets neither.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "_shared"))
from task_scope_files import parse_files  # noqa: E402
from task_targets import parse_targets  # noqa: E402

# ```` content ```` then an optional marker — whitespace **before** the marker is
# required (mirrors task_targets, whose marker is `[ \t]+\((new)\)`). The marker is
# either ``(new)`` or ``(modify)``.
_ITEM_RE = re.compile(r"`([^`]*)`(?:[ \t]+\((new|modify)\))?")
_SEP_RE = re.compile(r"\s*,\s*")
_SEGMENT_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
_COLON = "::"


def _item_errors(content: str) -> list[str]:
    """Why one backticked item is not a repo-relative path (empty → well-formed).

    Any extension is allowed, but the path must not use a node separator (``::``) and
    must not escape the repo (a leading ``/``, or a ``.``/``..`` segment).
    """
    if _COLON in content:
        return [f"bad path {content!r} (a File path has no `::` node separator)"]
    segments = content.split("/")
    if content.startswith("/") or not all(
            _SEGMENT_RE.match(s) and s not in (".", "..") for s in segments):
        return [f"bad path {content!r} (a repo-relative path)"]
    return []


def _split(text: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """``text`` → ``([(path, marker)], errors)``, consuming the whole field.

    ``marker`` is ``"new"``, ``"modify"`` or ``None`` (no marker / touches). The whole
    field must be consumed: an unbalanced backtick, free prose, a trailing comma or an
    unknown marker each leaves a remainder that is reported as an error.
    """
    items: list[tuple[str, str | None]] = []
    pos = 0
    while True:
        m = _ITEM_RE.match(text, pos)
        if not m:
            return items, [f"expected a backticked path at {text[pos:pos + 24]!r}"]
        items.append((m.group(1), m.group(2)))
        pos = m.end()
        if pos == len(text):
            return items, []
        sep = _SEP_RE.match(text, pos)
        if not sep or sep.end() == len(text):
            return items, [f"expected ', ' then a path at {text[pos:pos + 24]!r}"]
        pos = sep.end()


def parse_file_field(field: str | None) -> dict:
    """A task's **File** field → ``{canonical, items, errors}``.

    ``items`` is a list of ``{"path": <repo-relative path>, "marker": <"new" | "modify"
    | None>}`` in field order; ``marker`` is ``None`` when the item declared no marker
    (it "touches" the path). ``canonical`` is ``True`` only when the field is ``none`` or
    a well-formed item list; otherwise it is ``False`` and ``errors`` names the problem(s).
    A missing field (``None``) is non-canonical with a single error.
    """
    if field is None:
        return {"canonical": False, "items": [],
                "errors": ["file-field-missing"]}
    text = field.strip()
    if text == "none":
        return {"canonical": True, "items": [], "errors": []}
    items, errors = _split(text)
    for path, _marker in items:
        errors += _item_errors(path)
    return {
        "canonical": not errors,
        "items": [{"path": path, "marker": marker} for path, marker in items],
        "errors": errors,
    }


def check_file_existence(tasks: list[dict], root: str = ".") -> tuple[list, list]:
    """Existence of each task's declared paths, earlier-task aware → ``(issues, notes)``.

    Walks ``tasks`` (``extract_tasks`` dicts) in plan order keeping
    ``created = set()``: a ``modify`` of a path neither on disk (relative to
    ``root``) nor in ``created`` → WARN; a ``new`` of an already-existing path →
    NOTE (a re-run is legitimate); a ``new`` adds its path to ``created``, as do the
    task's ``(new)`` **Targets** files; an unmarked ("touches") path that does not
    exist → NOTE, and it never enters ``created``; a non-canonical **File** field
    falls back to the lenient ``task_scope_files.parse_files`` with one NOTE and its
    paths treated as unmarked. There is no parent-directory check.
    """
    root = Path(root)
    issues: list[tuple[str, str, str]] = []
    notes: list[tuple[str, str, str]] = []
    created: set[str] = set()
    for task in tasks:
        tid = task["id"]
        ctx = f"Task {tid}"
        fields = task.get("fields") or {}
        for path in parse_targets(fields.get("Targets"))["new_files"]:
            created.add(path)
        field = fields.get("File")
        if field is None:
            continue
        parsed = parse_file_field(field)
        if not parsed["canonical"]:
            paths, _unparsed = parse_files(field)
            notes.append(("NOTE", ctx, (
                f"task {tid}: File field is not declared-form (`path` (new|modify), …)"
                f"; coverage used a lenient parse")))
        else:
            paths = [i["path"] for i in parsed["items"]]
        for path in paths:
            if parsed["canonical"]:
                marker = next(i["marker"] for i in parsed["items"] if i["path"] == path)
            else:
                marker = None
            if marker == "modify" and not (root / path).is_file() and path not in created:
                issues.append(("WARN", ctx, (
                    f"task {tid}: modifies {path}, which does not exist and "
                    f"no earlier task creates it")))
            elif marker == "new":
                if (root / path).is_file():
                    notes.append(("NOTE", ctx,
                                  f"task {tid}: creates {path}, which already exists"))
                created.add(path)
            elif marker is None and not (root / path).is_file() and path not in created:
                notes.append(("NOTE", ctx, (
                    f"task {tid}: touches {path}, which does not exist yet; "
                    f"mark it (new) or (modify)")))
    return issues, notes
