#!/usr/bin/env python3
"""cheap_oracle.py — the oracle contract for cheap-tier slots.

design: cheap-tier-offload (Phase 2)

Every cheap-tier slot (cheap_tier.SLOTS) names an oracle: a check that decides
whether the cheap attempt is used. check(slot, artifact, ctx) runs it and
returns a Verdict; settle(slot, verdict) turns that into what the site does
next ("accept", or the slot on_fail: "drop" / "escalate").

The contract:

- An oracle is fn(artifact, ctx) -> (ok, reason), registered by name with the
  register(name) decorator. It recomputes from ctx paths and argv and never
  reads the artifact own claims ("ok", "ran", "exit", "passed").
- An exception inside an oracle gives ok=False, reason="oracle-error: ...";
  check never raises for an oracle failure. An unregistered oracle is not ok.
- An unknown slot, or "task" (its oracle is task_verify, run by the ladder),
  raises ValueError.

This module holds the text oracles (no subprocess). The executing oracles live
in cheap_oracle_run.py and the prose oracle in prose_oracle.py; on a registry
miss, check imports them lazily and they register themselves on import.
prose_shape (the handoff / history_line / docs_draft slots, Phase 7) takes the
draft as artifact["text"] or the file at artifact["path"], and reads ctx["kind"]
(the slot), ctx["root"], ctx["facts"] (the facts payload the drafter was given)
and optional ctx["required"] (extra headings or field prefixes). A missing
ctx key is an oracle-error, so the slot drops its draft.

hunk_bytes (the review_slice slot, design cheap-tier-review-prep) takes
artifact["hunks"], a list of {"file", "hunk"}, and ctx["diff_path"], the full diff
text. It passes only when every hunk is exactly a hunk of that diff.

Stdlib-only at import: classifier_schema imports classifier_judge (which needs
jsonschema) inside its own body, so a repo without jsonschema can still import
this module, and that one oracle fails as an oracle-error (escalate).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, TypedDict

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import cheap_tier  # noqa: E402 — in-repo, stdlib-only sibling

_PR_ITERATE_SCRIPTS = _SHARED.parent / "tp-pr-iterate" / "scripts"
_LAZY_MODULES = ("cheap_oracle_run", "prose_oracle")


class Verdict(TypedDict):
    ok: bool
    oracle: str
    reason: str


Oracle = Callable[[dict, dict], "tuple[bool, str]"]
ORACLES: dict[str, Oracle] = {}


def register(name: str):
    """Decorator: register fn as the oracle called name (a re-register replaces)."""
    def _add(fn):
        ORACLES[name] = fn
        return fn
    return _add


def _row(slot: str) -> cheap_tier.Slot:
    if slot == "task":
        raise ValueError("the task slot is checked by task_verify through the ladder")
    if slot not in cheap_tier.SLOTS:
        raise ValueError(f"unknown cheap-tier slot {slot!r}")
    return cheap_tier.SLOTS[slot]


def _lookup(name: str):
    """The registered oracle, importing the lazy oracle modules on a miss."""
    for module in _LAZY_MODULES:
        if name in ORACLES:
            break
        try:
            importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name != module:
                raise
    return ORACLES.get(name)


def _verdict(ok: bool, oracle: str, reason: str) -> Verdict:
    return {"ok": bool(ok), "oracle": oracle, "reason": str(reason)}


def check(slot: str, artifact: dict, ctx: dict) -> Verdict:
    """Run the slot oracle on artifact with ctx. Never raises for an oracle failure."""
    name = _row(slot).oracle
    try:
        fn = _lookup(name)
        if fn is None:
            return _verdict(False, name, f"unregistered oracle {name!r}")
        ok, reason = fn(artifact, ctx)
    except Exception as exc:  # noqa: BLE001 — any oracle failure is a failed check
        return _verdict(False, name, f"oracle-error: {type(exc).__name__}: {exc}")
    return _verdict(ok, name, reason)


def settle(slot: str, verdict: Verdict) -> str:
    """"accept" when the verdict is ok, else the slot on_fail ("drop" / "escalate")."""
    row = _row(slot)
    return "accept" if verdict.get("ok") is True else row.on_fail


# --- text oracles (pure) ---------------------------------------------------------


@register("classifier_schema")
def classifier_schema(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """classifier_judge.parse_response accepts artifact["response"], and its
    comment ids equal ctx["borderline_ids"] exactly once each (compared as str)."""
    scripts = str(_PR_ITERATE_SCRIPTS)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import classifier_judge  # lazy: needs jsonschema, which is not stdlib

    entries = classifier_judge.parse_response(artifact["response"])
    got = [str(e["comment_id"]) for e in entries]
    want = [str(i) for i in ctx["borderline_ids"]]
    if sorted(got) == sorted(want) and len(set(got)) == len(got):
        return True, ""
    extra = sorted(set(got) - set(want))
    missing = sorted(set(want) - set(got))
    dup = sorted(i for i in set(got) if got.count(i) > 1)
    return False, (f"ids differ from the borderline set: extra {extra}, "
                   f"missing {missing}, duplicate {dup}")


# --- hunk_bytes: review_slice (design: cheap-tier-review-prep, Phase 2) -----------


def _lines(text: str) -> list[str]:
    """Split on "\\n" only, keeping it. Not str.splitlines: that also splits on \\x0c,
    \\x85, \\u2028 and others, which can sit inside hunk content and would fake a line
    start. A last line with no newline is kept as it is."""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _header_file(header: list[str]) -> str | None:
    """The file a block names, from its header lines only: "+++ b/", else "--- a/"
    (a deletion has "+++ /dev/null"). git adds a tab after a name with spaces."""
    names = {}
    for line in header:
        for prefix in ("+++ b/", "--- a/"):
            if line.startswith(prefix) and prefix not in names:
                names[prefix] = line[len(prefix):].removesuffix("\n").removesuffix("\t")
    return names.get("+++ b/") or names.get("--- a/")


def _diff_hunks(text: str) -> set[tuple[str, str]]:
    """Every (file, hunk) of a `git diff` text, hunk bytes exact.

    A block starts at a line beginning "diff --git ". Its header is the lines up to the
    first line beginning "@@"; the file is read from the header only, so a hunk line
    such as "+++ b/q" is content. A hunk runs from a line beginning "@@" through the
    line before the next "@@" or "diff --git " line, newline-terminated. A block with
    no hunk (binary, pure rename, mode-only) contributes nothing. A block with hunks
    whose header names no file raises ValueError."""
    blocks: list[list[str]] = []
    for line in _lines(text):
        if line.startswith("diff --git "):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
    found: set[tuple[str, str]] = set()
    for block in blocks:
        starts = [i for i, line in enumerate(block) if line.startswith("@@")]
        if not starts:
            continue
        name = _header_file(block[1:starts[0]])
        if not name:
            raise ValueError(f"no file in the header of {block[0].rstrip()!r}")
        for begin, end in zip(starts, starts[1:] + [len(block)]):
            hunk = "".join(block[begin:end])
            found.add((name, hunk if hunk.endswith("\n") else hunk + "\n"))
    return found


def _slice_entry(entry) -> tuple[str, str] | None:
    if (isinstance(entry, dict) and isinstance(entry.get("file"), str)
            and isinstance(entry.get("hunk"), str)):
        return entry["file"], entry["hunk"]
    return None


@register("hunk_bytes")
def hunk_bytes(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """artifact["hunks"] is a non-empty list of {"file", "hunk"}, with no pair twice and
    every pair exactly a (file, hunk) of the diff text at ctx["diff_path"]: no strip,
    no normalisation. A failure names the index of the hunk that failed."""
    hunks = artifact["hunks"]
    if not isinstance(hunks, list):
        return False, "hunks is not a list"
    if not hunks:
        return False, "hunks is an empty list (need at least 1)"
    raw = Path(ctx["diff_path"]).read_bytes()  # bytes: no newline translation
    parsed = _diff_hunks(raw.decode("utf-8", errors="surrogateescape"))
    if len(hunks) > len(parsed):
        return False, (f"hunk {len(parsed)}: more hunks than the diff has "
                       f"({len(hunks)} > {len(parsed)})")
    seen: dict[tuple[str, str], int] = {}
    for i, entry in enumerate(hunks):
        pair = _slice_entry(entry)
        if pair is None:
            return False, f"hunk {i}: not an object with a str file and a str hunk"
        if pair in seen:
            return False, f"hunk {i}: duplicate of hunk {seen[pair]}"
        if pair not in parsed:
            return False, f"hunk {i}: not byte-for-byte a hunk of {pair[0]!r} in the diff"
        seen[pair] = i
    return True, ""


# --- path_line and log_substring: review-prep (design: cheap-tier-review-prep) ----

REFS_CAP = 60       # max refs one review_refs artifact may carry
QUOTE_CAP = 4000    # max chars one ci_log_triage quote may hold
NOTE_MAX = 200      # max chars one ref note may hold


def _ref_entry(ref) -> tuple[str, int, str] | None:
    """A ref entry, or None. A bool line is not a valid int line (bool is a subclass
    of int, so it is excluded before the int check)."""
    if (isinstance(ref, dict) and isinstance(ref.get("path"), str)
            and not isinstance(ref.get("line"), bool)
            and isinstance(ref.get("line"), int)
            and isinstance(ref.get("note"), str)):
        return ref["path"], ref["line"], ref["note"]
    return None


@register("path_line")
def path_line(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """artifact["refs"] is a non-empty list of {"path", "line", "note"} with at most
    REFS_CAP entries. Each path is relative with no ".." part and resolves (symlinks
    followed) under ctx["root"] to a regular file; 1 <= line <= the file's line count;
    note is at most 200 chars. A failure names the ref's index."""
    refs = artifact["refs"]
    if not isinstance(refs, list):
        return False, "refs is not a list"
    if not refs:
        return False, "refs is an empty list (need at least 1)"
    if len(refs) > REFS_CAP:
        return False, f"ref {REFS_CAP}: more refs than REFS_CAP ({len(refs)} > {REFS_CAP})"
    root = Path(ctx["root"]).resolve()
    for i, ref in enumerate(refs):
        entry = _ref_entry(ref)
        if entry is None:
            return False, (f"ref {i}: not an object with a str path, an int line "
                           f"(a bool is not an int) and a str note")
        path, line, note = entry
        rel = Path(path)
        if rel.is_absolute():
            return False, f"ref {i}: path {path!r} is not relative"
        if ".." in rel.parts:
            return False, f"ref {i}: path {path!r} has a .. part"
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            return False, (f"ref {i}: {path!r} resolves outside the root "
                           f"({target})")
        if not target.is_file():
            return False, (f"ref {i}: {path!r} is not a regular file under the root")
        count = len(_lines(target.read_text(encoding="utf-8")))
        if not 1 <= line <= count:
            return False, f"ref {i}: line {line} not in 1..{count}"
        if len(note) > NOTE_MAX:
            return False, f"ref {i}: note is {len(note)} chars (max {NOTE_MAX})"
    return True, ""


@register("log_substring")
def log_substring(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """artifact["quote"] is a non-empty str of at most QUOTE_CAP chars, a verbatim
    substring of the log text at ctx["log_path"], and artifact["step"] is a non-empty
    substring of that log (a `gh --log-failed` line carries <job>\t<step>\t…).
    No strip, no normalisation: one edited byte fails."""
    quote = artifact["quote"]
    step = artifact["step"]
    if not isinstance(quote, str) or not quote:
        return False, "quote is not a non-empty str"
    if len(quote) > QUOTE_CAP:
        return False, f"quote is {len(quote)} chars (max {QUOTE_CAP})"
    if not isinstance(step, str) or not step:
        return False, "step is not a non-empty str"
    log = Path(ctx["log_path"]).read_text(encoding="utf-8")
    if quote not in log:
        return False, "quote is not a verbatim substring of the log"
    if step not in log:
        return False, f"step {step!r} is not a substring of the log"
    return True, ""
