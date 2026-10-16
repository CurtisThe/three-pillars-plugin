#!/usr/bin/env python3
"""finalizer.py — prepare a stop for the one Fable finalizer (stop key, ledger, dispatch spec).

design: fable-first-stops (Task 1.3)

Every stop point (a ``/tp-pr-iterate`` budget terminal, an audit-gate retry
exhaustion, an orchestrator halt) goes to ONE ``tp-finalizer`` before the operator.
A Python module cannot spawn an agent, so this is the first step of a two-step
contract the calling prose drives: ``prepare`` (this module: build the brief and
the dispatch spec, or refuse) -> the caller spawns the agent -> ``apply``.

The stop is ``{"source", "signal", "target", "head"?, "detail"?}``; its key is
``source:signal:target[:sha256(detail)[:8]]`` (``target`` = PR URL or slug, never
the head SHA, so a fix that moves the head does not open a fresh stop):

- ``pr-iterate``: per signal (``round-cap``, ``wall-clock``, ...);
- ``audit-gate``: per slot, the signal is one of ``AUDIT_SLOTS``;
- ``halt``: per occurrence, the detail hash of a *normalised* detail (digit runs,
  hex ids and absolute paths stripped), so a recurring env-error keys the same.

The ledger (``finalizer-ledger.json``) makes "never a finalizer inside a
finalizer" and "never twice for one stop" mechanical: ``in_flight`` is
``{key, at}`` (or ``null``), ``seen`` maps each finalized key to its outcome,
``stale_cleared`` lists the keys of crashed finalizers whose marker aged past
``STALE_SEC``. ``prepare`` returns one of:

- ``dispatch`` — spawn ``agent_ref`` (model ``model``, else ``fallback``) with ``brief``;
- ``noop`` (``in-flight-same-target``) — a finalizer for this target is already running;
- ``refused`` with ``reason`` ``already-finalized`` | ``nested`` | ``ledger-unreadable``
  | ``agent-unresolved`` — the caller escalates without a dispatch.

A corrupt ledger fails closed (``ledger-unreadable``), never to a second dispatch.
Times are epoch seconds (numbers). Seams are injectable (``resolve_fn``, ``now``).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import agent_ref  # noqa: E402
import finalizer_ruling  # noqa: E402
from finalizer_outcome import (ALLOWED_ACTIONS, DESIGN_DOCS, GROUNDING_DOCS,  # noqa: E402
                               REPLY_KEYS)

try:  # 1.2 owns the constant; the literal keeps this module independent of it
    from model_policy import FINALIZER_FALLBACK as _FALLBACK  # noqa: E402
except ImportError:
    _FALLBACK = {"model": "opus", "effort": "xhigh"}

SOURCES = ("pr-iterate", "audit-gate", "halt", "question")
AUDIT_SLOTS = ("design", "plan", "implementation")
STALE_SEC = 7200
FINALIZER_AGENT = "tp-finalizer"
FINALIZER_MODEL = "fable"
_HASH_LEN = 8
_HINTS = {
    "pr-iterate": "A PR-loop budget terminal. Resolved = the loop may continue past the "
    "limit (the caller records one bounded extension and runs the converging round).",
    "audit-gate": "An audit gate out of retries. Resolved = you patched the artifact and "
    "ONE re-audit returned PASS; never lower the floor.",
    "halt": "An orchestrator halt (env-error). Resolved = the run can continue; answer "
    "only from design.md, decisions.md and recorded rulings.",
    "question": "A question stop: a `resolved` needs a chosen option with a verbatim `serves` "
    "quote from vision.md or architecture.md; no basis -> reply `escalate`.\n"
    "Seat entry: the operator's seat asked the question directly; reply the same envelope.",
}
# pr-loop §B: a stop carrying `mix` (round_mix.attach) is told what to do about it.
_SIGNAL_HINTS = {"structural-rewrite": "Rewrite the named area as one change; any size is allowed "
                 "(ruling 2). Resolved = the rewrite is committed and the loop runs a delta round "
                 "on it."}

_PATH = re.compile(r"(?<![\w:/.~-])(?:~)?/[^\s'\"`]+")
_HEX_ID = re.compile(r"\b[0-9a-fA-F]{7,}\b")
_DIGITS = re.compile(r"\d+")


class LedgerError(ValueError):
    """The ledger file exists but is unreadable or malformed."""


def normalize_detail(detail) -> str:
    """Halt detail with volatile tokens stripped: paths, hex ids, digit runs."""
    if detail is None:
        text = ""
    elif isinstance(detail, str):
        text = detail
    else:
        text = json.dumps(detail, sort_keys=True, default=str)
    text = _PATH.sub("<path>", text)
    text = _HEX_ID.sub("#", text)
    text = _DIGITS.sub("#", text)
    return " ".join(text.split())


def _check_stop(stop) -> tuple:
    """``(source, signal, target)`` of a well-formed stop, else ``ValueError``."""
    if not isinstance(stop, dict):
        raise ValueError(f"stop must be an object, got {type(stop).__name__}")
    source, signal, target = stop.get("source"), stop.get("signal"), stop.get("target")
    if source not in SOURCES:
        raise ValueError(f"unknown stop source {source!r}; expected one of {SOURCES}")
    if source == "audit-gate" and signal not in AUDIT_SLOTS:
        raise ValueError(f"audit-gate signal {signal!r} must be one of {AUDIT_SLOTS}")
    if source == "question" and signal not in finalizer_ruling.KINDS:
        raise ValueError(f"question kind {signal!r} must be one of {finalizer_ruling.KINDS}")
    if not isinstance(signal, str) or not signal or ":" in signal:
        raise ValueError(f"stop signal must be a non-empty string without ':', got {signal!r}")
    if not isinstance(target, str) or not target:
        raise ValueError(f"stop target must be a non-empty string, got {target!r}")
    return source, signal, target


def stop_key(stop) -> str:
    """The one-finalizer-per-stop identity; ``ValueError`` for a malformed stop."""
    source, signal, target = _check_stop(stop)
    key = f"{source}:{signal}:{target}"
    if source in ("halt", "question"):
        detail = stop.get("detail")
        if source == "question":  # a non-dict detail carries no question -> hash of ""
            detail = detail.get("question") if isinstance(detail, dict) else None
        digest = hashlib.sha256(normalize_detail(detail).encode("utf-8"))
        key += ":" + digest.hexdigest()[:_HASH_LEN]
    return key


def _target_of_key(key) -> str:
    """The target inside a well-formed key, else ``ValueError``."""
    parts = key.split(":", 2) if isinstance(key, str) else []
    if len(parts) != 3 or parts[0] not in SOURCES or not parts[1]:
        raise ValueError(f"malformed stop key {key!r}")
    target = parts[2]
    if parts[0] in ("halt", "question"):
        target, _, digest = target.rpartition(":")
        if len(digest) != _HASH_LEN:
            raise ValueError(f"malformed halt key {key!r}")
    if not target:
        raise ValueError(f"malformed stop key {key!r}")
    return target


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate(data) -> dict:
    if not isinstance(data, dict):
        raise LedgerError("ledger is not a JSON object")
    ledger = {"in_flight": None, "seen": {}, "stale_cleared": []}
    ledger.update({k: data[k] for k in ledger if k in data})
    flight, seen, cleared = ledger["in_flight"], ledger["seen"], ledger["stale_cleared"]
    if flight is not None:
        if not isinstance(flight, dict) or not _number(flight.get("at")):
            raise LedgerError("in_flight must be {key, at} with a numeric at")
        try:
            _target_of_key(flight.get("key"))
        except ValueError as exc:
            raise LedgerError(f"in_flight: {exc}") from None
    if not isinstance(seen, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in seen.items()
    ):
        raise LedgerError("seen must map stop keys to outcome strings")
    if not isinstance(cleared, list) or not all(isinstance(k, str) for k in cleared):
        raise LedgerError("stale_cleared must be a list of stop keys")
    return ledger


def load_ledger(ledger_path) -> dict:
    """The ledger dict (empty when the file is missing); ``LedgerError`` when corrupt."""
    try:
        text = Path(ledger_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _validate({})
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"{ledger_path} unreadable ({exc})") from None
    try:
        return _validate(json.loads(text))
    except ValueError as exc:
        if isinstance(exc, LedgerError):
            raise LedgerError(f"{ledger_path}: {exc}") from None
        raise LedgerError(f"{ledger_path} is not valid JSON ({exc})") from None


def save_ledger(ledger_path, ledger: dict) -> None:
    """Atomic write: a tmp file beside the ledger, then ``os.replace``."""
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    try:
        tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _expire(ledger: dict, now) -> list:
    """Clear an in-flight marker older than ``STALE_SEC`` in memory; the cleared keys."""
    flight = ledger["in_flight"]
    if flight is None or now - flight["at"] <= STALE_SEC:
        return []
    ledger["in_flight"] = None
    ledger["stale_cleared"].append(flight["key"])
    return [flight["key"]]


def clear_stale(ledger_path, now=None):
    """Clear (and record) a stale in-flight marker; the cleared key, else ``None``."""
    ledger = load_ledger(ledger_path)
    cleared = _expire(ledger, time.time() if now is None else now)
    if cleared:
        save_ledger(ledger_path, ledger)
    return cleared[0] if cleared else None


def clear_in_flight(ledger_path, key: str, outcome: str) -> bool:
    """Record ``key`` as seen (``outcome``); clear the marker only if it is ``key``'s.

    True when the in-flight marker was cleared. Idempotent, and never touches
    another key's marker.
    """
    ledger = load_ledger(ledger_path)
    flight = ledger["in_flight"]
    cleared = flight is not None and flight["key"] == key
    if cleared:
        ledger["in_flight"] = None
    ledger["seen"][key] = outcome
    save_ledger(ledger_path, ledger)
    return cleared


def _render(value) -> str:
    if value is None or value == "":
        return "(none)"
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def _grounding(repo_root, decisions) -> list:
    """The grounding docs that exist, repo-relative; a consumer repo's missing ones are skipped."""
    root = Path(repo_root)
    found = [d for d in GROUNDING_DOCS if (root / d).exists()]
    design_dir = Path(decisions).parent
    for name in DESIGN_DOCS:
        path = design_dir / name
        if path.exists():
            try:
                found.append(str(path.resolve().relative_to(root.resolve())))
            except ValueError:
                found.append(str(path))
    return found


def _mix_lines(stop: dict) -> list:
    """The §B hint then a blank line for a known ``mix`` signal; else ``[]`` (brief unchanged)."""
    mix = stop.get("mix") if isinstance(stop.get("mix"), dict) else {}
    hint = _SIGNAL_HINTS.get(mix.get("signal"))
    return [] if hint is None else [
        "", f"Structural-rewrite signal for area `{mix.get('area') or '.'}`: {hint}"]


def _brief(stop: dict, key: str, decisions, repo_root=".", entry="run") -> str:
    source, signal, target = stop["source"], stop["signal"], stop["target"]
    lines = [
        "Finalizer brief: one stop needs your diagnosis before the operator is involved.",
        "",
        f"- source: {source}",
        f"- signal: {signal}",
        f"- target: {target}",
    ]
    if stop.get("head"):
        lines.append(f"- head: {stop['head']}")
    lines += [
        f"- stop key: {key}",
        f"- detail: {_render(stop.get('detail'))}",
        f"- decisions log: {decisions}",
        "",
        _HINTS[source],
        "",
        "Diagnose, apply the real-usage blocking bar, fix within your allowlist, and "
        "reply with ONLY the JSON envelope from your agent file ("
        + ", ".join(f"`{k}`" for k in REPLY_KEYS) + "): one JSON object, bare or in one "
        "```json fence, with no prose around it. Anything else escalates.",
        "`actions` is a list of action tokens, each exactly one of: "
        + ", ".join(f"`{a}`" for a in ALLOWED_ACTIONS)
        + ". Any other string escalates. Put free-text detail (files, tests, results) "
        "in `reasoning`, never in `actions`.",
        "`blocked` lists ONLY actions a permission or classifier denial stopped; "
        "anything else goes in `reasoning`. A non-empty `blocked` escalates.",
    ]
    lines[lines.index(_HINTS[source]) + 1:lines.index(_HINTS[source]) + 1] = _mix_lines(stop)
    if source == "question":
        lines += [""] + finalizer_ruling.brief_lines(entry, repo_root, decisions)
    else:
        lines += [
            "",
            "Grounding (read before ruling, per your agent file; missing docs are skipped):",
            *([f"- {doc}" for doc in _grounding(repo_root, decisions)] or ["- (none found)"]),
            "A `resolved` names in `reasoning` the doc (path or file name) and the principle "
            "or priority that drove the call; an uncited `resolved` escalates. If the docs "
            "do not settle the call, or it conflicts with vision or architecture, reply "
            "`escalate`.",
        ]
    return "\n".join(lines)


def _refuse(reason: str, detail: str = "", stale=()) -> dict:
    return {"status": "refused", "reason": reason, "detail": detail, "stale_cleared": list(stale)}


def prepare(stop, ledger_path, resolve_fn=None, now=None, decisions_path=None,
            repo_root=".", entry="run") -> dict:
    """Dispatch spec for ``stop`` (marking it in flight), a ``noop``, or a refusal.

    ``ValueError`` for a malformed stop, before anything is read or written.
    ``decisions_path`` defaults to ``decisions.md`` beside the ledger; ``repo_root`` (the
    cwd by default) anchors the grounding docs the brief lists; ``entry`` (``run`` |
    ``seat``) names the entry a question brief answers from.
    """
    key = stop_key(stop)
    now = time.time() if now is None else now
    try:
        ledger = load_ledger(ledger_path)
    except LedgerError as exc:
        return _refuse("ledger-unreadable", str(exc))
    stale = _expire(ledger, now)
    flight = ledger["in_flight"]
    if flight is not None:  # nothing expired, so nothing to persist on these two exits
        if _target_of_key(flight["key"]) == stop["target"]:
            return {"status": "noop", "reason": "in-flight-same-target"}
        return _refuse("nested", f"finalizer in flight for {flight['key']}")
    if key in ledger["seen"]:
        if stale:
            save_ledger(ledger_path, ledger)
        return _refuse("already-finalized", f"{key} was {ledger['seen'][key]}", stale)
    try:
        ref = (resolve_fn or agent_ref.resolve)(FINALIZER_AGENT)
    except agent_ref.AgentRefError as exc:
        if stale:
            save_ledger(ledger_path, ledger)
        return _refuse("agent-unresolved", str(exc), stale)
    ledger["in_flight"] = {"key": key, "at": now}
    save_ledger(ledger_path, ledger)
    decisions = decisions_path or Path(ledger_path).parent / "decisions.md"
    return {
        "status": "dispatch",
        "key": key,
        "agent_ref": ref,
        "model": FINALIZER_MODEL,
        "fallback": dict(_FALLBACK),
        "brief": _brief(stop, key, decisions, repo_root, entry),
        "stale_cleared": stale,
    }
