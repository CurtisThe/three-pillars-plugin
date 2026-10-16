"""explainer/explain_deliver.py — write the brief file and post-or-edit the forge comment.

Public API (every function takes the repo `root` first; there is no cwd default):
    PR_BRIEF_KIND                        "pr-brief", the kind `write_brief` writes
    write_brief(root, slug, env, *, evidence_head, drafter=None, check_outcome=None) -> Path
    write_artifacts(root, slug, env, *, evidence_head, drafter=None, check_outcome=None) -> str
    brief_path(root, slug) -> Path           where `brief.md` is (see below)
    envelope_path(root, slug) -> Path        where the stored `pr-brief` envelope JSON is
    post_or_edit(root, slug, pr, body, *, kind, context, forge_mod=forge) -> forge.Result
    refresh_needed(root, slug, pr, *, forge_mod=forge) -> bool
    degrade_line(root, slug, kind, reason) -> str

`brief_path` resolves the design dir through `explain_sources.design_dir` (live `tp-designs`
first, then `completed-tp-designs`), so `post` and `headline` still find the brief after
`/tp-design-complete` archives the design. With neither dir present it is the `tp-designs`
path, where `brief` writes first.

`write_brief` writes three files and never commits (the caller decides when the brief is
committed):
    <root>/three-pillars-docs/tp-designs/<slug>/brief.md        the forge comment body: the
        `pr-brief` marker first, the markdown render stamped `Briefed head: <sha>`, then one
        line naming the drafter and the Opus check outcome;
    <state>/<slug>/pr-brief.html                                 the offline HTML page;
    <state>/<slug>/pr-brief.envelope.json                        the envelope as given.
`<state>` is `explain_state.state_root(root)`. The drafter and the check outcome come from
the `drafter` / `check_outcome` arguments, else from the envelope's own keys of those names,
else read "unknown". The HTML path is stored in the `pr-brief` delivery entry. `slug` must be
one path component, else ValueError, and nothing is written.

`write_artifacts` is the refresh half of `write_brief`: it writes the HTML page and the
envelope JSON (and stores the HTML path) and returns the comment body, but leaves `brief.md`
alone, so a refresh edits the posted comment and moves nothing in the tree. `write_brief` is
`write_artifacts` plus writing that body to `brief.md`.

`post_or_edit` puts `body` on PR `pr` and returns the forge `Result`. It looks the comment up
in this order and reads and writes only `explain_state.delivery(root, slug, kind)`:
    1. the stored `comment_id`: edit it;
    2. the marker: `forge_mod.comment_list` and the first comment whose body parses
       (`explainer_marker.parse`) to the same `kind` and `slug`, whatever its `head`, so a
       refresh after a head change edits the old comment and does not post a second;
    3. neither: post a new comment.
On success it stores `comment_id` and, when `body` starts with a marker, `posted_head` in that
kind's entry (the CLI's first `post` then overwrites it with the PR head commit from `pr_read`).
A stored id that will not edit (the comment is gone) falls through to the marker
lookup. A failed listing returns its degraded `Result` and posts nothing, so a forge that
cannot list never gets a duplicate. A failed edit or post returns its degraded `Result` and
stores nothing. `kind` must be a delivery kind, else ValueError before any forge call.
`forge_mod` is the forge module (injectable); its `comment_list` / `comment_edit` /
`comment_post` take the repo root first.

Authorship (GitHub): `forge` owns the write identity. Its comment writes run as the
configured automation account (`automation_identity.run_gh_write`, one token fetch per
write, `GH_TOKEN` only in the child env), so `post_or_edit` passes no runner and builds no
token. `context` is accepted for the callers' sake and does not change the write. A bot
that cannot be honored (`BotAuthUnavailable`) prints one degrade line and returns a degraded
`Result` with nothing posted: a write never falls back to the ambient login. Gitea uses
its own token path; a Gitea without a token returns a degraded `Result`.

Degrade: `post_or_edit` returns a forge degrade as a `Result` and records nothing for it, so
the caller reports it with `degrade_line(root, slug, kind, result.line)`: one line
`explainer: <reason> — see <path>` on stderr (stdout stays clean for the CLI's JSON), the
reason stored once in the kind's `delivery.degraded`, the line returned. `<path>` is
`brief.md` for the `pr-brief` kind and the stored HTML page (else `brief.md`) for the rest.
A reason is collapsed to one line. A refresh only reads the forge and edits a comment;
nothing here runs `git commit`.

`refresh_needed` is True when the `pr-brief` entry has no `posted_head` (nothing is posted),
when `forge_mod.pr_read(root, pr)` degrades (one degrade line; staleness cannot be shown, so
regenerate), or when the PR head commit it reports (`head_sha`; `head` is the branch name)
differs from `posted_head`; else False.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import automation_identity  # noqa: E402
import explain_html  # noqa: E402
import explain_markdown  # noqa: E402
import explain_sources  # noqa: E402
import explain_state  # noqa: E402
import explainer_marker  # noqa: E402
import forge  # noqa: E402

PR_BRIEF_KIND = "pr-brief"
_DESIGN_DIR = ("three-pillars-docs", "tp-designs")
_UNKNOWN = "unknown"


def _design_dir(root, slug) -> Path:
    """The design dir: live `tp-designs` first, then `completed-tp-designs`, else the live path."""
    return explain_sources.design_dir(root, slug) or Path(root).joinpath(*_DESIGN_DIR, slug)


def brief_path(root, slug) -> Path:
    """The design dir's `brief.md`: live, else archived, else live; ValueError on a bad slug."""
    explain_state._check_slug(slug)
    return _design_dir(root, slug) / "brief.md"


def envelope_path(root, slug) -> Path:
    """`<state>/<slug>/pr-brief.envelope.json`; ValueError on a bad slug."""
    explain_state._check_slug(slug)
    return explain_state.state_root(root) / slug / f"{PR_BRIEF_KIND}.envelope.json"


def _stamp(value, fallback) -> str:
    """The text for the drafter / check-outcome line: argument, else envelope, else unknown."""
    chosen = value if value is not None else fallback
    return explain_markdown.escape_md(chosen if chosen not in (None, "") else _UNKNOWN)


def write_artifacts(root, slug, env, *, evidence_head, drafter=None, check_outcome=None) -> str:
    """Write the offline HTML and the envelope JSON; return the comment body. No `brief.md`."""
    explain_state._check_slug(slug)
    head = str(evidence_head)
    source = env if isinstance(env, dict) else {}
    marker = explainer_marker.marker(PR_BRIEF_KIND, slug, head)
    text = explain_markdown.render_markdown(env, head=head, marker=marker)
    text += (f"\nDrafter: {_stamp(drafter, source.get('drafter'))}. "
             f"Check outcome: {_stamp(check_outcome, source.get('check_outcome'))}.\n")
    page = explain_html.render_html(env, head=head, title=f"Explainer brief: {slug}")
    out = explain_state.state_root(root) / slug
    out.mkdir(parents=True, exist_ok=True)
    html_path = out / f"{PR_BRIEF_KIND}.html"
    html_path.write_text(page, encoding="utf-8")
    envelope_path(root, slug).write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")
    explain_state.delivery(root, slug, PR_BRIEF_KIND, update={"html": str(html_path)})
    return text


def write_brief(root, slug, env, *, evidence_head, drafter=None, check_outcome=None) -> Path:
    """Write `brief.md`, the offline HTML and the envelope JSON; commit nothing."""
    text = write_artifacts(root, slug, env, evidence_head=evidence_head, drafter=drafter,
                           check_outcome=check_outcome)
    brief = brief_path(root, slug)
    brief.parent.mkdir(parents=True, exist_ok=True)
    brief.write_text(text, encoding="utf-8")
    return brief


def _find_by_marker(comments, kind, slug):
    """The id of the first comment whose marker names this `kind` and `slug`, else None."""
    for comment in comments if isinstance(comments, list) else []:
        if not isinstance(comment, dict):
            continue
        parsed = explainer_marker.parse(comment.get("body"))
        if parsed and parsed["kind"] == kind and parsed["slug"] == slug:
            return comment.get("id")
    return None


def _store(root, slug, kind, comment_id, body) -> None:
    update = {}
    if comment_id is not None:
        update["comment_id"] = comment_id
    parsed = explainer_marker.parse(body)
    if parsed:
        update["posted_head"] = parsed["head"]
    if update:
        explain_state.delivery(root, slug, kind, update=update)


def _one_line(text) -> str:
    return " ".join(str(text).split())


def _see_path(root, slug, kind) -> str:
    brief = brief_path(root, slug)
    if kind == PR_BRIEF_KIND:
        return str(brief)
    return str(explain_state.delivery(root, slug, kind).get("html") or brief)


def degrade_line(root, slug, kind, reason) -> str:
    """Print `explainer: <reason> — see <path>` to stderr, store the reason once; return it."""
    reason = _one_line(reason)
    see = _see_path(root, slug, kind)
    explain_state.record_degraded(root, slug, kind, reason)
    line = f"explainer: {reason} — see {see}"
    print(line, file=sys.stderr)
    return line


def post_or_edit(root, slug, pr, body, *, kind, context, forge_mod=forge):
    """Edit the stored or marker-found comment, else post one; return the forge Result."""
    try:
        return _post_or_edit(root, slug, pr, body, kind, forge_mod)
    except automation_identity.BotAuthUnavailable as exc:
        degrade_line(root, slug, kind, exc)
        return forge.Result.degraded(" ".join(str(exc).split()))


def _post_or_edit(root, slug, pr, body, kind, forge_mod):
    stored = explain_state.delivery(root, slug, kind).get("comment_id")
    refused = None
    if stored is not None:
        result = forge_mod.comment_edit(root, stored, body)
        if result.status == "ok":
            _store(root, slug, kind, stored, body)
            return result
        refused = result
    listing = forge_mod.comment_list(root, pr)
    if listing.status != "ok":
        return refused if refused is not None else listing
    found = _find_by_marker(listing.payload.get("comments"), kind, slug)
    if found is not None:
        if stored is not None and str(found) == str(stored):
            return refused  # the stored comment is the one that will not edit
        result = forge_mod.comment_edit(root, found, body)
        if result.status == "ok":
            _store(root, slug, kind, found, body)
        return result
    result = forge_mod.comment_post(root, pr, body)
    if result.status == "ok":
        _store(root, slug, kind, result.payload.get("id"), body)
    return result


def refresh_needed(root, slug, pr, *, forge_mod=forge) -> bool:
    """True when the brief on PR `pr` no longer matches the PR head (see the module doc)."""
    posted = explain_state.delivery(root, slug, PR_BRIEF_KIND).get("posted_head")
    if not posted:
        return True
    result = forge_mod.pr_read(root, pr)
    if result.status != "ok":
        degrade_line(root, slug, PR_BRIEF_KIND, result.line)
        return True
    return str(result.payload.get("head_sha")) != str(posted)
