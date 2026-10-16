#!/usr/bin/env python3
"""forge_cli.py — the one command line over `forge.py`'s dispatch (Task 1.5).

`forge.py pr-create | pr-read | comment-post | comment-edit | comment-list |
label-add | label-remove | resolve | compare-url`, with one exit-code contract shared
by every subcommand: **0** ok, **2** usage, **3** bot auth unavailable (github only),
**4** degraded. stdout is machine-readable only — the `ForgeInfo` JSON, a payload
JSON, a PR URL or a compare URL — and is empty for a degrade on a forge whose URL
shape is unknown, so a Gitea origin never gets a `github.com` URL and kind `other`
never gets a guessed one. Every degrade is the one actionable line on stderr.

Everything after a literal `--` on `pr-create` is pass-through: on github it goes to
`github_pr_author.py` untouched (that chokepoint keeps authorship), elsewhere it is
read here for `--base/--head/--title/--body/--body-file/--reviewer`. Split out of
`forge.py` to keep both files under the soft-warn. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import sys

import forge
import forge_gitea_agit
import github_pr_author

EXIT_OK, EXIT_USAGE, EXIT_BOT_AUTH, EXIT_DEGRADED = 0, 2, 3, 4


def _split_on_dashdash(raw_argv: list) -> "tuple[list, list]":
    """`(own, passthrough)` on the first literal `--`; the rest is never re-quoted."""
    if "--" in raw_argv:
        idx = raw_argv.index("--")
        return raw_argv[:idx], raw_argv[idx + 1:]
    return raw_argv, []


def _parser() -> argparse.ArgumentParser:
    repo_opt = argparse.ArgumentParser(add_help=False)
    repo_opt.add_argument(
        "--repo", default=None,
        help="local repo path whose origin is the forge (default: git toplevel)")
    top = argparse.ArgumentParser(prog="forge.py",
                                 description="One forge entry point, one exit code.")
    sub = top.add_subparsers(dest="command", required=True)
    sub.add_parser("resolve", parents=[repo_opt], help="print the resolved ForgeInfo")
    cmp_ = sub.add_parser("compare-url", parents=[repo_opt],
                          help="print this forge's own compare URL")
    cmp_.add_argument("--base", required=True)
    cmp_.add_argument("--head", required=True)
    create = sub.add_parser("pr-create", parents=[repo_opt],
                            help="open a PR (args after `--`)")
    create.add_argument("--context", choices=["manual", "autonomous"], default="manual")
    for name, extra in (("pr-read", "number"), ("comment-post", "number"),
                        ("comment-edit", "comment-id"), ("label-add", "number"),
                        ("label-remove", "number")):
        op = sub.add_parser(name, parents=[repo_opt])
        op.add_argument(extra.replace("-", "_"))
        if name in ("comment-post", "comment-edit"):
            op.add_argument("--body-file", required=True)
        if name in ("label-add", "label-remove"):
            op.add_argument("name")
    listing = sub.add_parser("comment-list", parents=[repo_opt],
                             help="print a PR's comments as {comments: [{id, body}]}")
    listing.add_argument("--number", required=True)
    return top


def _passthrough_parser() -> argparse.ArgumentParser:
    """The `pr-create` args after `--` for a non-github forge. Unknown flags pass.

    `--repo` is accepted here too so `pr-create -- … --repo P` names the repo (the
    position argparse would otherwise put it in).
    """
    p = argparse.ArgumentParser(add_help=False)
    for flag in ("--base", "--head", "--title", "--body", "--body-file", "--reviewer",
                 "--repo"):
        p.add_argument(flag)
    return p


def _read_body(path) -> "tuple[str | None, str]":
    """`(text, error_line)` for `--body-file`: `(None, "")` when none was named."""
    if not path:
        return None, ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(), ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"cannot read --body-file {path}: {exc}"


def _print_result(result: forge.Result) -> int:
    """ok -> payload JSON, 0. degraded -> the one line on stderr, 4."""
    if result.status == "ok":
        print(json.dumps(result.payload))
        if result.note:
            print(result.note, file=sys.stderr)
        return EXIT_OK
    print(result.line, file=sys.stderr)
    return EXIT_DEGRADED


def _compare_url(info, base: str, head: str) -> str:
    if info.kind == "github":
        return f"{info.web_base}/{info.owner}/{info.repo}/compare/{base}...{head}" \
               "?expand=1"
    return forge_gitea_agit.compare_url(info, base, head)


def _cmd_compare_url(args, info) -> int:
    if info.kind == "other":
        print(forge._unsupported(info).line, file=sys.stderr)
        return EXIT_DEGRADED
    print(_compare_url(info, args.base, args.head))
    return EXIT_OK


def _cmd_pr_create(args, repo, info, passthrough) -> int:
    if info.kind == "github":  # authorship stays with the PR-author chokepoint
        argv = ["create", "--context", args.context]
        if args.repo:
            argv += ["--repo", args.repo]
        try:
            return github_pr_author.main(argv + ["--", *passthrough])
        except github_pr_author.BotAuthUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_BOT_AUTH
    pt, _unknown = _passthrough_parser().parse_known_args(passthrough)
    file_body, bad = _read_body(pt.body_file)
    if bad:
        print(bad, file=sys.stderr)
        return EXIT_USAGE
    body = pt.body if pt.body is not None else (file_body or "")
    result = forge.pr_create(repo, base=pt.base or "", head=pt.head or "",
                             title=pt.title or "", body=body, reviewers=pt.reviewer,
                             info=info)
    if result.status == "ok":
        print(result.payload.get("url", ""))
        if result.note:
            print(result.note, file=sys.stderr)
        return EXIT_OK
    print(result.line, file=sys.stderr)
    if info.kind == "gitea":  # Gitea's own URL shape is known — offer it
        print(_compare_url(info, pt.base or "", pt.head or ""))
    return EXIT_DEGRADED


def _cmd_payload(args, repo, info, op: str) -> int:
    body, bad = _read_body(getattr(args, "body_file", None))
    if bad:
        print(bad, file=sys.stderr)
        return EXIT_USAGE
    try:  # a github write runs as the configured bot; an unusable bot refuses (exit 3)
        if op == "pr_read":
            result = forge.pr_read(repo, args.number, info=info)
        elif op == "comment_post":
            result = forge.comment_post(repo, args.number, body or "", info=info)
        elif op == "comment_edit":
            result = forge.comment_edit(repo, args.comment_id, body or "", info=info)
        elif op == "comment_list":
            result = forge.comment_list(repo, args.number, info=info)
        elif op == "label_add":
            result = forge.label_add(repo, args.number, args.name, info=info)
        else:
            result = forge.label_remove(repo, args.number, args.name, info=info)
    except github_pr_author.BotAuthUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_BOT_AUTH
    return _print_result(result)


def main(argv=None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    own, passthrough = _split_on_dashdash(raw)
    try:
        args = _parser().parse_args(own)
    except SystemExit as exc:  # argparse usage error -> our contract's 2
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_OK
    repo = args.repo or str(github_pr_author._default_repo_root())
    info = forge.resolve(repo)
    if args.command == "resolve":
        print(json.dumps(info._asdict()))
        return EXIT_OK
    if args.command == "compare-url":
        return _cmd_compare_url(args, info)
    if args.command == "pr-create":
        return _cmd_pr_create(args, repo, info, passthrough)
    return _cmd_payload(args, repo, info, args.command.replace("-", "_"))


if __name__ == "__main__":
    sys.exit(main())
