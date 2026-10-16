"""finalizer_effects.py — injectable gh/git seams and the post-hoc check.

design: fable-first-stops (Task 1.6)

The classifier and the permission system stay the PRIMARY guard on a finalizer
reply; this module is the record check on top of them (Behavior 5, F8 MED):
after a `resolved` reply, the PR must not be merged and the current head must
still descend from the pre-stop head (a non-descendant head is a force-push).
A violation is `finalizer-violation` — the caller escalates and grants nothing.

Seams are injectable everywhere. The defaults shell out with argv lists
(never `shell=True`), `subprocess`-style, and fail open:

- `default_pr_state_fn` — `gh pr view <url> --json state,headRefOid`; returns
  `{"state", "headRefOid"}`, or `None` (unverifiable) when `gh` is missing,
  exits non-zero, or the output is not the expected JSON shape. It never
  raises. `gh` reports states as uppercase enums (`MERGED`, `OPEN`, `CLOSED`),
  so callers compare case-insensitively.
- `default_is_ancestor_fn` — `git merge-base --is-ancestor <a> <b>`; True when
  `<a>` is an ancestor of (or equal to) `<b>`, `RuntimeError` on a hard git
  error (exit 128), which `posthoc` records as unverifiable.
- `default_comment_fn` / `default_label_fn` — post the resolution note /
  diagnosis label; print ONE line and return `False` on any failure, never
  raise (fail open: the note is an honesty signal, not a gate). The label goes
  through the REST issues/labels endpoint, never `gh pr edit` (which dies on a
  classic-Projects repo before the label lands — the `label_manager` route), and
  a missing label is created on the repo and the add retried once.

Both are WRITES, so they run as the configured automation account through
`automation_identity.run_gh_write` (`config=DISCOVER` loads the repo config; an explicit
`None`/`{}` is the ambient login). A bot whose token cannot be fetched keeps the fail-open
contract: one printed line (the exception class, never the token), `False`, no write.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

_SHARED_DIR = str(Path(__file__).resolve().parent)
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)

import automation_identity  # noqa: E402

_STATE_JSON = "state,headRefOid"
_TIMEOUT = 30


def _run(argv, runner, stdin=None, who=None) -> subprocess.CompletedProcess:
    """One call through the injected `runner`. `who=(config, token_runner)` marks a WRITE: it
    runs as the configured automation account (`run_gh_write`); `None` is a plain read."""
    kw = {"input": stdin} if stdin is not None else {}
    if who is not None:
        return automation_identity.run_gh_write(
            list(argv), config=who[0], runner=runner, token_runner=who[1],
            cwd=None, capture_output=True, text=True, timeout=_TIMEOUT, **kw)
    return runner(list(argv), cwd=None, capture_output=True, text=True, timeout=_TIMEOUT, **kw)


def default_pr_state_fn(url, runner=subprocess.run) -> dict | None:
    """PR state via `gh pr view <url> --json state,headRefOid`.

    `{"state", "headRefOid"}` on success (state as `gh` reported it, e.g.
    `MERGED`); `None` when `gh` is missing, fails, or the reply is malformed —
    the caller treats `None` as unverifiable, never as a pass or a violation.
    """
    try:
        proc = _run(["gh", "pr", "view", url, "--json", _STATE_JSON], runner)
    except (OSError, ValueError) as exc:  # gh not on PATH, runner error
        print(f"finalizer-effects: gh pr view failed open ({exc.__class__.__name__})")
        return None
    if proc.returncode != 0:
        print(f"finalizer-effects: gh pr view exited {proc.returncode} (fail-open)")
        return None
    try:
        data = json.loads(proc.stdout or "")
    except ValueError:
        print("finalizer-effects: gh pr view returned non-JSON (fail-open)")
        return None
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(state, str) or not state:
        print("finalizer-effects: gh pr view missing state (fail-open)")
        return None
    return {"state": state, "headRefOid": data.get("headRefOid")}


def default_is_ancestor_fn(ancestor, descendant, runner=subprocess.run) -> bool:
    """True when `ancestor` is an ancestor of (or equal to) `descendant`.

    `RuntimeError` on a hard git error (exit 128: bad sha, no repo) so the
    caller can record an unverifiable check instead of guessing.
    """
    proc = _run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant], runner
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise RuntimeError(f"git merge-base failed ({proc.returncode}): {proc.stderr.strip()}")


def _attempt(argv, runner, what, stdin=None, who=None):
    """Run one `gh` call: `(proc, None)`, or `(None, reason)` when it could not run."""
    try:
        return _run(argv, runner, stdin, who), None
    except (OSError, ValueError, automation_identity.BotAuthUnavailable) as exc:
        return None, f"finalizer-effects: {what} failed open ({exc.__class__.__name__})"


def _effect(argv, runner, what, who=None) -> bool:
    """Run one `gh` write effect; True on success, one printed line + False on failure."""
    proc, err = _attempt(argv, runner, what, who=who)
    if err is None and proc.returncode != 0:
        err = f"finalizer-effects: {what} exited {proc.returncode} (fail-open)"
    if err:
        print(err)
        return False
    return True


def default_comment_fn(url, body, runner=subprocess.run,
                       config=automation_identity.DISCOVER, token_runner=None) -> bool:
    """Post the resolution note: `gh pr comment <url> --body <body>`, as the automation account."""
    return _effect(["gh", "pr", "comment", url, "--body", body], runner, "gh pr comment",
                   (config, token_runner))


def _pr_parts(url):
    """`https://<host>/<owner>/<repo>/pull/<n>` -> `(owner, repo, n)`, else None."""
    parts = [p for p in urlparse(str(url or "")).path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull" or not parts[3].isdigit():
        return None
    return parts[0], parts[1], parts[3]


def _label_missing(stderr) -> bool:
    """The add failed because the label does not exist (`label_manager`'s signal)."""
    s = (stderr or "").lower()
    return "not found" in s or "does not exist" in s or ("422" in s and "label" in s)


def default_label_fn(url, label, runner=subprocess.run,
                     config=automation_identity.DISCOVER, token_runner=None) -> bool:
    """Label the PR via REST `POST repos/<o>/<r>/issues/<n>/labels` (never `gh pr edit`).

    A missing label is created (`gh label create <label> --repo <o>/<r>`) and the add
    retried once. Both writes run as the automation account. Fail open: one printed line
    and `False` on any failure, never raises.
    """
    who = (config, token_runner)
    where = _pr_parts(url)
    if where is None:
        print(f"finalizer-effects: gh api add-label skipped, not a PR url (fail-open): {url!r}")
        return False
    owner, repo, number = where
    add = ["gh", "api", "--method", "POST", f"repos/{owner}/{repo}/issues/{number}/labels",
           "--input", "-"]
    body = json.dumps({"labels": [label]})
    proc, err = _attempt(add, runner, "gh api add-label", body, who)
    if err is None and proc.returncode != 0 and _label_missing(proc.stderr):
        made, err = _attempt(["gh", "label", "create", label, "--repo", f"{owner}/{repo}"],
                             runner, "gh label create", who=who)
        if err is None and made.returncode != 0:
            err = f"finalizer-effects: gh label create exited {made.returncode} (fail-open)"
        if err is None:
            proc, err = _attempt(add, runner, "gh api add-label", body, who)
    if err is None and proc.returncode != 0:
        err = f"finalizer-effects: gh api add-label exited {proc.returncode} (fail-open)"
    if err:
        print(err)
        return False
    return True


def posthoc(stop, pr_url, pr_state_fn=None, is_ancestor_fn=None) -> dict:
    """The post-hoc record check for a `resolved` finalizer reply.

    Violations (the caller escalates `finalizer-violation`, grants nothing):

    - `pr-merged`      — the PR's state is `MERGED` (compared case-insensitively;
      `gh` reports uppercase enums, so `merged`, `MERGED` and `Merged` all count);
    - `head-rewritten` — the current head no longer descends from the pre-stop
      `stop["head"]` (a force-push over the stop).

    Clean fix-forwards return `{"ok": True}`. An unverifiable check — a missing
    `head` on the stop, a seam raising, or `gh`/`git` missing — returns
    `{"ok": True, "unverified": <reason>}`: recorded, never escalated, because
    the classifier and permissions remain the primary guard.

    `pr_state_fn` takes the PR URL and returns the `default_pr_state_fn` dict
    (or `None` = unverifiable); `is_ancestor_fn(a, b)` takes
    `(pre-stop head, current head)` and returns a bool.
    """
    if not isinstance(stop, dict) or not stop.get("head"):
        return {"ok": True, "unverified": "no pre-stop head to check"}

    pr_state_fn = pr_state_fn if pr_state_fn is not None else default_pr_state_fn
    is_ancestor_fn = (
        is_ancestor_fn if is_ancestor_fn is not None else default_is_ancestor_fn
    )

    try:
        info = pr_state_fn(pr_url)
    except Exception as exc:  # seam failure is recorded, not escalated
        return {"ok": True, "unverified": f"pr-state check failed ({exc})"}
    if not isinstance(info, dict):
        return {"ok": True, "unverified": "pr-state unverifiable (gh unavailable)"}

    state = info.get("state")
    if isinstance(state, str) and state.strip().lower() == "merged":
        return {"ok": False, "violation": "pr-merged"}

    current = info.get("headRefOid")
    if not isinstance(current, str) or not current:
        return {"ok": True, "unverified": "no current head reported"}

    try:
        descended = is_ancestor_fn(stop["head"], current)
    except Exception as exc:  # git missing / bad sha: record, never escalate
        return {"ok": True, "unverified": f"ancestry check failed ({exc})"}
    if descended:
        return {"ok": True}
    return {"ok": False, "violation": "head-rewritten"}
