#!/usr/bin/env python3
"""run_retro_collect.py — read a design run's own artifacts into friction signals.

design: design-learn-retro. ``collect`` reads, fail-open (a missing or unreadable artifact
gives no rows, never a raise): ``decisions.md`` headings, ``finalizer-ledger.json``, the
escape ledger, the dispatch telemetry, the ladder's ``stops.ndjson`` and the JUnit reports
under ``CI_LOCAL_MANIFEST_DIR`` (the dev-repo CI writer's ``pytest-main.xml`` and
``pytest-serial.xml``). File names come from the emitting modules, never retyped here.

A Signal is ``{kind, key, ref, operator_touch, rerun, skill}``. ``key`` is the structured
retro key: the most specific mechanism token with its class prefix (``path:``,
``finalizer:``, ``escape:``, ``junit:``), else ``event:<token>``. ``ref`` is a pointer
(``decisions.md:L<line>``, a ledger key, a row number), never a heading's free text: refs
become board evidence, and only shapes leave the machine. Each finalizer stop is its own
signal, so a halt that fired twice counts twice. Stdlib only.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
from pathlib import Path

_SHARED = str(Path(__file__).resolve().parent)
if _SHARED not in sys.path:
    sys.path.insert(0, _SHARED)

import ladder_files  # noqa: E402 — STOPS name and ladder_dir
import stopped_agents  # noqa: E402 — records() reads a stops file
from dispatch_log import NDJSON_NAME as TELEMETRY_NAME  # noqa: E402 — the telemetry file's name
from escape_ledger import NDJSON_NAME as ESCAPE_NAME  # noqa: E402 — the escape-ledger file's name
from finalizer import LedgerError, load_ledger  # noqa: E402
from junit_verdict import parse as parse_junit  # noqa: E402

RETRY_TOKENS = frozenset(("retry-with-advice", "retry", "retry-exhausted", "audit-retry-exhausted"))
_HALT_NAMES = ("worker-root-refused", "worker-root-open-failed", "sha-mismatch",
               "no-candidate-block", "worker-noop", "rerun-failed", "task-env-error",
               "map-check-escalated")
BLOCK_TOKENS = frozenset(_HALT_NAMES)
RELAY_MARKERS = ("Seat (under operator delegation", "Operator ruling")
ESCAPE_DISPOSITIONS = frozenset(("dropped", "downgraded", "opus-added"))
STOP_RESULTS = frozenset(("refused", "error"))
JUNIT_FILES = ("pytest-main.xml", "pytest-serial.xml")
LEDGER_NAME = "finalizer-ledger.json"

_HEADING = re.compile(r"^### \[([^\]\n]+)\][ \t]*(.*)$", re.MULTILINE)
_PATH = re.compile(r"(?<![\w/.-])(?:skills|agents)/[\w./-]*\w")
_FINALIZER_TITLE = re.compile(r"^(\S+)\s+—\s+([\w-]+)/([\w-]+)")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


def parse_entries(text: str) -> list[dict]:
    """Split ``decisions.md`` on ``### [prefix] title`` headings into entries; ``line`` is the
    heading's 1-based line number."""
    found = list(_HEADING.finditer(text or ""))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.append({"prefix": m.group(1).strip(), "title": m.group(2).strip(),
                    "body": text[m.end():end].strip(), "line": text.count("\n", 0, m.start()) + 1})
    return out


def _pointer(entry) -> str:
    """The evidence pointer for a decisions.md entry: its line, never its title text."""
    return f"decisions.md:L{entry['line']}"


def _norm(text: str) -> str:
    """Lower-case with every run of characters outside ``[a-z0-9]`` as one ``-``, edges trimmed."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _join(*parts: str) -> str:
    return "-".join(p for p in map(_norm, parts) if p)


def normalised_token(key: str) -> str:
    """The seed-match token and slug stem of a key: only ``[a-z0-9-]``, one token per key.

    ``path:`` keeps the parent directory beside the file stem, so two files that share a name
    (``skills/tp-design/SKILL.md``, ``skills/tp-spike/SKILL.md``) never share a token; a private
    container directory (``_shared``) is skipped, its files are named distinctly by design.
    ``junit:`` keeps the last class segment beside the test name.
    """
    cls, _, rest = key.partition(":")
    if cls == "path":
        path = Path(rest)
        parent = "" if path.parent.name.startswith("_") else path.parent.name
        return _join(parent, path.stem)
    if cls in ("finalizer", "escape"):
        return _norm(rest.replace(":", "-"))
    if cls == "junit":
        classname, _, name = rest.rpartition("::")
        return _join(classname.rpartition(".")[2], name)
    return _norm(rest)


def _signal(kind, key, ref, *, touch=False, rerun=False, skill="") -> dict:
    return {"kind": kind, "key": key, "ref": ref, "operator_touch": touch,
            "rerun": rerun, "skill": skill}


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _own_paths(design_dir: Path) -> set:
    lines = [ln for ln in _read(design_dir / "plan.md").splitlines() if "**File**" in ln]
    return set(_PATH.findall("\n".join(lines)))


def _entry_key(entry, token, own) -> str:
    for text in (entry["title"], entry["body"]):
        for path in _PATH.findall(text):
            if path not in own:
                return f"path:{path}"
    return f"event:{token}"


def _title_token(title: str) -> str:
    return (title.split() or [""])[0].lower().strip(".,:;()")


def _heading_signals(entries, own) -> list[dict]:
    out = []
    for e in entries:
        skill = e["prefix"].split("/")[0]
        if skill in ("run-retro", "finalizer"):  # B11: its own entries are never signals
            continue
        token = _title_token(e["title"])
        touch = any(m in e["title"] or m in e["body"] for m in RELAY_MARKERS)
        kind = "retry" if token in RETRY_TOKENS else "block" if token in BLOCK_TOKENS else (
            "touch" if touch else None)
        if kind:
            out.append(_signal(kind, _entry_key(e, token, own), _pointer(e), touch=touch,
                               rerun=kind == "retry", skill=skill))
    return out


def _finalizer_signals(design_dir: Path, entries) -> list[dict]:
    try:
        seen = load_ledger(design_dir / LEDGER_NAME)["seen"]
    except LedgerError:
        seen = {}
    by_key: dict = {}  # key -> one signal per stop, never merged
    for stop, outcome in seen.items():
        parts = stop.split(":")
        if len(parts) < 2:  # a key not shaped ``kind:name[:...]`` names no finalizer
            continue
        key = f"finalizer:{parts[0]}:{parts[1]}"
        by_key.setdefault(key, []).append(_signal(
            "finalizer", key, f"{LEDGER_NAME}: {stop}", touch=outcome == "escalate",
            skill="finalizer"))
    ledger_keys = set(by_key)  # order-independent: a non-escalate entry never creates a key
    used: dict = {}
    for e in entries:  # the n-th finalizer entry of a key annotates its n-th stop, or is one
        m = _FINALIZER_TITLE.match(e["title"]) if e["prefix"] == "finalizer" else None
        if not m:
            continue
        key = f"finalizer:{m.group(2)}:{m.group(3)}"
        escalate = m.group(1) == "escalate"
        if key not in ledger_keys and not escalate:
            continue
        sigs, n = by_key.setdefault(key, []), used.get(key, 0)
        used[key] = n + 1
        if n == len(sigs):
            sigs.append(_signal("finalizer", key, "", skill="finalizer"))
        sig, ref = sigs[n], _pointer(e)
        sig["ref"] = f"{sig['ref']}; {ref}" if sig["ref"] else ref
        sig["operator_touch"] = sig["operator_touch"] or escalate
    return [sig for sigs in by_key.values() for sig in sigs]


def _rows(path) -> list[dict]:
    rows = []
    for line in _read(path).splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _escape_signals(design_dir: Path) -> list[dict]:
    out = []
    for n, row in enumerate(_rows(design_dir / ESCAPE_NAME), 1):
        if row.get("disposition") in ESCAPE_DISPOSITIONS:
            key = f"escape:{row.get('role')}:{row['disposition']}"
            out.append(_signal("escape", key, f"{ESCAPE_NAME}:{n}"))
    return out


def _tokens(design_dir: Path) -> dict:
    totals: dict = {}
    for row in _rows(design_dir / TELEMETRY_NAME):
        n, role = row.get("tokens"), row.get("role")
        if isinstance(n, int) and not isinstance(n, bool) and isinstance(role, str):
            totals[role] = totals.get(role, 0) + n
    return totals


def _stop_signals(design_dir: Path, repo_root) -> list[dict]:
    try:
        path = ladder_files.ladder_dir(repo_root, design_dir.name) / ladder_files.STOPS
        records = stopped_agents.records(path)
    except Exception:  # noqa: BLE001 — fail-open: no ladder dir, no stop rows
        return []
    return [_signal("stop", f"event:stop-{r['result']}", f"{ladder_files.STOPS}:{n}")
            for n, r in enumerate(records, 1) if r.get("result") in STOP_RESULTS]


def _first_stamp(design_dir: Path):
    stamps = _STAMP.findall(_read(design_dir / "decisions.md"))
    if not stamps:
        return None
    try:
        first = min(datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ") for s in stamps)
    except ValueError:
        return None
    return first.replace(tzinfo=datetime.timezone.utc).timestamp()


def _junit_signals(design_dir: Path, env) -> list[dict]:
    base = (env or {}).get("CI_LOCAL_MANIFEST_DIR")
    if not base:
        return []
    first, out = _first_stamp(design_dir), []
    for name in JUNIT_FILES:
        path = Path(base) / name
        try:
            if first is not None and path.stat().st_mtime < first:
                continue  # a report older than the run is another run's
        except OSError:
            continue
        for _file, classname, test, outcome in parse_junit(path) or []:
            if outcome == "failed":
                out.append(_signal("ci_fail", f"junit:{classname}::{test}", name))
    return out


def collect(design_dir, *, repo_root, env=os.environ) -> dict:
    """``{signals: [Signal], tokens: {role: n}}`` for one design run; never raises on reads."""
    design_dir = Path(design_dir)
    entries = parse_entries(_read(design_dir / "decisions.md"))
    signals = (_heading_signals(entries, _own_paths(design_dir))
               + _finalizer_signals(design_dir, entries) + _escape_signals(design_dir)
               + _stop_signals(design_dir, repo_root) + _junit_signals(design_dir, env))
    return {"signals": signals, "tokens": _tokens(design_dir)}
