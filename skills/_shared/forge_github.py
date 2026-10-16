#!/usr/bin/env python3
"""forge_github.py — the GitHub backend, on exactly the paths used today.

design: forge-interface (Task 1.2)

Thin wrappers only. `pr_create` builds NO argv: it hands `gh_args`, `config`,
`context` and its three seams straight to `github_pr_author.create_pr`, so the
existing PR-author chokepoint stays the only place `gh pr create` argv and the
bot-token child env are built (its `BotAuthUnavailable` therefore propagates —
a configured-but-unavailable bot is fail-loud, never a silent ambient fallback).
The read / comment / label ops use the same `gh api` REST shapes today's callers
use (`cert_comment`, `review_merge`, `label_manager`) — REST rather than
`gh pr comment` / `gh pr edit`, which is the classic-Projects workaround those
callers already depend on. Labels are URL-encoded because `tp:` labels carry a
colon. Every op returns a forge `Result`: rc 0 → `ok` with a parsed payload; a
non-zero rc → `degraded` carrying the first stderr line; a missing `gh` →
`degraded` naming `install gh`; unparsable JSON → `degraded` with one line.
Seams: `runner` (argv list -> CompletedProcess-like) and, for create, `env` and
`token_runner`, both passed through to the chokepoint. The four comment / label writes
default `config=DISCOVER` and run through `automation_identity.run_gh_write`, so they post as
the configured bot (design: review-proof-ambient-gh-identity); an explicit `config=None` is the
ambient one-argument `runner(argv)` call, and the reads never fetch a token. Stdlib only.
"""
from __future__ import annotations

import json
import subprocess
from urllib.parse import quote

import automation_identity
from automation_identity import DISCOVER
from forge import ForgeInfo, Result
import github_pr_author

# The one line every "no gh on this machine" degrade carries.
NO_GH_LINE = "gh not found — install gh (https://cli.github.com)"

# The fields pr_read asks gh for, in the order the payload maps them.
_PR_VIEW_JSON = "number,headRefName,headRefOid,state,url"


def _default_runner(argv, env=None):
    """The default `runner` seam: argv list -> CompletedProcess (text output).

    `env` reaches `subprocess.run` only when given, so the unconfigured call is unchanged.
    """
    extra = {} if env is None else {"env": env}
    return subprocess.run(argv, capture_output=True, text=True, **extra)


def _first_line(text: str) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def _fail_line(argv, proc) -> str:
    """One actionable line for a failed `gh`: first stderr line, or the argv."""
    return _first_line(proc.stderr) or f"{' '.join(argv[:3])} failed (exit {proc.returncode})"


def _call(argv, run):
    """`(proc, None)` when `gh` answered, `(None, Result)` for either failure."""
    try:
        proc = run(argv)
    except FileNotFoundError:
        return None, Result.degraded(NO_GH_LINE)
    if proc.returncode != 0:
        return None, Result.degraded(_fail_line(argv, proc))
    return proc, None


def _write(argv, runner, config, env, token_runner):
    """`_call` for a write: `gh` runs as the configured automation account.

    `BotAuthUnavailable` propagates (fail loud, `runner` never called). With no account the
    runner sees exactly `runner(argv)` — a caller `env` is passed through, none is added.
    """
    def run(call_argv):
        return automation_identity.run_gh_write(
            call_argv, config=config, runner=runner or _default_runner, env=env,
            token_runner=token_runner)
    return _call(argv, run)


def _payload(proc, what: str) -> Result:
    """Parse `gh`'s JSON stdout, or degrade with one line."""
    try:
        loaded = json.loads(proc.stdout or "")
    except ValueError:
        return Result.degraded(f"could not parse {what} output from gh")
    return Result.ok(loaded) if isinstance(loaded, dict) else Result.degraded(
        f"unexpected {what} output from gh")


def pr_create(info: ForgeInfo, gh_args, config: dict, context: str, *, runner=None,
              env=None, token_runner=None) -> Result:
    """`gh pr create` through the PR-author chokepoint — no argv built here."""
    try:
        rc = github_pr_author.create_pr(gh_args, config, context, runner=runner,
                                        env=env, token_runner=token_runner)
    except FileNotFoundError:
        return Result.degraded(NO_GH_LINE)
    if rc != 0:
        return Result.degraded(f"gh pr create failed (exit {rc})")
    return Result.ok({"returncode": 0})


def pr_read(info: ForgeInfo, number, *, runner=None) -> Result:
    """`gh pr view <n> --json …` -> `{number, head, head_sha, state, url}`.

    `head` is the branch name (`headRefName`); `head_sha` is the head commit (`headRefOid`).
    """
    run = runner or _default_runner
    argv = ["gh", "pr", "view", str(number), "--json", _PR_VIEW_JSON]
    proc, bad = _call(argv, run)
    if bad is not None:
        return bad
    result = _payload(proc, "gh pr view")
    if result.status != "ok":
        return result
    data = result.payload
    return Result.ok({"number": data.get("number"), "head": data.get("headRefName"),
                      "head_sha": data.get("headRefOid"),
                      "state": data.get("state"), "url": data.get("url")})


def comment_post(info: ForgeInfo, number, body: str, *, runner=None, config=DISCOVER,
                 env=None, token_runner=None) -> Result:
    """POST the REST issue-comments endpoint -> `{id, url}`, as the configured bot."""
    argv = ["gh", "api", f"repos/{info.owner}/{info.repo}/issues/{number}/comments",
            "-f", f"body={body}"]
    proc, bad = _write(argv, runner, config, env, token_runner)
    if bad is not None:
        return bad
    result = _payload(proc, "gh api comments")
    if result.status != "ok":
        return result
    data = result.payload
    return Result.ok({"id": data.get("id"), "url": data.get("html_url")})


def _json_pages(text: str):
    """Every JSON value in `text`, in order (`gh --paginate` may print one per page)."""
    decoder, pos, values = json.JSONDecoder(), 0, []
    text = text or ""
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return values
        value, pos = decoder.raw_decode(text, pos)
        values.append(value)


def comment_list(info: ForgeInfo, number, *, runner=None) -> Result:
    """`gh api --paginate` the issue comments -> `{"comments": [{id, body}]}`."""
    run = runner or _default_runner
    argv = ["gh", "api", "--paginate",
            f"repos/{info.owner}/{info.repo}/issues/{number}/comments"]
    proc, bad = _call(argv, run)
    if bad is not None:
        return bad
    try:
        pages = _json_pages(proc.stdout)
    except ValueError:
        return Result.degraded("could not parse gh api comments output from gh")
    if not pages or not all(isinstance(page, list) for page in pages):
        return Result.degraded("unexpected gh api comments output from gh")
    return Result.ok({"comments": [
        {"id": item.get("id"), "body": item.get("body")}
        for page in pages for item in page
        if isinstance(item, dict) and item.get("id") is not None]})


def comment_edit(info: ForgeInfo, comment_id, body: str, *, runner=None, config=DISCOVER,
                 env=None, token_runner=None) -> Result:
    """PATCH `repos/{o}/{r}/issues/comments/{id}`, as the configured bot."""
    argv = ["gh", "api", "-X", "PATCH",
            f"repos/{info.owner}/{info.repo}/issues/comments/{comment_id}",
            "-f", f"body={body}"]
    proc, bad = _write(argv, runner, config, env, token_runner)
    return bad if bad is not None else Result.ok({})


def label_add(info: ForgeInfo, number, name: str, *, runner=None, config=DISCOVER,
              env=None, token_runner=None) -> Result:
    """Add `name` via the REST issues/labels endpoint (`labels[]` field), as the bot."""
    argv = ["gh", "api", f"repos/{info.owner}/{info.repo}/issues/{number}/labels",
            "-f", f"labels[]={name}"]
    proc, bad = _write(argv, runner, config, env, token_runner)
    return bad if bad is not None else Result.ok({})


def label_remove(info: ForgeInfo, number, name: str, *, runner=None, config=DISCOVER,
                 env=None, token_runner=None) -> Result:
    """DELETE `repos/{o}/{r}/issues/{n}/labels/<name>` (name URL-encoded), as the bot."""
    argv = ["gh", "api", "-X", "DELETE",
            f"repos/{info.owner}/{info.repo}/issues/{number}/labels/{quote(name, safe='')}"]
    proc, bad = _write(argv, runner, config, env, token_runner)
    return bad if bad is not None else Result.ok({})
