"""finder_segments — cut a large diff into segments, one Strata finder run per segment.

design: review-loop-jdi-fixes (Part 1)

A Strata finder that reads a diff above the threshold (default 600 changed lines or
10 files, `review.strata_finder_segment`) runs past its deadline and holds the single
GPU slot. `plan_segments` groups the diff so a source file stays with its tests and the
docs that cite it, packs the groups into segments under the threshold, and caps the
segments run per angle (default 4). `expand_angles` swaps each Strata finder for one
advisory finder per segment (`<angle>-s<k>`; a segment past the cap is
`skipped: "segment-budget"`). Everything downstream (put, read, mark-unparseable, the
Opus check) sees ordinary manifest entries. `merge_segment_replies` is the check's
deduped (file:line) view. Under the threshold, or off Strata, nothing changes.

CLI: `merge --round-dir R` writes `R/opus-check/segments-merged.json`. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

DEFAULTS = {"max_lines": 600, "max_files": 10, "max_segments": 4}
SKIP_BUDGET = "segment-budget"
CODE_EXT = {".py", ".sh", ".js", ".ts"}
MIN_FRACTION = 0.25  # a segment's deadline never scales below this share of the cap
MERGED = "segments-merged.json"
_FILE_RE = re.compile(r'^diff --git (?:"a/(?:[^"\\]|\\.)*"|a/.*?) (?P<b>"b/(?:[^"\\]|\\.)*"|b/.*)$')
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def settings(config) -> dict | None:
    """The segment limits from `review.strata_finder_segment`, or None when it is `false`."""
    raw = ((config or {}).get("review") or {}).get("strata_finder_segment")
    if raw is False:
        return None
    out = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in out:
            val = raw.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val >= 1:
                out[key] = val
    return out


_ESC = {"t": 9, "n": 10, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, '"': 34, "\\": 92}


def _unquote(token: str) -> str:
    """The path of a `b/...` header token; git's C-quoted form (`"b/..."`) is decoded
    (octal and letter escapes to bytes, raw characters kept) and a trailing TAB git adds
    after a path with a space is dropped."""
    token = token.rstrip("\t")
    if token.startswith('"') and token.endswith('"') and len(token) > 1:
        body, out, i = token[1:-1], bytearray(), 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                m = re.match(r"[0-7]{3}", body[i + 1:i + 4])
                if m:
                    out.append(int(m.group(), 8))
                    i += 4
                    continue
                if body[i + 1] in _ESC:
                    out.append(_ESC[body[i + 1]])
                    i += 2
                    continue
            out += c.encode("utf-8")
            i += 1
        token = out.decode("utf-8", "replace")
    return token[2:] if token[:2] in ("a/", "b/") else token


def parse_diff(text: str) -> list[dict]:
    """`[{path, lines, text, hunks: [{start, end, lines}]}]` from a unified diff."""
    files: list[dict] = []
    for line in text.splitlines():
        m = _FILE_RE.match(line)
        if m:
            files.append({"path": _unquote(m.group("b")), "lines": 0, "text": [], "hunks": []})
        if not files:
            continue
        cur = files[-1]
        cur["text"].append(line)
        if not cur["hunks"] and line[:4] in ("+++ ", "--- ") and line[4:] != "/dev/null":
            cur["path"] = _unquote(line[4:])  # the header line is ambiguous for a path with " b/"
        h = _HUNK_RE.match(line)
        if h:
            start, count = int(h.group(1)), int(h.group(2) or 1)
            cur["hunks"].append({"start": start, "end": start + max(count, 1) - 1, "lines": 0})
        elif line[:1] in ("+", "-") and cur["hunks"]:  # file headers precede the first hunk
            cur["hunks"][-1]["lines"] += 1
            cur["lines"] += 1
    for f in files:
        f["text"] = "\n".join(f["text"])
    return files


def _stem(path: str) -> str:
    name = Path(path).stem
    return name[5:] if name.startswith("test_") else name[:-5] if name.endswith("_test") else name


def _is_test(path: str) -> bool:
    name = Path(path).name
    return name.startswith("test_") or Path(path).stem.endswith("_test")


def _groups(files: list[dict]) -> list[list[dict]]:
    """Union-find: a test joins its source by stem prefix or import; a doc joins the
    source it cites by file name."""
    parent = list(range(len(files)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    sources = [(i, _stem(f["path"])) for i, f in enumerate(files)
               if not _is_test(f["path"]) and Path(f["path"]).suffix in CODE_EXT]
    for i, f in enumerate(files):
        path, body = f["path"], f["text"]
        for j, stem in sources:
            if j == i or not stem:
                continue
            base = Path(files[j]["path"]).name
            linked = False
            if Path(path).suffix == ".py":
                s = _stem(path)
                linked = (_is_test(path) and (s == stem or s.startswith(stem + "_"))) or bool(
                    re.search(rf"^[+ ]\s*(import|from)\s+{re.escape(stem)}\b", body, re.M))
            elif Path(path).suffix == ".md":
                linked = base in body or files[j]["path"] in body
            if linked:
                parent[find(i)] = find(j)
    out: dict[int, list[dict]] = {}
    for i, f in enumerate(files):
        out.setdefault(find(i), []).append(f)
    return list(out.values())


def _pieces(f: dict, max_lines: int) -> list[dict]:
    """One unit per file, or hunk-boundary pieces when the file alone is over `max_lines`."""
    if f["lines"] <= max_lines or len(f["hunks"]) < 2:
        return [{"files": [f["path"]], "lines": f["lines"], "ranges": None}]
    pieces, cur = [], None
    for h in f["hunks"]:
        if cur and cur["lines"] + h["lines"] > max_lines:
            pieces.append(cur)
            cur = None
        if cur is None:
            cur = {"files": [f["path"]], "lines": 0, "ranges": [h["start"], h["end"]]}
        cur["lines"] += h["lines"]
        cur["ranges"][1] = h["end"]
    pieces.append(cur)
    return pieces


def plan_segments(diff_text: str, cfg: dict) -> dict:
    """`{engaged, lines, files, segments: [{id, files, lines, ranges, status, fraction}]}`.

    Not engaged (one finder, whole diff) when the diff is within `max_lines` and
    `max_files`. No segment is over `max_lines` unless it is one hunk. Code-bearing
    segments come first, larger first; those past `max_segments` are `skipped`.
    """
    files = parse_diff(diff_text)
    total = sum(f["lines"] for f in files)
    out = {"engaged": False, "lines": total, "files": len(files), "segments": []}
    if total <= cfg["max_lines"] and len(files) <= cfg["max_files"]:
        return out
    units = []
    for group in _groups(files):
        size = sum(f["lines"] for f in group)
        if size <= cfg["max_lines"] and len(group) <= cfg["max_files"]:
            units.append({"files": [f["path"] for f in group], "lines": size, "ranges": None})
        else:  # over the threshold: the group falls apart into per-file units
            for f in group:
                units.extend(_pieces(f, cfg["max_lines"]))
    units.sort(key=lambda u: (not any(Path(p).suffix in CODE_EXT for p in u["files"]), -u["lines"]))
    bins: list[dict] = []
    for u in units:
        for b in bins:
            if (b["ranges"] is None and u["ranges"] is None
                    and b["lines"] + u["lines"] <= cfg["max_lines"]
                    and len(b["files"]) + len(u["files"]) <= cfg["max_files"]):
                b["files"] += u["files"]
                b["lines"] += u["lines"]
                break
        else:
            bins.append({"files": list(u["files"]), "lines": u["lines"], "ranges": u["ranges"]})
    for k, b in enumerate(bins, 1):
        b["id"] = f"s{k}"
        b["status"] = "run" if k <= cfg["max_segments"] else f"skipped ({SKIP_BUDGET})"
        b["fraction"] = round(max(MIN_FRACTION, min(1.0, b["lines"] / cfg["max_lines"])), 2)
    out.update(engaged=True, segments=bins)
    return out


def manifest_text(diff_text: str, intent: str = "") -> str:
    """The whole change in brief: the file list with changed lines, plus the intent."""
    rows = ", ".join(f"{f['path']} ({f['lines']})" for f in parse_diff(diff_text))
    return f"files: {rows}" + (f"; intent: {intent}" if intent else "")


def segment_prompt(prompt: str, seg: dict, *, n: int, base: str, head: str, whole: str) -> str:
    """The angle's prompt plus its segment: paths to diff, split ranges, the whole-change manifest."""
    where = f" (new-side lines {seg['ranges'][0]}-{seg['ranges'][1]} only)" if seg["ranges"] else ""
    return (f"{prompt}\n\nSEGMENT {seg['id']} of {n}: the diff above is too large for one pass, so "
            f"review only these files{where}: {', '.join(seg['files'])}. Run `git diff {base}...{head} "
            f"-- {' '.join(shlex.quote(p) for p in seg['files'])}`, not the whole range. The whole change, so you can name a "
            f"cross-segment concern without seeing it all: {whole}. The Opus check merges the "
            "segments and owns cross-segment judgement.")


def _is_strata_finder(a: dict) -> bool:
    return (a.get("role") == "finder" and a.get("model") == "local" and a.get("advisory")
            and not a.get("skipped"))


def expand_angles(entries: list, seg_plan: dict, *, base: str, head: str, whole: str) -> list:
    """Each Strata finder becomes one finder per segment; a plan that is not engaged,
    or a non-Strata angle, passes through unchanged."""
    if not seg_plan.get("engaged"):
        return entries
    segs, out = seg_plan["segments"], []
    for a in entries:
        if not _is_strata_finder(a):
            out.append(a)
            continue
        for seg in segs:
            meta = {"angle": a["name"], "id": seg["id"], "of": len(segs), "files": seg["files"],
                    "fraction": seg["fraction"]}
            e = {**a, "name": f"{a['name']}-{seg['id']}", "segment": meta}
            if seg["status"] == "run":
                e["prompt"] = segment_prompt(a["prompt"], seg, n=len(segs), base=base, head=head,
                                             whole=whole)
            else:
                e["skipped"] = SKIP_BUDGET
            out.append(e)
    return out


def uncovered_files(manifest: dict) -> list[str]:
    """Files in a skipped or unparseable segment: some angle's Strata finders did not see
    them (a split file counts when any one of its range segments was missed). Empty when no
    segment entry exists."""
    return sorted({p for e in manifest.get("angles") or ()
                   if e.get("segment") and (e.get("skipped") or e.get("unparseable"))
                   for p in e["segment"]["files"]})


def merge_segment_replies(manifest: dict, replies: dict) -> dict:
    """`{angle: [finding...]}` over each angle's segment replies, deduped by file:line.

    `replies` maps an entry name to its parsed finding list. A duplicate keeps the first
    finding and lists every segment that reported it under `segments`."""
    merged: dict[str, dict] = {}
    for e in manifest.get("angles") or ():
        seg = e.get("segment")
        if not seg or e.get("skipped") or e.get("unparseable"):
            continue
        by_loc = merged.setdefault(seg["angle"], {})
        for f in replies.get(e["name"]) or ():
            if not isinstance(f, dict):
                continue
            rng = f.get("line_range")
            start = rng[0] if isinstance(rng, list) and rng else f.get("line")
            key = (str(f.get("file")), start if isinstance(start, int) else None)
            hit = by_loc.setdefault(key, {**f, "segments": [], "also": []})
            if seg["id"] not in hit["segments"]:
                hit["segments"].append(seg["id"])
            summary = f.get("summary")
            if summary and summary != hit.get("summary") and summary not in hit["also"]:
                hit["also"].append(summary)
    return {angle: list(v.values()) for angle, v in merged.items()}


def whole_diff(repo, base, head) -> str:
    """`git diff base...head` text, or "" on any git failure (the plan then does not engage)."""
    try:
        r = subprocess.run(["git", "-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff",
                            "--no-textconv", f"{base}...{head}"], cwd=repo,
                           capture_output=True, text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout if r.returncode == 0 else ""


def _intent(repo, base, head) -> str:
    try:
        r = subprocess.run(["git", "log", "--no-ext-diff", "--format=%s", f"{base}..{head}"], cwd=repo,
                           capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    return "; ".join(re.sub(r"[^\x20-\x7e]", " ", s) for s in r.stdout.splitlines()[:5]) if r.returncode == 0 else ""


def apply_to_round(entries, config, *, repo, base, head) -> list:
    """The `round_scratch.prepare` hook: expand the Strata finders when the diff is over the threshold."""
    cfg = settings(config)
    if cfg is None or not any(_is_strata_finder(a) for a in entries):
        return entries
    diff = whole_diff(repo, base, head)
    seg_plan = plan_segments(diff, cfg)
    if not seg_plan["engaged"]:
        return entries
    return expand_angles(entries, seg_plan, base=base, head=head,
                         whole=manifest_text(diff, _intent(repo, base, head)))


def _cmd_merge(args) -> int:
    from review_merge import parse_codereview_result  # noqa: PLC0415 — lazy, CLI only
    rd = Path(args.round_dir)
    try:
        manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"finder_segments: cannot read manifest: {exc}", file=sys.stderr)
        return 2
    replies = {}
    for e in manifest.get("angles") or ():
        if e.get("segment") and not e.get("skipped"):
            try:
                text = (rd / e["name"] / "reply.md").read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            findings = parse_codereview_result(text)[0]
            replies[e["name"]] = findings if isinstance(findings, list) else []
    out = {"merged": merge_segment_replies(manifest, replies),
           "uncovered_files": uncovered_files(manifest)}
    dest = rd / "opus-check"
    dest.mkdir(exist_ok=True)
    (dest / MERGED).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(dest / MERGED), "uncovered": len(out["uncovered_files"])}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finder_segments")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge")
    m.add_argument("--round-dir", required=True)
    m.set_defaults(func=_cmd_merge)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
