#!/usr/bin/env python3
"""prose_oracle.py — the prose_shape oracle for the cheap-if-wrong prose slots.

design: cheap-tier-offload (Phase 7)

The prose slots (`handoff`, `history_line`, `docs_draft`; cheap_tier.SLOTS) get a
drafter's draft built from a structured facts payload, never the session context.
check(kind, text, root=, required=, facts=) decides whether the draft is usable:

- every required heading or field prefix starts a line (the kind's defaults plus
  `required`): `handoff` needs the tp-session-save template headings, `docs_draft`
  the diff-style proposal's `**Before**` / `**After**` / `**Why**` fields, and
  `history_line` is one `- YYYY-MM-DD — <summary>` line, dated the facts `date`
  when the facts carry one;
- every backticked repo path exists under root. A span counts as a path when it
  has a `/`, no space or template character, and either its first segment exists
  under root or its last segment has a file extension (so `tp/<slug>` and
  `origin/master` are not paths); a `:12` / `::test` suffix and `.` segments
  (`./a/b`, `a/./b`) are dropped, and a span with a `..` segment is not checked;
- every `#NNN` (also `PR#NNN` and the second ref of `#N/#M`) and every commit SHA in
  the text also appears in the facts payload. A PR number counts only when the facts
  name it as one (an int, an all-digit string, or `#N` / `PR N` / `pull/N` in a
  string), never as a digit run inside another value such as the date;
- no TBD / TODO / FIXME / XXX, `[...]` or lorem ipsum anywhere, and no `<name>` /
  `{name}` template placeholder outside a code span;
- the text is within its kind's cap (CAPS: lines, non-whitespace chars).

A failed check is `drop`: the site's Opus step writes the prose as it does today.
On import this module registers `prose_shape` into cheap_oracle.ORACLES, whose
check imports it lazily on a registry miss.

The edit metric (the Phase 3 flip evidence, operator edits per draft): save_draft
stores each draft under `.handoffs/drafts/` with a sidecar whose `edit_ratio`
(edit_ratio(draft, final), difflib) is set only when an operator reviewed the
final. edit_metric averages reviewed sidecars only, so an auto-landed draft
(`/tp-design-learn --auto`, reviewed later at the PR) is never 0-edit evidence.
cheap_ab.py report shows it per slot. The prose stubs call the CLI: `prose_oracle.py
save-draft --root R --slot S --draft F [--final F] --reviewed true|false` (exit 0).
Stdlib-only.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import cheap_oracle  # noqa: E402 — in-repo, stdlib-only sibling

ORACLE = "prose_shape"
KINDS = ("handoff", "history_line", "docs_draft")
HANDOFF_HEADINGS = ("## Phase", "## Decisions", "## State", "## Next", "## Open Questions",
                    "## Carried Forward")
REQUIRED = {"handoff": HANDOFF_HEADINGS, "history_line": (),
            "docs_draft": ("**Before**", "**After**", "**Why**")}
CAPS = {"handoff": (60, 6000), "history_line": (1, 800), "docs_draft": (80, 8000)}
DRAFTS_DIR = Path(".handoffs") / "drafts"
HISTORY_RE = re.compile(r"- (\*\*)?(\d{4}-\d{2}-\d{2})(?(1)\*\*) — \S")  # date may be bold

_FENCE_RE = re.compile(r"```.*?```", re.S)
_SPAN_RE = re.compile(r"`([^`\n]+)`")
_MARKER_RE = re.compile(r"\b(?:TBD|TODO|FIXME|XXX)\b|\[(?:\.\.\.|…)\]|(?i:lorem ipsum)")
_TEMPLATE_RE = re.compile(r"<[A-Za-z][\w -]*>|\{[A-Za-z][\w-]*\}")
_NOT_PATH_CHARS = set(" \t<>{}$*?[]|\"'")
_EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")
_PR_RE = re.compile(r"(?:(?<=[Pp][Rr])|(?<![\w&#]))#(\d+)\b")
_NUM_LIST = r"#?\d+(?:\s*(?:,|/|&|\band\b)\s*#?\d+)*"
_FACT_PR_RE = re.compile(rf"#(\d+)\b|\bPRs?[\s#-]*({_NUM_LIST})\b|/pulls?/(\d+)\b", re.I)
_PR_KEY_RE = re.compile(r"prs?|pr_number|pulls?|.+_prs?", re.I)
_SHA_RE = re.compile(r"(?<![\w/.-])([0-9a-f]{7,40})(?![\w/-])")


def _path(span: str, root: Path) -> str | None:
    """The repo path a code span names, or None when it is not a path."""
    tok = span.strip()
    if (not tok or _NOT_PATH_CHARS & set(tok) or "://" in tok
            or tok.startswith(("/", "~", "-"))):
        return None
    tok = re.sub(r":\d+(?:-\d+)?$", "", tok.split("::", 1)[0]).rstrip("/")
    parts = [p for p in tok.split("/") if p != "."]  # `./a/b`, `a/./b` name `a/b`
    if len(parts) < 2 or any(p in ("", "..") for p in parts):
        return None
    if (root / parts[0]).exists() or _EXT_RE.search(parts[-1]):
        return "/".join(parts)
    return None


def _fact_prs(facts) -> set[int]:
    """The PR numbers the facts name. Anywhere (keys included), a string names
    `#N`, `PR N` / `PRs 190 and 191` / `PR-191` or `/pull(s)/N`. Under a PR-named key
    (`pr`, `prs`, `pr_number`, `pull`, `pulls`, `*_pr`, `*_prs`) an int, or a string
    listing numbers (`190, 191`), also counts. Any other int (a phase, a count) and a
    digit run inside another value, such as a date, is not one."""
    out: set[int] = set()
    stack = [(facts, False)]
    while stack:
        v, pr_key = stack.pop()
        if isinstance(v, dict):
            for k, sub in v.items():
                stack.append((k, False))
                stack.append((sub, pr_key or (isinstance(k, str)
                                              and bool(_PR_KEY_RE.fullmatch(k)))))
        elif isinstance(v, (list, tuple, set)):
            stack.extend((x, pr_key) for x in v)
        elif isinstance(v, int) and not isinstance(v, bool):
            if pr_key:
                out.add(v)
        elif isinstance(v, str):
            if pr_key and re.fullmatch(rf"\s*{_NUM_LIST}\s*", v):
                out.update(int(n) for n in re.findall(r"\d+", v))
            for m in _FACT_PR_RE.finditer(v):
                out.update(int(n) for n in re.findall(r"\d+", next(g for g in m.groups() if g)))
    return out


def _in_facts(ref: str, blob: str, prs: set[int]) -> bool:
    if ref.startswith("#"):
        return int(ref[1:]) in prs
    return ref.lower() in blob


def _refs(text: str) -> list[str]:
    refs = [f"#{m.group(1)}" for m in _PR_RE.finditer(text)]
    refs += [m.group(1) for m in _SHA_RE.finditer(text)
             if re.search(r"\d", m.group(1)) and re.search(r"[a-f]", m.group(1))]
    return list(dict.fromkeys(refs))


def _problems(kind: str, text: str, root: Path, required, facts) -> list[str]:
    lines = text.rstrip("\n").split("\n")
    out = [f"missing {r!r}" for r in (*REQUIRED[kind], *(required or ()))
           if not any(line.lstrip().startswith(r) for line in lines)]
    if kind == "history_line":
        shape = HISTORY_RE.match(lines[0])
        want = facts.get("date") if isinstance(facts, dict) else None
        if not shape:
            out.append("history_line shape: expected '- YYYY-MM-DD — summary'")
        elif isinstance(want, str) and want.strip() and shape.group(2) != want.strip():
            out.append(f"history_line date {shape.group(2)} is not the facts date {want}")
    max_lines, max_chars = CAPS[kind]
    chars = len("".join(text.split()))
    if len(lines) > max_lines:
        out.append(f"over the {kind} cap: {len(lines)} lines > {max_lines}")
    if chars > max_chars:
        out.append(f"over the {kind} cap: {chars} non-ws chars > {max_chars}")
    out += [f"placeholder {m.group(0)!r}" for m in _MARKER_RE.finditer(text)]
    prose = _SPAN_RE.sub("", _FENCE_RE.sub("", text))
    out += [f"placeholder {m.group(0)!r}" for m in _TEMPLATE_RE.finditer(prose)]
    for span in _SPAN_RE.findall(text):
        tok = _path(span, root)
        if tok is not None and not (root / tok).exists():
            out.append(f"phantom path `{tok}`")
    blob = json.dumps(facts, sort_keys=True, default=str).lower() if facts else ""
    prs = _fact_prs(facts) if facts else set()
    out += [f"ref {ref} not in the facts" for ref in _refs(text)
            if not _in_facts(ref, blob, prs)]
    return list(dict.fromkeys(out))


def check(kind: str, text: str, *, root, required=None, facts=None) -> dict:
    """The prose_shape Verdict {ok, oracle, reason} for text as kind; reason lists
    every failure. An unknown kind raises ValueError."""
    if kind not in KINDS:
        raise ValueError(f"unknown prose kind {kind!r} (expected one of {KINDS})")
    problems = _problems(kind, str(text), Path(root), required, facts)
    return {"ok": not problems, "oracle": ORACLE, "reason": "; ".join(problems)}


@cheap_oracle.register(ORACLE)
def prose_shape(artifact: dict, ctx: dict) -> tuple[bool, str]:
    """check on the draft (artifact["text"], or the file at artifact["path"]) as kind
    ctx["kind"], with ctx["root"], ctx["facts"] and optional ctx["required"]."""
    if "text" in artifact:
        text = artifact["text"]
    else:
        text = Path(artifact["path"]).read_text(encoding="utf-8")
    v = check(ctx["kind"], text, root=ctx["root"], required=ctx.get("required"),
              facts=ctx.get("facts"))
    return v["ok"], v["reason"]


# --- the edit metric (operator-reviewed drafts only) ---------------------------------


def edit_ratio(draft: str, final: str) -> float:
    """How much of the draft the final changed: 1 - difflib's similarity, in [0, 1];
    0.0 when they are equal."""
    if draft == final:
        return 0.0
    ratio = difflib.SequenceMatcher(None, draft, final, autojunk=False).ratio()
    return min(1.0, max(0.0, 1.0 - ratio))


def save_draft(root, slot: str, draft: str, final, *, reviewed) -> Path:
    """Store the draft as <root>/.handoffs/drafts/<slot>-<sha8>.md, plus a sidecar
    <slot>-<sha8>.json {slot, draft_sha256, reviewed, edit_ratio}; returns the sidecar.

    `reviewed` is True only when an operator approved the final; `edit_ratio` is None
    unless it is. The drafts dir carries a `*` .gitignore, so nothing in it is committed.
    """
    if slot not in KINDS:
        raise ValueError(f"unknown prose slot {slot!r} (expected one of {KINDS})")
    reviewed = reviewed is True
    if reviewed and final is None:
        raise ValueError("a reviewed draft needs its final text")
    drafts = Path(root) / DRAFTS_DIR
    drafts.mkdir(parents=True, exist_ok=True)
    ignore = drafts / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()
    stem = f"{slot}-{sha[:8]}"
    (drafts / f"{stem}.md").write_text(draft, encoding="utf-8")
    side = {"slot": slot, "draft_sha256": sha, "reviewed": reviewed,
            "edit_ratio": edit_ratio(draft, final) if reviewed else None}
    path = drafts / f"{stem}.json"
    path.write_text(json.dumps(side, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sidecars(root):
    """Each parseable sidecar under root's drafts dir and every design's."""
    root = Path(root)
    for pattern in (f"{DRAFTS_DIR.as_posix()}/*.json",
                    f"three-pillars-docs/*/*/{DRAFTS_DIR.as_posix()}/*.json"):
        for path in sorted(root.glob(pattern)):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                yield data


def edit_metric(root, slot: str | None = None) -> dict:
    """{n, mean, unreviewed}: the mean edit_ratio over reviewed sidecars only (n of
    them), optionally for one slot. An unreviewed draft (`--auto`, reviewed at the PR)
    only counts in `unreviewed`: it is never 0-edit evidence."""
    ratios, unreviewed = [], 0
    for data in _sidecars(root):
        if slot is not None and data.get("slot") != slot:
            continue
        ratio = data.get("edit_ratio")
        if data.get("reviewed") is True and isinstance(ratio, (int, float)) \
                and not isinstance(ratio, bool):
            ratios.append(float(ratio))
        else:
            unreviewed += 1
    mean = sum(ratios) / len(ratios) if ratios else None
    return {"n": len(ratios), "mean": mean, "unreviewed": unreviewed}


def main(argv=None) -> int:
    """CLI for the prose stubs: `save-draft`. Exits 0 on every path, like the record step."""
    parser = argparse.ArgumentParser(prog="prose_oracle.py",
                                     description="Store a cheap-tier prose draft.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sd = sub.add_parser("save-draft", help="store a draft and its edit sidecar")
    sd.add_argument("--root", required=True,
                    help="the dir that holds .handoffs/ (a design dir, or the repo root)")
    sd.add_argument("--slot", required=True, choices=KINDS)
    sd.add_argument("--draft", required=True, help="the drafter's file")
    sd.add_argument("--final", help="a file holding the final text (needed when reviewed)")
    sd.add_argument("--reviewed", required=True, choices=("true", "false"))
    args = parser.parse_args(argv)
    try:
        draft = Path(args.draft).read_text(encoding="utf-8")
        final = Path(args.final).read_text(encoding="utf-8") if args.final else None
        path = save_draft(args.root, args.slot, draft, final, reviewed=args.reviewed == "true")
    except (OSError, ValueError) as exc:
        print(f"save-draft: {exc}", file=sys.stderr)
        return 0
    print(json.dumps({"sidecar": str(path)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
