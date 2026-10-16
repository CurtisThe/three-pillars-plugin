"""round_freeze — freeze the review bar after a clean verdict, defer the rest.

design: review-convergence (Task 5.4, detailed-design-pr-loop §D2)

A review round with **0 blocking findings and no degraded sentinel** is the loop's
signal that the diff is understood: `mark_if_clean` stamps `frozen_at` = that
round's head into the iterate-state file (schema `iterate-state.v1.json`: string
or null). From then on the loop keeps fixing real blockers — a *new* blocking
finding still gets its fix — but stops churning on non-blocking notes:
`partition(classified, frozen)` keeps only `verdict == "structural"` items and
defers the rest with `reason = "frozen-follow-up"`. Deferred items accumulate in
`<proof_root>/rounds/<pr>/follow-up.json` (`add_follow_ups`, idempotent per
`comment_id`) and post **once** as a single PR comment at a terminal (`post`);
when the forge degrades they go to the loop log instead — `round_scratch.py flush`
moves that into `decisions.md`, where `/tp-design-learn` can turn it into a
`known_issues.md` entry (a Low into `known_issues_low.md`) — and one line is
printed. A degraded follow-up is never
silent.

The state-file half mirrors `budget_clock.stamp_round_start` exactly: a missing,
non-regular or unreadable `state_path` answers False, changes nothing and raises
nothing, because `run_round` owns the bootstrap and this must not become a second
writer (a FIFO read would otherwise hang the round).

CLI: `round_freeze.py post --pr-url U --root R` (fail-open, exit 0) and
`round_freeze.py is-frozen --state-path P` (exit 0 frozen / 1 not — the loop prose
feeds that to `fix_round.py --frozen`). Stdlib + sibling modules + `forge`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parents[1] / "_shared"
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import forge  # noqa: E402
import iterate_state  # noqa: E402
from finding_class import is_sentinel  # noqa: E402
from severity import is_blocking  # noqa: E402

FOLLOW_UP = "follow-up.json"          # <proof_root>/rounds/<pr>/follow-up.json
FROZEN_FIELD = "frozen_at"
DEFER_REASON = "frozen-follow-up"
DEGRADE_PREFIX = "follow-up: forge comment degraded ("
_PR_RE = re.compile(r"/pull/(\d+)")


# ---------- the freeze mark ----------


def _is_clean(findings) -> bool:
    """True when every finding is a real dict that does not block and is no sentinel.

    `severity.is_blocking` is the only bar (an Opus downgrade or a refuted
    reproducer clears it). A degraded sentinel means the review did not happen, so
    the round is not clean and must not freeze; a non-dict entry is neither, so it
    fails closed too.
    """
    for f in findings or ():
        if not isinstance(f, dict) or is_sentinel(f) or is_blocking(f):
            return False
    return True


def mark_if_clean(state_path, head, findings) -> bool:
    """Stamp `frozen_at` = `head` into the existing state file when nothing blocks.

    A missing file stays absent (no bootstrap: `run_round` owns that), a file that
    is not a readable JSON object is left byte-identical for `run_round` to refuse,
    and a non-regular node is never read. Returns True when the mark was written.
    """
    path = Path(state_path)
    if not path.is_file():  # missing, dangling, or non-regular (a FIFO would block a read)
        return False
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(state, dict) or not _is_clean(findings):
        return False
    state[FROZEN_FIELD] = head
    iterate_state.write_state_atomic(path, state)
    return True


def _read_state(state_path) -> dict:
    """The state object at `state_path`, or `{}` for anything unreadable."""
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def is_frozen(state) -> bool:
    """True when the state carries a non-empty `frozen_at` (absent/null/blank: not)."""
    return isinstance(state, dict) and bool(str(state.get(FROZEN_FIELD) or "").strip())


# ---------- partitioning a round's fixes ----------


def partition(classified, frozen: bool) -> tuple:
    """`(keep, defer)`: while frozen only structural fixes run; the rest are follow-ups.

    Not frozen → everything is kept, unchanged. Frozen → a `verdict ==
    "structural"` item (a real blocker, whenever it appeared) is kept; every other
    item is copied and gains `reason = "frozen-follow-up"`, the shape `fix_round`'s
    `fixes_deferred` entry carries. The input list and its dicts are never mutated.
    """
    if not frozen:
        return list(classified or ()), []
    keep, defer = [], []
    for f in classified or ():
        if isinstance(f, dict) and f.get("verdict") == "structural":
            keep.append(f)
            continue
        item = dict(f) if isinstance(f, dict) else {"summary": str(f)}
        item["reason"] = DEFER_REASON
        defer.append(item)
    return keep, defer


# ---------- the follow-up store ----------


def _store_path(rounds_pr_dir) -> Path:
    return Path(rounds_pr_dir) / FOLLOW_UP


def _stored(path: Path) -> list:
    """The stored items; a missing, corrupt or non-array file reads as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def add_follow_ups(rounds_pr_dir, items) -> int:
    """Append deferred `items` to `follow-up.json`. → how many were new.

    Idempotent per `comment_id`, so a round that is partitioned twice (a rerun, a
    resumed loop) cannot store the same note twice. An item with no `comment_id` is
    always new. Nothing is written when nothing is added.
    """
    path = _store_path(rounds_pr_dir)
    existing = _stored(path)
    seen = {e.get("comment_id") for e in existing if e.get("comment_id") is not None}
    added = 0
    for item in items or ():
        if not isinstance(item, dict):
            continue
        key = item.get("comment_id")
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        existing.append(item)
        added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return added


# ---------- posting them once ----------


def _pr_number(pr_url: str) -> str:
    """The PR number in `pr_url` ("" when it does not look like one)."""
    m = _PR_RE.search(str(pr_url))
    return m.group(1) if m else ""


def _item_loc(item: dict) -> str:
    """Where a deferred item points: its file, else its comment id."""
    return str(item.get("file") or item.get("comment_id") or "?")


def _item_text(item: dict) -> str:
    """`<file>: <summary>` — one item, one line, trailing space trimmed."""
    return f"{_item_loc(item)}: {str(item.get('summary') or '').strip()}".rstrip()


def _item_line(item: dict) -> str:
    """One item on one loop-log line: `frozen-follow-up: <file>: <summary>`."""
    return f"{DEFER_REASON}: {_item_text(item)}"


def _body(items) -> str:
    """One PR comment naming every deferred item and why it was deferred."""
    lines = [f"[{DEFER_REASON}] Non-blocking review notes deferred after the "
             "clean-round freeze (the code they name was not changed):"]
    lines += [f"- {_item_text(i)}" for i in items]
    return "\n".join(lines)


def _default_post(pr_url, body: str, *, repo: str = ".") -> forge.Result:
    """The forge chokepoint path: `forge.comment_post` on the PR's number."""
    number = _pr_number(pr_url)
    if not number:
        return forge.Result.degraded(f"not a PR url: {pr_url!r}")
    return forge.comment_post(repo, number, body)


def _attempt(pr_url, body: str, repo: str, post_fn) -> tuple:
    """`(ok, kind)` for one post: `kind` names the degrade for the log line."""
    try:
        out = post_fn(pr_url, body) if post_fn is not None else _default_post(
            pr_url, body, repo=repo)
    except Exception as exc:  # a poster that raises degrades like one that returns False
        return False, type(exc).__name__
    if isinstance(out, forge.Result):
        return out.status == "ok", (out.line or "forge")
    return bool(out), "post-failed"


def _loop_log_path(rounds_pr_dir) -> Path:
    """`<proof_root>/iterate-log.<pr>.md` — the loop log for this PR's rounds."""
    pr_dir = Path(rounds_pr_dir)
    pr = pr_dir.name if pr_dir.name.isdigit() else "loop"
    return pr_dir.parent.parent / f"iterate-log.{pr}.md"


def post(pr_url, rounds_pr_dir, *, repo: str = ".", post_fn=None) -> str:
    """Post the stored follow-ups as ONE comment at a terminal. → body, or "" degraded.

    Posted → the store is emptied, so a second terminal (or a resumed loop) posts
    nothing: the note appears exactly once. Degraded (a false/raising `post_fn`, a
    degraded forge `Result`) → the items are appended to the loop log, which
    `round_scratch.py flush` moves into `decisions.md`, and one line is printed:
    `follow-up: forge comment degraded (<kind>); N item(s) logged to decisions.md`.
    A log write that itself fails still prints the line — never silent.
    """
    path = _store_path(rounds_pr_dir)
    items = _stored(path)
    if not items:
        return ""
    body = _body(items)
    ok, kind = _attempt(pr_url, body, repo, post_fn)
    if ok:
        try:
            path.unlink()
        except OSError:
            pass
        return body
    try:
        log = _loop_log_path(rounds_pr_dir)
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            for item in items:
                fh.write(_item_line(item) + "\n")
    except OSError:
        pass  # the printed line below is the operator's remaining signal
    print(f"{DEGRADE_PREFIX}{kind}); {len(items)} item(s) logged to decisions.md)")
    try:
        path.unlink()
    except OSError:
        pass
    return ""


def main(argv=None) -> int:
    """`post --pr-url U --root R` (fail-open) | `is-frozen --state-path P` (0/1)."""
    ap = argparse.ArgumentParser(prog="round_freeze")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("post", help="post the stored follow-ups once")
    p.add_argument("--pr-url", required=True)
    p.add_argument("--root", help="proof root (default: proof_root.py's)")
    f = sub.add_parser("is-frozen", help="exit 0 when the state carries frozen_at")
    f.add_argument("--state-path", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "is-frozen":
        return 0 if is_frozen(_read_state(a.state_path)) else 1
    import proof_root
    root = Path(a.root) if a.root else Path(proof_root.default_proof_root())
    post(a.pr_url, root / "rounds" / _pr_number(a.pr_url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
