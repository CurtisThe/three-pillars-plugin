"""rule_ledger.py — the D7 rule-ledger format and its check.

design: skill-context-diet (Task 1.3)

A ledger records where every rule of the pre-diet text went in the condensed
text (design D7). It is JSONL:

  line 1   the header: source, source_blob, base_ref, ranges, kinds, fragment,
           final, budget, final_blob, peer_blobs
  line 2+  one row per extracted item: kind, old, verdict, and the verdict's
           payload — needle | reason | file | test

`check(path, root)` returns one line per problem, each leading with its class
token (`todo`, `needle`, `reason`, `archived`, `repointed`, `budget`,
`unsealed`, `rows`, `hash`, `verdict`); an empty list means the ledger is
clean. `rule_ledger_cli` (Task 1.4) is the command line over this module:
`skeleton` builds a new ledger, `seal` records the final blobs, `coverage`
proves the slices tile their source, and `check_files` / `check_dir` run `check`
over many ledgers with one `ledger: problem` line each.

Two rules let a ledger outlive the design that wrote it:

* **Blob-bound needles.** Once the swap seals the ledger (`final_blob` set,
  Procedure W2h) the kept needles are read from that blob and the `peer_blobs`
  blobs, never from the live destination, so a later design editing the doc
  never fails a committed ledger. `live` is the one exception, run at swap time
  only: it reads the live files and additionally requires each to still hash to
  its sealed blob.
* **Rows-only fallback.** When a blob is unreachable (`git cat-file -e` fails —
  a squash-merged clone, a rewritten branch) the tool checks the rows it can
  check and says nothing about needle text or completeness, rather than
  reporting a false failure.

stdlib-only. It ships, so it cannot use the dev-only `git_env` helper: it
scrubs the repo-local git env itself (invariant #42's rule, inline) because it
runs git against the caller's `root`, which is not this repo.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from rule_ledger_extract import (
    extract_headings,
    extract_items,
    extract_pins,
    extract_rules,
    pin_tests_for,
)

__all__ = ["HEADER_FIELDS", "DROPPED_REASONS", "VERDICTS", "KINDS", "load", "dump",
           "check", "check_files", "check_dir", "skeleton", "seal", "coverage",
           "git_blob", "head_ref", "ledger_label", "LOAD_ERRORS"]

# The header fields, in the plan's order.
HEADER_FIELDS = ("source", "source_blob", "base_ref", "ranges", "kinds",
                 "fragment", "final", "budget", "final_blob", "peer_blobs")

# Procedure S step 4: the reason a `dropped` row must name.
DROPPED_REASONS = ("duplicate", "obsolete", "rationale", "history", "superseded", "resolved")

# Procedure S step 4 plus the `todo` the extract skeleton leaves behind.
VERDICTS = ("todo", "kept", "dropped", "archived", "repointed", "unpinned")

# header `kinds` → the extractor that re-derives the row set for completeness.
_EXTRACTORS = {
    "rules": lambda text, src, root: extract_rules(text),
    "items": lambda text, src, root: extract_items(text),
    "headings": lambda text, src, root: extract_headings(text),
    "pins": lambda text, src, root: extract_pins(text, pin_tests_for(src, root)),
}
KINDS = tuple(_EXTRACTORS)  # the header `kinds` an extract may name


def _git_env() -> dict:
    """os.environ minus every GIT_* var — `root` is a different repository."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root),
                          capture_output=True, text=True, env=_git_env())


def _reachable(root, blob) -> bool:
    return bool(blob) and _git(root, "cat-file", "-e", str(blob)).returncode == 0


def _blob_text(root, blob) -> str:
    proc = _git(root, "cat-file", "blob", str(blob))
    return proc.stdout if proc.returncode == 0 else ""


def _read(root, rel) -> str:
    try:
        return (Path(root) / str(rel)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _is_file(root, rel) -> bool:
    return bool(rel) and (Path(root) / str(rel)).is_file()


def _peer_items(peer_blobs) -> list:
    """`peer_blobs` as (path, blob) pairs: a dict once peers exist, [] until then."""
    if isinstance(peer_blobs, dict):
        return list(peer_blobs.items())
    return [(None, blob) for blob in (peer_blobs or [])]


def load(path) -> dict:
    """Parse a ledger into {"header": {...}, "rows": [...]}.

    A header missing one of the Task 1.3 fields raises: a half-written ledger
    would otherwise be checked for less than the design expects.
    """
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path}: empty ledger")
    header = json.loads(lines[0])
    missing = [field for field in HEADER_FIELDS if field not in header]
    if missing:
        raise ValueError(f"{path}: header missing {', '.join(missing)}")
    return {"header": header, "rows": [json.loads(ln) for ln in lines[1:]]}


def _seal_hash_problems(root, header, peers) -> list:
    """`live` only: every live destination must still hash to its sealed blob."""
    named = [(header.get("final"), header.get("final_blob"))]
    named += [(path, blob) for path, blob in peers if path]
    problems = []
    for rel, blob in named:
        if not blob or not _is_file(root, rel):
            continue
        proc = _git(root, "hash-object", "--", str(rel))
        if proc.returncode == 0 and proc.stdout.strip() != blob:
            problems.append(f"hash: {rel} no longer hashes to {blob}")
    return problems


def _needle_texts(header, root, final_only, live) -> tuple:
    """(texts a kept needle must appear in, problems). Empty texts: rows only."""
    final_blob = header.get("final_blob")
    peers = _peer_items(header.get("peer_blobs"))

    if final_blob:
        if not live:
            if not _reachable(root, final_blob):
                return [], []  # unreachable seal: rows only
            blobs = [final_blob] + [blob for _, blob in peers]
            return [_blob_text(root, b) for b in blobs if _reachable(root, b)], []
        texts = [_read(root, header.get("final"))]
        texts += [_read(root, path) for path, _ in peers if path]
        return texts, _seal_hash_problems(root, header, peers)

    if final_only or live:
        return [], [f"unsealed: {header.get('source')} names no final_blob"]
    if not _is_file(root, header.get("fragment")):
        return [], [f"unsealed: {header.get('source')} has no final_blob "
                    f"and its fragment {header.get('fragment')!r} is gone"]
    return [_read(root, header.get("fragment"))], []


def _budget_problem(header, root, final_only, live) -> list:
    """The staged fragment is over its budget (Procedure S step 3)."""
    if final_only or live or not header.get("fragment"):
        return []  # the fragment is not the text under check
    frag = header["fragment"]
    if not _is_file(root, frag):
        return []
    budget = header.get("budget")
    size = len(_read(root, frag))
    if isinstance(budget, int) and size > budget:
        return [f"budget: fragment {frag} is {size} chars, over {budget}"]
    return []


def _row_problem(row, line, texts, root) -> list:
    verdict, old = row.get("verdict"), row.get("old")
    where = f"line {line} ({row.get('kind')})"
    if verdict == "todo":
        return [f"todo: {where}: unfilled row: {old!r}"]
    if verdict == "kept":
        if not texts:
            return []
        needle = row.get("needle")
        if not needle:
            return [f"needle: {where}: kept row names no needle: {old!r}"]
        if needle in "\n".join(texts):
            return []
        return [f"needle: {where}: kept row {old!r} has no needle {needle!r} in its text"]
    if verdict == "dropped":
        reason = row.get("reason")
        if reason in DROPPED_REASONS:
            return []
        return [f"reason: {where}: dropped row reason {reason!r} "
                f"is not one of {', '.join(DROPPED_REASONS)}"]
    if verdict == "archived":
        rel = row.get("file")
        if rel and old and old in _read(root, rel):
            return []
        return [f"archived: {where}: {old!r} is not verbatim in {rel!r}"]
    if verdict == "repointed":
        rel = row.get("test")
        if rel and old and old in _read(root, rel):
            return [f"repointed: {where}: {rel} still contains the literal {old!r}"]
        return []
    if verdict == "unpinned":
        return []
    return [f"verdict: {where}: unknown verdict {verdict!r}"]


def _range_text(text, ranges) -> str:
    """The lines of `text` covered by the header's 1-based inclusive ranges."""
    lines = text.splitlines()
    picked: list[str] = []
    for rng in ranges or []:
        picked.extend(lines[max(int(rng[0]), 1) - 1:int(rng[1])])
    return "\n".join(picked)


def _completeness_problems(header, rows, root) -> list:
    """Re-extract the ranges from `source_blob`; a row-set mismatch is a problem."""
    blob, src = header.get("source_blob"), header.get("source")
    if not _reachable(root, blob):
        return []  # unreachable base: rows only
    text = _range_text(_blob_text(root, blob), header.get("ranges"))
    problems = []
    for kind in header.get("kinds") or []:
        if kind == "pins" and header.get("final_blob"):
            continue  # sealed: later tests naming the source are not this ledger's pins
        extract = _EXTRACTORS.get(kind)
        if extract is None:
            problems.append(f"rows: unknown kind {kind!r}")
            continue
        want = {str(item) for item in extract(text, src, root)}
        have = {str(row.get("old")) for row in rows if row.get("kind") == kind}
        if want == have:
            continue
        problems.append(
            f"rows: {kind} rows do not match the {src} ranges: "
            f"missing {sorted(want - have)}, extra {sorted(have - want)}")
    return problems


def check(path, root, final_only=False, live=False) -> list:
    """Every problem in the ledger at `path`, one line each; [] means clean.

    `final_only` is the committed-ledger posture: the fragment is ignored and an
    unsealed ledger is itself a problem. `live` is the swap-time posture: the
    needles come from the live destination (and the live peer destinations), and
    each must still hash to its sealed blob.
    """
    doc = load(path)
    header, rows = doc["header"], doc["rows"]
    texts, problems = _needle_texts(header, root, final_only, live)
    problems += _budget_problem(header, root, final_only, live)
    for offset, row in enumerate(rows):
        problems += _row_problem(row, offset + 2, texts, root)
    problems += _completeness_problems(header, rows, root)
    return problems


# ------------------------------------------------------------------ #
# Task 1.4: the library behind rule_ledger_cli
# ------------------------------------------------------------------ #

LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError)


def git_blob(root, rel, write=False) -> str:
    """The blob id of the file `rel` under `root` ("" when git cannot hash it).

    `write` stores the blob in the object database (`git hash-object -w`), so a
    later `cat-file` finds it even after the file itself has been rewritten.
    """
    proc = _git(root, "hash-object", *(["-w"] if write else []), "--", str(rel))
    return proc.stdout.strip() if proc.returncode == 0 else ""


def head_ref(root) -> str:
    """The short sha of HEAD under `root` ("" outside a repository)."""
    proc = _git(root, "rev-parse", "--short=8", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def dump(path, header, rows) -> None:
    """Write a ledger: the header line, then one row per line."""
    lines = [json.dumps(header, ensure_ascii=False)]
    lines += [json.dumps(row, ensure_ascii=False) for row in rows]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("".join(line + "\n" for line in lines), encoding="utf-8")


def skeleton(root, source, ranges, kinds, fragment, final, budget, base_ref) -> tuple:
    """(header, rows) of a new ledger for the 1-based `ranges` of `source`.

    Every row is `todo`; the header's `source_blob` is the blob the rows were
    extracted from (written to the object store, so the completeness check can
    re-read it after the swap rewrites the file). Raises ValueError on an
    unknown kind or a source git cannot hash.
    """
    unknown = [kind for kind in kinds if kind not in _EXTRACTORS]
    if unknown:
        raise ValueError(f"unknown kind {unknown[0]!r}; the kinds are {', '.join(KINDS)}")
    if not _is_file(root, source):
        raise ValueError(f"source {source!r} is not a file")
    blob = git_blob(root, source, write=True)
    if not blob:
        raise ValueError(f"git cannot hash source {source!r}")
    text = _range_text(_read(root, source), ranges)
    header = {"source": source, "source_blob": blob, "base_ref": base_ref,
              "ranges": [[int(a), int(b)] for a, b in ranges], "kinds": list(kinds),
              "fragment": fragment, "final": final, "budget": budget,
              "final_blob": None, "peer_blobs": []}
    rows = [{"kind": kind, "old": old, "verdict": "todo"}
            for kind in kinds for old in _EXTRACTORS[kind](text, source, root)]
    return header, rows


def ledger_label(root, path) -> str:
    """`path` relative to `root` when it sits under it, else as given."""
    try:
        return (Path(root) / path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def check_files(paths, root, final_only=False, live=False) -> list:
    """`check` over every ledger in `paths`: one `ledger: problem` line each.

    A ledger that cannot be read or parsed is a problem line, never a raise.
    """
    problems = []
    for path in paths:
        try:
            found = check(Path(root) / path, root, final_only=final_only, live=live)
        except LOAD_ERRORS as exc:
            found = [f"load: {exc}"]
        problems += [f"{ledger_label(root, path)}: {line}" for line in found]
    return problems


def check_dir(ledger_dir, root, final_only=False, live=False) -> list:
    """`check_files` over every `*.jsonl` in `ledger_dir`, in name order."""
    return check_files(sorted(Path(ledger_dir).glob("*.jsonl")), root, final_only, live)


def seal(root, ledger_paths) -> list:
    """Write `final_blob` and `peer_blobs` into every ledger; return the problems.

    `final_blob` is `git hash-object -w <final>`. `peer_blobs` maps each *other*
    distinct `final` named on the same call to its blob, so a kept needle may
    live in any destination of the swap. Nothing is written when any ledger is
    unreadable or any destination cannot be hashed. Rows are left byte-for-byte.
    """
    docs, problems = [], []
    for path in ledger_paths:
        try:
            docs.append((Path(root) / path, load(Path(root) / path)))
        except LOAD_ERRORS as exc:
            problems.append(f"{ledger_label(root, path)}: seal: {exc}")
    blobs: dict = {}
    for _, doc in docs:
        rel = doc["header"].get("final")
        if rel in blobs:
            continue
        blobs[rel] = git_blob(root, rel, write=True) if _is_file(root, rel) else ""
        if not blobs[rel]:
            problems.append(f"seal: destination {rel!r} is not a file git can hash")
    if problems:
        return problems
    for path, doc in docs:
        header = doc["header"]
        header["final_blob"] = blobs[header["final"]]
        header["peer_blobs"] = {rel: blob for rel, blob in blobs.items() if rel != header["final"]}
        lines = path.read_text(encoding="utf-8").splitlines()
        first = next(i for i, line in enumerate(lines) if line.strip())
        lines[first] = json.dumps(header, ensure_ascii=False)
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return []


def _tiling_problems(src, spans, total) -> list:
    """Gap / overlap / overrun lines for sorted (lo, hi, ledger) spans of `src`."""
    problems, expect = [], 1  # `expect` is the first line not yet covered
    for lo, hi, name in spans:
        if lo < 1 or hi < lo:
            problems.append(f"coverage: {name} names the bad range {lo}-{hi}")
        elif lo > expect:
            problems.append(f"coverage: gap: lines {expect}-{lo - 1} of {src} are in no ledger")
        elif lo < expect:
            problems.append(f"coverage: overlap: lines {lo}-{min(hi, expect - 1)} of {src} "
                            f"are in more than one range ({name})")
        expect = max(expect, hi + 1)
    if expect <= total:
        problems.append(f"coverage: gap: lines {expect}-{total} of {src} are in no ledger")
    elif expect > total + 1:
        problems.append(f"coverage: lines {total + 1}-{expect - 1} run past the end of "
                        f"{src} ({total} lines)")
    return problems


def coverage(root, ledger_paths) -> list:
    """Problems unless the ledgers' ranges cover each source's lines exactly once.

    Ledgers are grouped by `source`; the line count is that of the `source_blob`
    the ranges were cut from (the live file when the blob is unreachable).
    """
    problems, by_source = [], {}
    for path in ledger_paths:
        try:
            header = load(Path(root) / path)["header"]
            by_source.setdefault(header["source"], []).append((ledger_label(root, path), header))
        except LOAD_ERRORS as exc:
            problems.append(f"{ledger_label(root, path)}: coverage: {exc}")
    for src, entries in by_source.items():
        blobs = sorted({str(header["source_blob"]) for _, header in entries})
        if len(blobs) > 1:
            problems.append(f"coverage: {src} is cut from different source_blobs: {', '.join(blobs)}")
            continue
        text = _blob_text(root, blobs[0]) if _reachable(root, blobs[0]) else _read(root, src)
        try:
            spans = sorted((int(lo), int(hi), name) for name, header in entries
                           for lo, hi in header.get("ranges") or [])
        except LOAD_ERRORS as exc:
            problems.append(f"coverage: {src} has an unreadable ranges field: {exc}")
            continue
        problems += _tiling_problems(src, spans, len(text.splitlines()))
    return problems
