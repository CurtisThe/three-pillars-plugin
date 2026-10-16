"""cert_gap — the PR certification block and the `tp:cert-gap` label.

design: certifier-lean (Task 1.6; design.md Behaviors 3, 6).

A run that continues with `cert-gap` findings carries its evidence in the PR itself:

- `block(route, lint)` renders the certification block: one bullet per `cert_route`
  gap, one per note (a claim-shape `unverified`, or a cert-fix claim that already spent
  its follow-up), one per claim the lint dropped before dispatch (`lint`'s
  `dropped` claim dicts — each bullet carries the claim id and every `<id>: <reason>`
  line that names it, joined in order; a bare id in `dropped` is accepted too). With nothing to report the block is the
  heading plus one bullet, so the PR always states that certification ran.
- `apply_label(repo, pr, route, ...)` asks the forge adapter for `tp:cert-gap`, and
  only when the route actually has gaps. Every non-`ok` outcome — a `degraded` adapter
  result (a Gitea instance without the label, an unsupported forge) or an unavailable
  bot identity — leaves the block as the only record and returns exactly one line
  saying the label was skipped, carrying the adapter's own degrade line. No gaps means
  no forge call at all.

Forge parity: GitHub's add-labels call creates a missing label, so re-adding is a
no-op. Gitea's label path degrades when the label does not exist — visibly, in the one
skipped line, never silently.

CLI (`certify_cli_lean.MODULES`): `gap-block`, `gap-label`.
"""

from __future__ import annotations

import forge
import github_pr_author
from certify_cli import EXIT_OK, BadInput, load_json

LABEL = "tp:cert-gap"
HEADING = "#### Certification"
NONE_BULLET = "- certification ran: no gaps, no notes, no dropped claims"


def _reason_text(item) -> str:
    reasons = [str(r) for r in item.get("reasons") or []]
    if item.get("status"):
        reasons.insert(0, str(item["status"]))
    return "; ".join(reasons) or "no reason recorded"


def _bullets(route, lint) -> list[str]:
    out = []
    for item in route.get("gaps") or ():
        out.append(f"- gap `{item.get('key')}`: {_reason_text(item)}")
    for item in route.get("notes") or ():
        out.append(f"- note `{item.get('key')}`: {_reason_text(item)}")
    lines = [str(ln) for ln in (lint or {}).get("lines") or ()]
    for item in (lint or {}).get("dropped") or ():
        cid = str(item.get("id") if isinstance(item, dict) else item)
        reasons = [ln.split(":", 1)[1].strip() for ln in lines
                   if ln.split(":", 1)[0].strip() == cid]
        detail = "; ".join(r for r in reasons if r) or "dropped by the claim lint"
        out.append(f"- dropped claim `{cid}`: {detail}")
    return out


def block(route, lint=None) -> str:
    """The PR certification block: every gap, note and lint-dropped claim, once."""
    if not isinstance(route, dict):
        raise BadInput("route must be a JSON object")
    bullets = _bullets(route, lint)
    return "\n".join([HEADING] + (bullets or [NONE_BULLET]))


def apply_label(repo, pr, route, *, label_add=None, info=None) -> str:
    """One line for the `tp:cert-gap` label; the block stands on its own regardless."""
    if not (route or {}).get("gaps"):
        return "cert-gap: none"
    add = label_add if label_add is not None else forge.label_add
    try:
        result = add(repo, pr, LABEL, info=info) if info is not None else add(repo, pr, LABEL)
    except github_pr_author.BotAuthUnavailable as exc:  # tp-allow-fail-open: no bot token means the PR block is the whole record
        return f"cert-gap: label skipped: bot identity unavailable: {exc}"
    if getattr(result, "status", "") == "ok":
        return f"cert-gap: labelled {LABEL} on PR {pr}"
    return f"cert-gap: label skipped: {getattr(result, 'line', '') or 'no adapter result'}"


def cmd_gap_block(args) -> int:
    route = load_json(args.route)
    if not isinstance(route, dict):
        raise BadInput("--route must be a JSON object")
    lint = load_json(args.lint) if args.lint else None
    print(block(route, lint))
    return EXIT_OK


def cmd_gap_label(args) -> int:
    route = load_json(args.route)
    if not isinstance(route, dict):
        raise BadInput("--route must be a JSON object")
    print(apply_label(args.repo, args.pr, route))  # every label outcome exits 0
    return EXIT_OK


def register(sub) -> None:
    """Add `gap-block` / `gap-label` to `certify.py`'s subparsers."""
    blk = sub.add_parser("gap-block", help="the PR certification block")
    blk.add_argument("--route", required=True, help="a `certify.py route` decision JSON")
    blk.add_argument("--lint", help="a `certify.py lint` report JSON")
    blk.set_defaults(func=cmd_gap_block)
    lab = sub.add_parser("gap-label", help="apply the tp:cert-gap label through the forge")
    lab.add_argument("--route", required=True, help="a `certify.py route` decision JSON")
    lab.add_argument("--pr", required=True, type=int, help="the PR number")
    lab.add_argument("--repo", default=".", help="the repo (path or owner/name)")
    lab.set_defaults(func=cmd_gap_label)
