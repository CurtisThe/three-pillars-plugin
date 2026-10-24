"""Ruling files: one committed markdown file per finalizer ruling.

design: fable-escalation 4.1 — id, O_EXCL write with clash re-hash,
render/parse round trip. (4.2 adds find/append_feedback/set_explain.)
Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

RULINGS_REL = "three-pillars-docs/escalations/rulings"
ID_RE = r"^[a-z0-9-]+-\d{8}-[0-9a-f]{6}$"

_FRONT_KEYS = ("id", "slug", "entry", "source", "kind", "outcome", "model",
               "at", "stop_key", "explain")
_CLASH_SUFFIXES = ("", "#1", "#2", "#3")  # appended to the hash INPUT only
_SECTION = re.compile(r"^## (Question|Ruling|Feedback)[ \t]*$", re.M)


def ruling_id(scope, question, at) -> str:
    """``<scope>-<YYYYMMDD>-<sha256(question+'\\n'+at)[:6]>``."""
    return _id_with_suffix(scope, question, at, "")


def _id_with_suffix(scope, question, at, suffix) -> str:
    date = at[:10].replace("-", "")
    digest = hashlib.sha256(
        (question + "\n" + at + suffix).encode("utf-8")).hexdigest()[:6]
    return f"{scope}-{date}-{digest}"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _question_of(stop, key) -> str:
    """``detail.question`` for a question stop, else the stop key itself."""
    if stop.get("source") == "question":
        detail = stop.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("question"), str):
            return detail["question"]
    return key


def _render(rid, scope, entry, stop, key, result, model, at, question) -> str:
    front = {
        "id": rid,
        "slug": scope,
        "entry": entry,
        "source": str(stop.get("source", "")),
        "kind": str(stop.get("signal")) if stop.get("source") == "question" else "-",
        "outcome": str(result.get("outcome", "")),
        "model": str(model),
        "at": at,
        "stop_key": str(key),
        "explain": "-",
    }
    lines = ["---"]
    lines += [f"{k}: {front[k]}" for k in _FRONT_KEYS]
    lines += ["---", "", "## Question", "", question, "",
              "## Ruling", "", "```json",
              json.dumps(result, indent=2, ensure_ascii=False), "```",
              "", "## Feedback", ""]
    return "\n".join(lines)


def write(root, *, scope, entry, stop, key, result, model, at=None) -> Path:
    """Write one ruling file under RULINGS_REL; return its path.

    O_EXCL create: an id clash re-hashes with ``#1``..``#3`` appended to the
    hash INPUT (the id itself never carries a suffix); after ``#3`` raise
    ``FileExistsError``. Scope ``seat`` with ``entry=run`` is refused.
    A ``scope`` outside ``[a-z0-9-]+`` (design: fable-escalation 8.3) raises
    ``ValueError`` before the rulings dir is created, so a scope can never
    escape ``RULINGS_REL``; the CLI's ``_finish`` turns that into one
    fail-open line.
    """
    if not re.fullmatch(r"[a-z0-9-]+", scope):
        raise ValueError(f"bad scope: {scope!r}")
    if scope == "seat" and entry == "run":
        raise ValueError("ruling scope 'seat' with entry 'run' is refused")
    at = at or _now()
    question = _question_of(stop, key)
    base = Path(root) / RULINGS_REL
    base.mkdir(parents=True, exist_ok=True)
    for suffix in _CLASH_SUFFIXES:
        rid = _id_with_suffix(scope, question, at, suffix)
        path = base / (rid + ".md")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_render(rid, scope, entry, stop, key, result, model,
                             at, question))
        return path
    raise FileExistsError(f"ruling id candidates exhausted for {scope} at {at}")


def _split_sections(body: str) -> dict[str, str]:
    """{heading: raw body} for every `## Question|Ruling|Feedback` section."""
    sections = {}
    hits = list(_SECTION.finditer(body))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        sections[m.group(1)] = body[m.end():end].strip()
    return sections


def parse(path) -> dict:
    """{"front": {...}, "question": str, "ruling": dict, "feedback": [str]}."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    front: dict[str, str] = {}
    body = text
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for line in lines[1:i]:
                    if ": " in line:
                        k, v = line.split(": ", 1)
                        front[k.strip()] = v.strip()
                body = "\n".join(lines[i + 1:])
                break
    sections = _split_sections(body)
    ruling_text = sections.get("Ruling", "")
    m = re.search(r"```json\n(.*?)\n```", ruling_text, re.S)
    ruling = json.loads(m.group(1)) if m else {}
    feedback = [ln.strip() for ln in sections.get("Feedback", "").splitlines()
                if ln.strip()]
    return {"front": front,
            "question": sections.get("Question", ""),
            "ruling": ruling,
            "feedback": feedback}


_ANSWER = re.compile(r"^- \d{4}-\d{2}-\d{2}: answer: (.*)$")


def answer_of(parsed):
    """The label of the last ``answer:`` feedback line (what ``ruling_cli answer``
    writes), cut at the first `` — `` and `` (Recommended)`` stripped; else None.

    design: seat-escalate-first 1.3 — the one reading of "answered" shared by
    the hook, ``review_stop.settle`` and the seat commit guard.
    """
    for line in reversed(parsed.get("feedback") or []):
        m = _ANSWER.match(line)
        if m:
            return m.group(1).split(" — ", 1)[0].removesuffix(" (Recommended)")
    return None


def find(root, rid):
    """``RULINGS_REL/<rid>.md`` under ``root`` when it exists, else None.

    A ``rid`` outside ``ID_RE`` (e.g. ``../x``) returns None without
    touching the filesystem.
    """
    if not re.fullmatch(ID_RE, str(rid)):
        return None
    path = Path(root) / RULINGS_REL / (rid + ".md")
    return path if path.is_file() else None


def append_feedback(path, line) -> None:
    """Append ``- <YYYY-MM-DD>: <line>`` (UTC) under the final ``## Feedback``."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    if not any(m.group(1) == "Feedback" for m in _SECTION.finditer(text)):
        text += "\n## Feedback\n\n"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path.write_text(text + f"- {day}: {line}\n", encoding="utf-8")


def set_explain(path, ref) -> None:
    """Rewrite only the front-matter ``explain:`` line."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for j in range(1, i):
                    if lines[j].startswith("explain:"):
                        lines[j] = f"explain: {ref}\n"
                        break
                break
    path.write_text("".join(lines), encoding="utf-8")
