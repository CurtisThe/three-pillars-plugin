"""Flag a consumer-facing change to a shared protocol doc at design-learn.

`check <range>` diffs the watched paths over a commit range and reports which
``## `` sections the diff hunks touched, so design-learn can call out edits to
the commit protocol that every consumer repo sees.
"""

import argparse
import json
import re
import subprocess

# path -> the `## ` section titles whose edits count (None = the whole file).
WATCHED = {
    "skills/_shared/commit-after-work.md": (
        "The protocol",
        "Task commits: red, then green",
        "Commit message conventions",
    ),
}

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
HEADING_RE = re.compile(r"^## (.*\S)\s*$")


def _sections(path_text):
    """[(title, start, end)] for each `## ` heading; end is inclusive."""
    lines = path_text.split("\n")
    found = []
    for idx, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            found.append([m.group(1), idx + 1, len(lines)])
    for i in range(len(found) - 1):
        found[i][2] = found[i + 1][1] - 1
    return found


def _section_at(spans, line):
    for title, start, end in spans:
        if start <= line <= end:
            return title
    return spans[0][0] if spans else None


def flagged_sections(path_text, hunks, titles):
    """Section titles touched by `hunks` (list of (new_start, new_count))."""
    spans = _sections(path_text)
    if not spans or not hunks:
        return []
    if titles is None:
        return [title for title, _, _ in spans]
    wanted = set(titles)
    hit = set()
    for new_start, new_count in hunks:
        first = max(new_start, 1)
        last = first + max(new_count - 1, 0)
        for title, start, end in spans:
            if title not in wanted:
                continue
            if start <= last and first <= end:
                hit.add(title)
    return [title for title, _, _ in spans if title in hit]


def _git(root, args):
    proc = subprocess.run(["git", "-C", str(root)] + args,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return proc.stdout


def _hunks(diff_text):
    out = []
    for line in diff_text.split("\n"):
        m = HUNK_RE.match(line)
        if m:
            out.append((int(m.group(1)), int(m.group(2)) if m.group(2) else 1))
    return out


def _head_of(range_spec):
    for sep in ("...", ".."):
        if sep in range_spec:
            return range_spec.rsplit(sep, 1)[1]
    return range_spec


def check(range_spec, root="."):
    """{"flagged": bool, "hits": [{"path", "sections"}]} for a commit range."""
    head = _head_of(range_spec)
    hits = []
    for path, titles in WATCHED.items():
        diff = _git(root, ["diff", "-U0", range_spec, "--", path])
        if diff is None:
            continue
        hunks = _hunks(diff)
        if not hunks:
            continue
        text = _git(root, ["show", "%s:%s" % (head, path)])
        if text is None:
            continue
        sections = flagged_sections(text, hunks, titles)
        if sections:
            hits.append({"path": path, "sections": sections})
    return {"flagged": bool(hits), "hits": hits}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="consumer_facing_change.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check")
    chk.add_argument("--range", required=True)
    chk.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    print(json.dumps(check(args.range, root=args.root)))
    return 0


if __name__ == "__main__":
    main()
