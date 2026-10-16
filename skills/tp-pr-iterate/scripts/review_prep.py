"""review_prep — cheap-tier review prep: work dir, facts, drafts, cache, suffix, shape.

design: cheap-tier-review-prep (Phase 3; Task 3.1 — constants, facts, paths,
suffix, shape; Task 3.2 — the per-head cache, D3; Task 3.3 — `move_work` and
`render`). Stdlib only.

`W` is a prep work dir (a `prep-work/next` under the PR's rounds dir), `R` a
round dir. Facts payloads carry only what a drafter needs — never session
context (detailed-design-prep Phase 3); `rule` is the one-line output contract
(the Phase 2 artifact keys, by slot).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import angles as angles_mod  # noqa: E402 — first: it puts skills/_shared on sys.path

SLICER_VERSION = 1
PREP_BUDGET_SEC = 300
PREP_LINE = ("Labelled cheap-tier prep (may be incomplete; the full diff is "
             "authoritative): {path}")
WORK, CACHE = "prep-work", "prep-cache"

_PR_RE = re.compile(r"/pull/(\d+)")

# One-line output contract per slot (Phase 2 artifact keys) — the `rule` key.
_RULES = {
    "review_slice": ("Write draft.json with {\"hunks\": [{\"file\", \"hunk\"}]} "
                     "- each hunk a verbatim, newline-terminated slice of the "
                     "diff (its @@ line through the line before the next @@ or "
                     "diff --git line)."),
    "review_refs": ("Write draft.json with {\"refs\": [{\"path\", \"line\", "
                    "\"note\"}]} - path relative to the repo root, line within "
                    "the file at head, note at most 200 chars."),
    "ci_log_triage": ("Write draft.json with {\"quote\", \"step\"} - quote a "
                      "verbatim, non-empty substring of the log (at most 4000 "
                      "chars) naming the failure, step a non-empty substring "
                      "of the log naming the step."),
    "repro_scaffold": ("Write draft.json with {\"source\", \"test_name\"} - "
                       "source a self-contained pytest module that fails on "
                       "head by an assertion in a test named test_name."),
}


def _pr_number(pr_url: str) -> str:
    m = _PR_RE.search(str(pr_url))
    if not m:
        raise ValueError(f"not a PR url: {pr_url!r}")
    return m.group(1)


def _meta(work) -> dict:
    return json.loads((Path(work) / "meta.json").read_text(encoding="utf-8"))


def work_dir(proof_root, pr_url) -> Path:
    """`rounds/<pr>/prep-work/next` under the proof root (round_scratch's `<pr>`)."""
    return Path(proof_root) / "rounds" / _pr_number(pr_url) / WORK / "next"


def draft_path(work, slot, unit) -> Path:
    """`W/<slot>/<unit>/draft.json` — the drafter's only writable path."""
    return Path(work) / str(slot) / str(unit) / "draft.json"


def facts(slot, work, unit, *, finding=None) -> dict:
    """The drafter payload for one unit — exactly that slot's design keys.

    `unit` is the angle name, `"_"`, or a check/finding key. `review_slice`
    reads `angle`/`angle_prompt` from `W/meta.json` `angles` and refuses a
    skipped angle; `repro_scaffold` carries the target `finding` as given.
    """
    if slot not in _RULES:
        raise ValueError(f"unknown prep slot: {slot!r}")
    work = Path(work)
    out_path = str(draft_path(work, slot, unit))
    if slot == "review_slice":
        name = str(unit)
        try:
            entry = next(a for a in _meta(work).get("angles") or ()
                         if a.get("name") == name)
        except StopIteration as exc:
            raise ValueError(
                f"review_slice unit {name!r} not in W/meta.json angles") from exc
        if entry.get("skipped"):
            raise ValueError(f"review_slice unit {name!r} is skipped in W/meta.json")
        return {"slot": slot, "angle": name, "angle_prompt": entry.get("prompt"),
                "diff_path": str(work / "diff.patch"), "out_path": out_path,
                "rule": _RULES[slot]}
    if slot == "review_refs":
        return {"slot": slot, "diff_path": str(work / "diff.patch"),
                "root": _meta(work).get("repo", "."), "out_path": out_path,
                "rule": _RULES[slot]}
    if slot == "ci_log_triage":
        return {"slot": slot, "check": str(unit),
                "log_path": str(work / "ci" / f"{unit}.log"),
                "out_path": out_path, "rule": _RULES[slot]}
    return {"slot": slot, "finding": finding,
            "diff_path": str(work / "diff.patch"), "head": _meta(work).get("head"),
            "out_path": out_path, "rule": _RULES[slot]}


def ctx_for(slot, work, *, unit, root, scratch=None) -> dict:
    """The oracle ctx for one unit (Phase 2 keys), per slot."""
    if slot not in _RULES:
        raise ValueError(f"unknown prep slot: {slot!r}")
    work = Path(work)
    if slot == "review_slice":
        return {"diff_path": str(work / "diff.patch")}
    if slot == "review_refs":
        return {"root": root}
    if slot == "ci_log_triage":
        return {"log_path": str(work / "ci" / f"{unit}.log")}
    if scratch is None:
        raise ValueError("repro_scaffold ctx needs a scratch worktree")
    return {"cwd": root, "head": _meta(work).get("head"), "scratch_dir": str(scratch)}


def prompt_suffix(path) -> str:
    """`""` when no prep file; else the labelled prep line, after a blank line."""
    return "" if path is None else "\n\n" + PREP_LINE.format(path=path)


def _changed_lines(diff_text: str) -> int:
    """Counted changed lines: `+`/`-` lines excluding the `+++`/`---` headers."""
    n = 0
    for line in str(diff_text).splitlines():
        if line.startswith(("+++", "---", "diff ")):
            continue
        if line[:1] in "+-":
            n += 1
    return n


def diff_bucket(diff_text) -> str:
    """xs <= 50, s <= 300, m <= 1500 changed lines, else l."""
    n = _changed_lines(diff_text)
    if n <= 50:
        return "xs"
    if n <= 300:
        return "s"
    if n <= 1500:
        return "m"
    return "l"


def shape(manifest, diff_text) -> str:
    """`",".join(sorted digest_labels names)` + `"|" + bucket` — order independent."""
    names = sorted(label for label, _count in angles_mod.digest_labels(manifest, {}))
    return ",".join(names) + "|" + diff_bucket(diff_text)


# --- the per-head cache (D3; Task 3.2) -------------------------------------------

# A cache key: <base>-<head>-<slot>-<unit>-v<N>.json. Base and head are git
# SHAs (lowercase hex, no "-"); slot one of the four prep slots (no "-"); unit
# is the remainder and MAY contain "-".
_KEY_RE = re.compile(
    r"^(?P<base>[0-9a-f]+)-(?P<head>[0-9a-f]+)"
    r"-(?P<slot>review_slice|review_refs|ci_log_triage|repro_scaffold)"
    r"-(?P<unit>.+)-v(?P<version>\d+)\.json$")


def cache_key(base, head, slot, unit) -> str:
    """`<base>-<head>-<slot>-<unit>-v<SLICER_VERSION>.json` (D3)."""
    return f"{base}-{head}-{slot}-{unit}-v{SLICER_VERSION}.json"


def _parsed_key(key) -> dict:
    """The fields a cache key names, or None (the unit keeps any "-")."""
    m = _KEY_RE.match(str(key))
    if not m:
        return None
    fields = m.groupdict()
    fields["version"] = int(fields["version"])
    return fields


def cache_put(cache_dir, key, artifact) -> None:
    """Store `artifact` unchanged under `key`, atomically (temp + os.replace).

    `cache_put` sees only the key, so it recovers base/head/slot/unit/version by
    parsing it; a key that does not parse is a ValueError.
    """
    fields = _parsed_key(key)
    if fields is None:
        raise ValueError(f"not a cache key: {key!r}")
    entry = {"slot": fields["slot"], "unit": fields["unit"],
             "base": fields["base"], "head": fields["head"],
             "version": fields["version"], "artifact": artifact}
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (str(key) + ".tmp")
    tmp.write_text(json.dumps(entry), encoding="utf-8")
    os.replace(str(tmp), str(cache_dir / key))


def _recheck_ok(recheck, artifact) -> bool:
    """True only for a `cheap_oracle.Verdict` dict whose "ok" is truthy.

    A non-dict verdict, a falsy "ok", or a recheck that raises is a failed
    recheck (design: read `verdict["ok"]`).
    """
    try:
        verdict = recheck(artifact)
    except Exception:  # noqa: BLE001 — a raising recheck is a failed recheck
        return False
    return isinstance(verdict, dict) and bool(verdict.get("ok"))


def cache_get(cache_dir, key, recheck) -> dict | None:
    """The stored artifact when re-verified; None (unlinking) when not (D3).

    A hit requires: the entry file parses as a dict; its stored slot/unit/
    base/head equal the key's parsed fields; its version == SLICER_VERSION;
    and `recheck(artifact)` is ok. Any failure unlinks the file (if present)
    and returns None. The stored artifact is never modified.
    """
    fields = _parsed_key(key)
    cache_dir = Path(cache_dir)
    path = cache_dir / str(key)
    if fields is None:
        path.unlink(missing_ok=True)
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return None
    if (not isinstance(entry, dict)
            or entry.get("slot") != fields["slot"]
            or entry.get("unit") != fields["unit"]
            or entry.get("base") != fields["base"]
            or entry.get("head") != fields["head"]
            or entry.get("version") != SLICER_VERSION
            or not _recheck_ok(recheck, entry.get("artifact"))):
        path.unlink(missing_ok=True)
        return None
    return entry["artifact"]


def cache_prune(cache_dir, head) -> int:
    """Drop every entry for another head (and any unparseable one); return the count.

    Entries for `head` are kept. A missing cache dir is 0.
    """
    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return 0
    dropped = 0
    for path in sorted(cache_dir.glob("*.json")):
        entry = None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                entry = loaded
        except (OSError, ValueError):
            entry = None
        if entry is None or entry.get("head") != head:
            try:
                path.unlink()
                dropped += 1
            except OSError:
                pass
    return dropped


# --- move_work and render (Task 3.3) ---------------------------------------------

HEADING = ("# Cheap-tier prep for {angle} (labelled; may be incomplete; the full "
           "diff is authoritative)")
# slot -> {artifact key: {item field: type}} for the accepted drafts render reads.
_SHAPES = {"review_slice": ("hunks", {"file": str, "hunk": str}),
           "review_refs": ("refs", {"path": str, "line": int, "note": str}),
           "ci_log_triage": (None, {"quote": str, "step": str})}


def move_work(prep_dir, round_dir) -> Path:
    """Move W to `R/prep/work` with `os.replace`; return that path."""
    dest = Path(round_dir) / "prep" / "work"
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(prep_dir), str(dest))
    return dest


def _fence(text, info="") -> str:
    """A fenced block whose fence outruns every backtick run inside `text`."""
    runs = [len(r) for r in re.findall(r"`+", text)]
    ticks = "`" * max(3, max(runs, default=0) + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{ticks}{info}\n{body}{ticks}\n"


def _flat(text) -> str:
    return " ".join(str(text).split())


def _typed(name, art, fields) -> None:
    for key, kind in fields.items():
        val = art.get(key)
        if not isinstance(val, kind) or isinstance(val, bool):
            raise ValueError(f"{name}: {key!r} is not a {kind.__name__}")


def _load_accepted(adir: Path):
    """`(slices {angle: hunks}, refs, ci [(check, draft)])` from `W/accepted/`.

    A slot render does not use is skipped unread; a malformed draft is a
    ValueError (json errors are), an unreadable one an OSError.
    """
    slices, refs, ci = {}, [], []
    for path in sorted(adir.glob("*.json")):
        slot, sep, unit = path.stem.partition("--")  # the FIRST `--` only
        if not sep or slot not in _SHAPES:
            continue
        art = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(art, dict):
            raise ValueError(f"{path.name}: accepted draft is not an object")
        key, fields = _SHAPES[slot]
        if key is None:
            _typed(path.name, art, fields)
            ci.append((unit, art))
            continue
        items = art.get(key)
        if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
            raise ValueError(f"{path.name}: {key!r} is not a list of objects")
        for item in items:
            _typed(path.name, item, fields)
        if slot == "review_refs":
            refs.extend(items)
        else:
            slices.setdefault(unit, []).extend(items)
    return slices, refs, sorted(ci, key=lambda c: c[0])


def render(round_dir, angles) -> dict:
    """Write `R/prep/<angle>.md` per non-skipped angle with accepted work.

    Reads `R/prep/work/accepted/`: the angle's hunks (fenced `diff`), then the
    refs (`path:line — note`) and each failed check's quote (fenced), the last
    two shared by every non-skipped angle. No file for a skipped angle or one
    with nothing accepted. Returns `{angle: path}` for the files written.
    """
    prep = Path(round_dir) / "prep"
    adir = prep / "work" / "accepted"
    if not adir.is_dir():
        return {}
    slices, refs, ci = _load_accepted(adir)
    shared = []
    if refs:
        shared.append("## Refs\n\n" + "".join(
            f"- {_flat(r['path'])}:{r['line']} — {_flat(r['note'])}\n" for r in refs))
    if ci:
        shared.append("## Failed CI checks\n\n" + "\n".join(
            f"### {_flat(unit)} (step: {_flat(art['step'])})\n\n{_fence(art['quote'])}"
            for unit, art in ci))
    out = {}
    for angle in angles:
        name = angle["name"]
        if angle.get("skipped"):
            continue
        hunks = slices.get(name) or []
        sections = list(shared)
        if hunks:
            sections.insert(0, "## Hunks\n\n" + "\n".join(
                f"File: {_flat(h['file'])}\n\n{_fence(h['hunk'], 'diff')}" for h in hunks))
        if not sections:
            continue
        path = prep / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADING.format(angle=name) + "\n\n" + "\n".join(sections),
                        encoding="utf-8")
        out[name] = path
    return out
