#!/usr/bin/env python3
"""run_retro_file.py — the leak backstop, the sealed outbox and the seed fallback.

design: design-learn-retro. ``file_drafts`` applies the reviewer's verdicts to the RRSI drafts
and files what survives. Verdicts: a list of ``{slug, verdict, reason}`` (``slug`` is the draft's
``proposed_slug``; ``verdict`` is ``accept``, ``reject`` or ``merge-with``; ``merge-with`` adds
``target``, the slug of the known item that gains an evidence line). A draft with no verdict is
treated as rejected: nothing is filed without an explicit accept. A ``merge-with`` target must
fullmatch ``SAFE_SLUG`` or the draft is refused before any path is built.

* ``board`` set: entries that passed every check go into ``<design_dir>/retro-outbox.json``,
  ``{board, entries: [{slug, retro_key, board, payload}]}``; each payload has exactly
  ``BOARD_FIELDS`` (the flags of notion-ops' ``/notion-file-upgrade-request``, one call per entry;
  ``retro_key`` stays on the entry, ours). This module has no composer or sink; ``parse_reply``
  reads that skill's reply line. The ``feedback`` board is refused (``ValueError``) before
  anything is written. An entry is
  built, then ``leaks()`` runs over all of it (the reviewer's reason is in the payload): a hit
  refuses the entry. An outbox entry is not a ``filed_marks`` mark: only ``record`` marks it.
* ``board`` None: fallback ``seed.md`` drafts under ``seed_root(design_dir)/<proposed_slug>/``
  (``tp-designs/``, also for an archived design under ``completed-tp-designs/``).
  Evidence lines (filter ``evidence_adds``, ``merge-with``, an existing slug) are appended to an
  existing seed.md only on this path; on the board path they are only returned.

Returns ``{outbox, seeds, evidence_adds, refused, rejected, skipped, modified_seeds,
filed_marks, fallback_reason}``. Stdlib only; imports nothing from notion-ops.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import seed_write  # noqa: E402

BOARD_FIELDS = ("package", "type", "source_run", "design", "root_cause_group", "evidence",
                "reviewer_verdict", "version", "recurrence", "rrsi_flags")
PACKAGE = "three-pillars"
MANIFEST = Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
ACTIONS = ("create", "bump", "repair", "noop")
OUTBOX_NAME = "retro-outbox.json"
EVIDENCE_HEADING = "## Evidence"
SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # a slug is a directory name: no path chars
LEAK_PATTERNS = (
    re.compile(r"[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S+"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xox[bap]-[A-Za-z0-9-]{8,}"),
)
_NEVER = ("feedback",)
ARCHIVE_DIR, ACTIVE_DIR = "completed-tp-designs", "tp-designs"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def leaks(draft) -> list:
    """Pattern sources that match any string field of ``draft`` (empty when clean)."""
    return [p.pattern for p in LEAK_PATTERNS for s in _strings(draft) if p.search(s)]


def plugin_version(manifest=MANIFEST) -> str:
    """The shipped plugin's version string; ``unknown`` when the manifest is absent or odd."""
    try:
        version = json.loads(Path(manifest).read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return version if isinstance(version, str) and version else "unknown"


def to_payload(draft: dict, verdict: dict, design: str, package: str = PACKAGE) -> dict:
    flags = [name.replace("_", "-") for name in ("operator_touch", "rerun") if draft.get(name)]
    return {
        "package": package,
        "type": "Bug" if draft.get("type") == "Bug" else "Idea",
        "source_run": design,
        "design": design,
        "root_cause_group": ", ".join(draft.get("shapes", [])),
        "evidence": list(draft.get("evidence", [])),
        "reviewer_verdict": f"{verdict['verdict']}: {verdict.get('reason', '')}",
        "version": plugin_version(),
        "recurrence": draft.get("count", 0),
        "rrsi_flags": flags,
    }


def parse_reply(text: str):
    """One ``/notion-file-upgrade-request`` reply: ``("filed", row url)`` for ``filed: <action>
    <url>``, ``("not filed", reason)`` for ``not filed: <reason>``, else None (an error line)."""
    lines = [ln.strip() for ln in str(text).splitlines() if ln.strip()]
    line = lines[-1] if lines else ""
    if line.startswith("not filed:"):
        return ("not filed", line[len("not filed:"):].strip() or "no reason given")
    parts = line.split()
    if len(parts) == 3 and parts[0] == "filed:" and parts[1] in ACTIONS:
        return ("filed", parts[2])
    return None


def seed_root(design_dir) -> Path:
    """The ``tp-designs`` dir seeds live in: the design's parent, or for an archived design
    (``completed-tp-designs/<name>``) the sibling ``tp-designs`` that ``known-items`` reads."""
    parent = Path(design_dir).parent
    return parent.parent / ACTIVE_DIR if parent.name == ARCHIVE_DIR else parent


def write_seed(draft: dict, design_dir, weight_class: str = "light") -> Path:
    """Write the fallback seed.md for ``draft``; refuse an existing path. Shapes only, no values.
    The frontmatter comes from ``seed_write.frontmatter`` and carries ``weight-class`` (light)."""
    path = seed_root(design_dir) / draft["proposed_slug"] / "seed.md"
    if path.exists():
        raise FileExistsError(str(path))
    refs = "\n".join(f"- {ref}" for ref in draft.get("evidence", []))
    shapes = ", ".join(draft.get("shapes", []))
    head = seed_write.frontmatter(weight_class=weight_class, extra={
        "origin": "run-retro", "upstream": "three-pillars", "retro_key": draft["retro_key"],
        "type": draft.get("type", "Idea"), "skill": draft.get("skill", ""),
        "recurrence": draft.get("count", 0)})
    body = (
        f"{head}# {draft['proposed_slug']} — seed (run-retro)\n\n"
        f"Friction shapes: {shapes}\n\n{EVIDENCE_HEADING}\n\n{refs}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _append_evidence(path: Path, line: str) -> bool:
    """Append ``line`` under ``## Evidence``; False when already present."""
    text = path.read_text(encoding="utf-8")
    if line in text.splitlines():
        return False
    lines = text.splitlines()
    if EVIDENCE_HEADING not in lines:
        lines += ["", EVIDENCE_HEADING, "", line]
    else:
        idx = lines.index(EVIDENCE_HEADING) + 1
        end = next((i for i in range(idx, len(lines)) if lines[i].startswith("#")), len(lines))
        while end > idx and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def _evidence_line(add: dict) -> str:
    return f"- evidence (run-retro): {add['retro_key']} {' '.join(add.get('evidence', []))}".rstrip()


def _safe_target(verdict: dict) -> bool:
    """A ``merge-with`` target becomes a directory name under tp-designs: it must be a slug."""
    target = verdict.get("target")
    return isinstance(target, str) and bool(SAFE_SLUG.fullmatch(target))


def _apply_evidence(add: dict, design_dir: Path, seeds_ok: bool, done: set, res: dict) -> None:
    mark = f"evidence:{add['seed']}@{add['retro_key']}"
    if mark in done:
        return
    res["evidence_adds"].append(add)
    seed = seed_root(design_dir) / add["seed"] / "seed.md"
    if seeds_ok and seed.is_file() and _append_evidence(seed, _evidence_line(add)):
        res["modified_seeds"].append(str(seed))
        res["filed_marks"].append(mark)


def file_drafts(drafts, verdicts, *, board, design_dir, already_filed=(),
                fallback_reason=None, evidence_adds=()) -> dict:
    """Apply ``verdicts`` to ``drafts`` and file the survivors (see the module docstring)."""
    if board in _NEVER:
        raise ValueError(f"board {board!r} is never a run-retro target")
    design_dir = Path(design_dir)
    seeds_dir = seed_root(design_dir)
    done = set(already_filed)
    by_slug = {v["slug"]: v for v in verdicts or []}
    res = {"outbox": [], "seeds": [], "evidence_adds": [], "refused": [], "rejected": [],
           "skipped": [], "modified_seeds": [], "filed_marks": [], "fallback_reason": fallback_reason}
    seeds_ok = board is None
    for draft in drafts or []:
        slug, key = draft["proposed_slug"], draft["retro_key"]
        verdict = by_slug.get(slug)
        if not SAFE_SLUG.fullmatch(slug):
            res["refused"].append({"slug": slug, "retro_key": key, "patterns": ["unsafe-slug"]})
        elif key in done or slug in done:
            res["skipped"].append(key)
        elif verdict is None or verdict["verdict"] not in ("accept", "merge-with"):
            reason = verdict.get("reason", "") if verdict else "no-verdict"
            res["rejected"].append({"slug": slug, "retro_key": key, "reason": reason})
        elif hits := leaks(draft):
            res["refused"].append({"slug": slug, "retro_key": key, "patterns": hits})
        elif verdict["verdict"] == "merge-with" and not _safe_target(verdict):
            res["refused"].append({"slug": slug, "retro_key": key, "patterns": ["unsafe-target"]})
        elif verdict["verdict"] == "merge-with" or (seeds_dir / slug / "seed.md").exists():
            target = verdict.get("target") if verdict["verdict"] == "merge-with" else slug
            add = {"seed": target, "kind": draft.get("type"), "retro_key": key,
                   "evidence": list(draft.get("evidence", [])), "count": draft.get("count", 0)}
            _apply_evidence(add, design_dir, seeds_ok, done, res)
        elif seeds_ok:
            path = write_seed(draft, design_dir)
            res["seeds"].append(str(path))
            res["modified_seeds"].append(str(path))
            res["filed_marks"] += [key, slug]
        else:
            entry = {"slug": slug, "retro_key": key, "board": board,
                     "payload": to_payload(draft, verdict, design_dir.name)}
            if hits := leaks(entry):  # the reason is in the payload: refuse, never strip
                res["refused"].append({"slug": slug, "retro_key": key, "patterns": hits})
            else:
                res["outbox"].append(entry)  # marked filed only by ``record``, never here
    for add in evidence_adds or []:
        _apply_evidence(add, design_dir, seeds_ok, done, res)
    if board is not None:
        out = {"board": board, "entries": res["outbox"]}
        (design_dir / OUTBOX_NAME).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return res
