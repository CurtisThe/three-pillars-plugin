"""proof_neutral_carry.py -- classify proof-neutral commits (proof-carry-trivial-commits).

The head-bound review proof is staled by any commit. A proof-neutral commit cannot change the
code the reviewers read, so the proof may be carried across it. This module classifies ONE
single-parent commit, and the first-parent walk strips a bounded chain of them.

A commit is proof-neutral iff EVERY changed path is one of:
  * a living-doc `.md` (`living_doc_carry.is_living_doc_carry_path`, so the `specs/` subtree and
    `project-context.md` stay out, and root `LICENSE` is out because it is not `.md`) with status
    `M` (modes 100644 -> 100644) or `A` (modes 000000 -> 100644);
  * an existing `.py` file (status `M`, one unchanged mode, 100644 or 100755) that
    `python_comment_only` accepts: same token stream once `COMMENT`/`NL` are dropped (so a
    docstring or string edit is code), both sides parse to an identical AST (`ast.dump`; the
    token stream alone misses the spaces in an f-string `{x=}` specifier), physical lines 1-2 identical (a shebang
    or coding cookie cannot move), source Python itself reads as UTF-8 (a utf-7 or `unicode_escape`
    cookie makes a "comment" decode to code) and no changed comment is a directive.
Every other status, mode, extension, path, an empty commit, a binary numstat row or an unreadable
git answer is NOT neutral. The contract is fail closed: every unknown is "not neutral".

A two-parent MERGE link (a base-sync) is also neutral when `merge_carry.merge_link` accepts it: the
second parent is on the base's first-parent history and the merge tree deviates from git's clean
merge of its parents (`git merge-tree`) only on living-doc `.md` paths (see `merge_carry.py`). It needs the walk's `base_ref`; without one
a merge stops the walk, as before. It counts as ONE link and its resolved lines count toward the cap.

`is_proof_neutral_commit` returns `(ok, reason, lines)`; `lines` is the commit's added+deleted
line count (0 when not neutral). `strip_proof_neutral_commits` walks first-parent from a head past
at most `MAX_LINKS` links (round-log, neutral or merge) and `MAX_LINES` neutral changed lines in all,
and returns the anchor it stopped at; round-log links add no lines. The walk stops early at the
first sha in `stop_at` (the reviewed heads), so a reviewed commit that is itself a doc or
round-log commit is not walked past. A caller compares the anchor against reviewed heads, so
anything over a cap or of any other shape fails closed.

stdlib-only, total, never raises, and the only subprocess it can spawn is read-only `git`
through the `run_git(args) -> (rc, out, err)` seam shared with `round_log_carry`.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from collections import Counter
from dataclasses import dataclass

MAX_LINKS = 4     # most proof-neutral commits one carry may strip (sync + renumber + log flush fits)
MAX_LINES = 200   # most changed lines across the neutral commits of one chain

_ZERO_MODE = "000000"
_REG_MODE = "100644"
_PY_MODES = ("100644", "100755")

# A comment is a directive (never neutral to add, remove or move) when it has this closed shape:
# a shebang, `# tp-...`, or a first word followed by `:`/`=` (noqa:, type:, pragma:, pylint:,
# fmt:, mypy:, isort:, pyright:, every `# tp-allow-*:` waiver). Prose such as `# Note: x` matches
# too, which fails closed. The words catch a tool tag that is not the first word, and a coding
# cookie such as `# -*- coding: x -*-`.
_DIRECTIVE_SHAPE = re.compile(r"#!|#\s*tp-|#\s*[\w.-]+\s*[:=]")
_DIRECTIVE_WORDS = ("nosec", "noqa", "type: ignore", "pragma", "coding:", "coding=", "tp-allow")


def proof_neutral_carry_enabled(config) -> bool:
    """Read `review.proof_neutral_carry` as a **default-ON** flag.

    Mirrors `living_doc_carry.carry_livingdoc_handres_enabled`: False **only on a literal
    `False`**; True on an absent key, a non-dict config or `review`, any non-bool value or any
    exception. The carry is sound on its own (classifier, caps, directive guard), so this flag
    is only the operator's opt-out. It is not nested under `approval_survives_safe_base_sync`.
    """
    try:
        review = config.get("review") if isinstance(config, dict) else None
        if not isinstance(review, dict):
            return True
        return review.get("proof_neutral_carry") is not False
    except Exception:
        return True


def _docs_class_reason(old_mode: str, new_mode: str, status: str, path: str) -> str:
    """"" when this raw entry is a neutral living-doc change, else why it is not."""
    import living_doc_carry
    if status not in ("M", "A"):
        return f"status {status} on {path}"
    if not (path.endswith(".md") and living_doc_carry.is_living_doc_carry_path(path)):
        return f"{path} is not a living-doc .md"
    if new_mode != _REG_MODE or old_mode != (_REG_MODE if status == "M" else _ZERO_MODE):
        return f"mode change on {path}"
    return ""


def _is_directive(comment: str) -> bool:
    low = comment.lower()
    return bool(_DIRECTIVE_SHAPE.match(comment)) or any(w in low for w in _DIRECTIVE_WORDS)


def _reads_as_utf8(src: str) -> bool:
    """True when Python decodes `src` as UTF-8: no cookie, `utf-8`, or a BOM (an allowlist).

    `src` is git's bytes decoded `utf-8`/`surrogateescape`, so the encode below is lossless. Any
    other cookie (utf-7, unicode_escape, latin-1, ...) means the str view is not what Python runs.
    """
    raw = src.encode("utf-8", "surrogateescape")
    return tokenize.detect_encoding(io.BytesIO(raw).readline)[0] in ("utf-8", "utf-8-sig")


def _scan(src: str) -> "tuple[list, list, list]":
    """(code tokens, comments, directive marks) of `src`; raises on a tokenize error.

    Code tokens are the `(type, string)` pairs without `COMMENT`/`NL`/`ENCODING`. A directive mark
    is `(index into the code tokens, comment)`, so a directive that moves is not the same mark.
    """
    code, comments, marks = [], [], []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comments.append(tok.string)
            if _is_directive(tok.string):
                marks.append((len(code), tok.string))
        elif tok.type not in (tokenize.NL, tokenize.ENCODING):
            code.append((tok.type, tok.string))
    return code, comments, marks


def python_comment_only(before: str, after: str) -> "tuple[bool, str]":
    """(True, "") when `after` differs from `before` only in non-directive comments.

    Requires an identical token stream AND an identical `ast.dump` (some edits, such as the
    spaces in an f-string `{x=}` specifier, change the AST but no token).

    Total: any failure, however odd, is `(False, reason)`; this never raises.
    """
    try:
        if before.split("\n")[:2] != after.split("\n")[:2]:
            return (False, "physical lines 1-2 changed")
        if not (_reads_as_utf8(before) and _reads_as_utf8(after)):
            return (False, "source encoding is not UTF-8")
        old_code, old_comments, old_marks = _scan(before)
        new_code, new_comments, new_marks = _scan(after)
        old_tree = ast.parse(before)
        new_tree = ast.parse(after)
        if old_code != new_code:
            return (False, "code tokens changed")
        if ast.dump(old_tree) != ast.dump(new_tree):
            return (False, "ast-differs")
        changed = (Counter(new_comments) - Counter(old_comments)) \
            + (Counter(old_comments) - Counter(new_comments))
        for comment in changed:
            if _is_directive(comment):
                return (False, f"directive comment changed: {comment!r}")
        if old_marks != new_marks:
            return (False, "directive comment moved")
        return (True, "")
    except Exception as exc:  # total: never raise
        return (False, f"error: {exc}")


def _python_class_reason(git, parent: str, commit: str, entry: tuple) -> str:
    """"" when this raw entry is a neutral comment-only `.py` edit, else why it is not."""
    old_mode, new_mode, status, path = entry
    if status != "M":
        return f"status {status} on {path}"
    if old_mode != new_mode or new_mode not in _PY_MODES:
        return f"mode change on {path}"
    sides = []
    for rev in (parent, commit):
        rc, out, _ = git(["cat-file", "-p", f"{rev}:{path}"])
        if rc != 0:
            return f"cannot read {path} at {rev}"
        sides.append(out)
    ok, why = python_comment_only(sides[0], sides[1])
    return "" if ok else f"{path}: {why}"


def _changed_lines(git, parent: str, commit: str, expected_rows: int) -> "tuple[int, str]":
    """(added+deleted, "") from `diff-tree --numstat`, or (0, reason) when unreadable/binary."""
    rc, out, _ = git(["diff-tree", "-r", "--no-renames", "--numstat", parent, commit])
    if rc != 0:
        return (0, "numstat failed")
    rows = [row for row in out.split("\n") if row]
    if len(rows) != expected_rows:
        return (0, "numstat does not match the raw diff")
    total = 0
    for row in rows:
        cols = row.split("\t", 2)
        if len(cols) != 3 or not (cols[0].isdigit() and cols[1].isdigit()):
            return (0, f"binary or unreadable numstat row {row!r}")
        total += int(cols[0]) + int(cols[1])
    return (total, "")


def is_proof_neutral_commit(git, parent: str, commit: str) -> "tuple[bool, str, int]":
    """(True, "", changed_lines) when `commit` over `parent` cannot change reviewed code.

    Total: any failure, however odd, is `(False, reason, 0)`; this never raises.
    """
    try:
        import round_log_carry
        rc, out, _ = git(["diff-tree", "-r", "--no-renames", "--raw", "-z", parent, commit])
        if rc != 0:
            return (False, "diff-tree failed", 0)
        entries = round_log_carry._parse_raw(out)
        if not entries:
            return (False, "empty or unparseable diff", 0)
        for entry in entries:
            if entry[3].endswith(".py"):
                why = _python_class_reason(git, parent, commit, entry)
            else:
                why = _docs_class_reason(*entry)
            if why:
                return (False, why, 0)
        lines, why = _changed_lines(git, parent, commit, len(entries))
        if why:
            return (False, why, 0)
        return (True, "", lines)
    except Exception as exc:  # total: never raise
        return (False, f"error: {exc}", 0)


@dataclass(frozen=True)
class NeutralStripResult:
    anchor: "str | None" = None   # sha the walk stopped at; None = could not resolve (fail closed)
    links: int = 0                # round-log and neutral commits stripped
    neutral_links: int = 0        # of those, the proof-neutral (non-round-log) ones
    lines: int = 0                # changed lines summed over the neutral links only
    reason: str = ""              # why the walk stopped (or why it could not start)


def strip_proof_neutral_commits(repo_root, head: str, *, max_links: int = MAX_LINKS,
                                max_lines: int = MAX_LINES, run_git=None,
                                stop_at=frozenset(), base_ref=None) -> NeutralStripResult:
    """Walk first-parent from `head` past round-log and neutral commits within both caps.

    Stops at the first commit whose sha is in `stop_at` (reviewed heads): every commit above it
    is already stripped, so the anchor is exactly the reviewed one. `base_ref` (a branch name, or
    a zero-arg callable returning one, resolved only when the walk meets a merge) lets a base-sync
    merge be a neutral link; without it every merge stops the walk.

    Total: never raises; an unresolvable head or any error gives `anchor=None`.
    """
    try:
        import merge_carry
        import round_log_carry
        git = run_git or round_log_carry._make_default_git(repo_root)
        cur = head
        links = neutral_links = lines = 0
        while True:
            rc, out, _ = git(["rev-list", "--parents", "-n1", cur])
            fields = out.split()
            if rc != 0 or not fields:
                if links == 0:
                    return NeutralStripResult(None, 0, 0, 0, f"cannot resolve {head}")
                return NeutralStripResult(cur, links, neutral_links, lines,
                                          f"cannot resolve parents of {cur}")
            cur = fields[0]
            if links and cur in stop_at:
                return NeutralStripResult(cur, links, neutral_links, lines, "reached a reviewed head")
            if len(fields) == 1:
                return NeutralStripResult(cur, links, neutral_links, lines, "root commit")
            parent = fields[1]
            added, is_neutral = 0, True
            if len(fields) > 2:
                ok, why, added = merge_carry.merge_link(git, cur, fields[1:], base_ref=base_ref)
            else:
                ok, why = round_log_carry.is_round_log_commit(git, parent, cur)
                if not ok:
                    ok, why, added = is_proof_neutral_commit(git, parent, cur)
                else:
                    is_neutral = False
            if not ok:
                return NeutralStripResult(cur, links, neutral_links, lines, why)
            if links >= max_links:
                return NeutralStripResult(cur, links, neutral_links, lines,
                                          f"chain exceeds the cap of {max_links} links")
            if lines + added > max_lines:
                return NeutralStripResult(cur, links, neutral_links, lines,
                                          f"changed lines exceed the cap of {max_lines}")
            links += 1
            neutral_links += is_neutral
            lines += added
            cur = parent
    except Exception as exc:  # total: never raise
        return NeutralStripResult(None, 0, 0, 0, f"error: {exc}")
