"""Ready-ping: tell the operator a design run's PR is ready, or that it stopped.

Task 1.1 covers the core: the ledger, the message, and the ping itself with
its delivery degrade (push tool -> marked printed line). ``ping_ready``,
``ping_stop``, ``pr_info`` and the CLI arrive in task 1.2.

Every public function is fail-open: nothing here raises to its caller. A
ledger or decisions write that cannot happen yields
``{"status": "error", "reason": ...}`` instead of an exception, because a
notification is never worth killing a run over.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MARK = "[READY-PING]"
# sibling _shared modules import each other by bare name; make that
# work however this module is loaded.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from finalizer import stop_key  # noqa: E402  (sibling _shared module)
LEDGER_DIR = "tp-ready-ping"
_GIT_TIMEOUT_S = 10


def pr_number(pr_url_or_none):
    """The PR number from a PR URL, or None when there isn't one.

    Both forge URL forms count: GitHub's ``/pull/<n>`` and Gitea's
    ``/pulls/<n>``. An ``int`` passes through. Trailing path segments like
    ``/files`` are ignored; a non-numeric segment is not a number.
    """
    if pr_url_or_none is None or isinstance(pr_url_or_none, bool):
        return None
    if isinstance(pr_url_or_none, int):
        return pr_url_or_none
    if not isinstance(pr_url_or_none, str):
        return None
    match = re.search(r"/pulls?/(\d+)(?:[/?#].*)?$", pr_url_or_none.strip())
    if not match:
        match = re.search(r"/pulls?/(\d+)", pr_url_or_none.strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _git_common_dir(root="."):
    """`git rev-parse --git-common-dir` as an absolute path, or None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else (Path(root) / path).resolve()


def ledger_path(slug):
    """`<git-common-dir>/tp-ready-ping/<slug>.ndjson`, absolute.

    Falls back to a literal `.git` directory when git cannot answer (no git,
    not a repo), so the caller still gets a usable path.
    """
    common = _git_common_dir()
    if common is None:
        common = Path(".git").resolve()
    return Path(common) / LEDGER_DIR / f"{slug}.ndjson"


def message(kind, slug, pr, summary):
    """The one-line ping text; `#N ` is omitted when there is no PR number."""
    who = f"{slug}"
    body = f"({who}): {summary}"
    if kind == "stop":
        prefix = "run stopped, needs you:"
    else:
        prefix = "ready to merge"
    if pr is None:
        return f"{prefix} {body}"
    return f"{prefix} #{pr} {body}"


def _decisions_header(kind, pr):
    """The decisions.md header for one ping.

    Deliberately never ``### [finalizer]`` — that string is counted by
    ``test_finalizer_ship.py`` and this is not a finalizer entry.
    """
    return f"### [ready-ping] {kind} ping #{pr if pr is not None else '-'}"


def _key_seen(ledger, key):
    path = Path(ledger)
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("key") == key:
            return True
    return False


def _append_ledger(ledger, record):
    path = Path(ledger)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def _append_decisions(decisions, header, msg, key):
    path = Path(decisions)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = f"{header}\n{msg}\n{key}\n"
    if path.exists() and path.stat().st_size > 0:
        entry = "\n" + entry
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def ping(kind, *, slug, pr, head, summary, ledger, key=None, decisions=None,
         push_fn=None, out=None, now=None):
    """Deliver one ping once per key, recording it in the ledger.

    Returns ``{"status": "sent"|"duplicate"|"error", ...}``. A key already in
    the ledger delivers nothing. Delivery is `push_fn(message)` when given and
    it does not raise (channel ``push``), otherwise the marked line printed to
    `out` (default stderr, channel ``print``).
    """
    try:
        resolved_key = key if key is not None else f"{kind}:{head or summary}"
        if _key_seen(ledger, resolved_key):
            return {"status": "duplicate", "kind": kind, "key": resolved_key}

        msg = message(kind, slug, pr, summary)
        channel = "push"
        if push_fn is None:
            channel = _print(msg, out)
        else:
            try:
                push_fn(msg)
            except Exception:
                channel = _print(msg, out)

        at = now or datetime.now(timezone.utc).isoformat()
        _append_ledger(ledger, {
            "key": resolved_key, "kind": kind, "slug": slug, "pr": pr,
            "head": head, "channel": channel, "message": msg, "at": at,
        })
        header = _decisions_header(kind, pr)
        if decisions is not None:
            _append_decisions(decisions, header, msg, resolved_key)
        return {
            "status": "sent", "kind": kind, "key": resolved_key,
            "channel": channel, "message": msg, "decisions_line": header,
        }
    except Exception as exc:  # fail-open: a ping never breaks its caller
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def _print(msg, out):
    """The degrade path: the marked line to `out` (stderr by default)."""
    import sys

    stream = sys.stderr if out is None else out
    try:
        stream.write(f"{MARK} {msg}\n")
    except Exception:
        pass
    return "print"


def _safe_info(info_fn, pr_url):
    """``info_fn(pr_url)`` as a dict — ``{}`` on a raise or a bad shape."""
    if pr_url is None or info_fn is None:
        return {}
    try:
        info = info_fn(pr_url)
    except Exception:
        return {}
    return info if isinstance(info, dict) else {}


def _slug_from_ref(head_ref_name):
    """``tp/<slug>`` -> ``<slug>``; anything else -> ``unknown``."""
    ref = head_ref_name
    if not isinstance(ref, str) or not ref:
        return "unknown"
    return ref[len("tp/"):] if ref.startswith("tp/") else ref


def pr_info(pr_url):
    """One ``gh pr view`` for mergeability/title/head; ``{}`` on any failure.

    A non-GitHub forge (no ``gh``, no auth, a Gitea URL) simply yields ``{}``
    and the caller pings with the unchecked-mergeability suffix instead.
    """
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", str(pr_url), "--json",
             "mergeable,title,headRefName"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def ping_ready(pr_url, head, *, info_fn=None, ledger=None, decisions=None,
               push_fn=None, out=None):
    """Ping once that ``pr_url`` is ready to merge; skip a conflicting PR.

    The slug is the PR's head ref minus ``tp/`` (``unknown`` when ``gh``
    cannot answer), the summary the PR title, suffixed with
    ``" (mergeability unchecked)"`` unless ``mergeable == "MERGEABLE"``.
    """
    try:
        info = _safe_info(info_fn or pr_info, pr_url)
        if info.get("mergeable") == "CONFLICTING":
            return {"status": "skipped", "reason": "conflicting"}
        slug = _slug_from_ref(info.get("headRefName"))
        summary = info.get("title") or "pull request ready"
        if info.get("mergeable") != "MERGEABLE":
            summary = f"{summary} (mergeability unchecked)"
        return ping("ready", slug=slug, pr=pr_number(pr_url), head=head,
                    summary=summary,
                    ledger=ledger if ledger is not None else ledger_path(slug),
                    decisions=decisions, push_fn=push_fn, out=out)
    except Exception as exc:  # fail-open, like every public entry here
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def ping_stop(stop, *, info_fn=None, ledger=None, decisions=None, push_fn=None,
              out=None):
    """Ping once per finalizer stop.

    ``stop`` is the finalizer stop dict; its ``target`` is a PR URL when it
    contains ``://`` (slug from ``info_fn``) and otherwise the slug itself.
    The key carries ``finalizer.stop_key(stop)`` so two different headless
    stops for one slug both ping. A malformed stop returns an error dict —
    nothing here raises.
    """
    try:
        base_key = stop_key(stop)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        target = stop["target"]
        pr_url = target if "://" in target else None
        info = _safe_info(info_fn or pr_info, pr_url) if pr_url else {}
        slug = _slug_from_ref(info.get("headRefName")) if pr_url else target
        head = stop.get("head")
        summary = (f"{stop.get('source')}/{stop.get('signal')} "
                   "escalated to the operator")
        return ping("stop", slug=slug, pr=pr_number(pr_url), head=head,
                    summary=summary,
                    ledger=ledger if ledger is not None else ledger_path(slug),
                    key=f"stop:{base_key}:{head or ''}",
                    decisions=decisions, push_fn=push_fn, out=out)
    except Exception as exc:
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def _parser():
    ap = argparse.ArgumentParser(
        prog="ready_ping", description="Ready/stop pings for design runs")
    sub = ap.add_subparsers(dest="command", required=True)
    ready = sub.add_parser("ready", help="ping that a PR is ready to merge")
    ready.add_argument("--pr-url", required=True)
    ready.add_argument("--head", required=True)
    ready.add_argument("--decisions")
    stop = sub.add_parser("stop", help="ping that a run stopped and needs you")
    stop.add_argument("--slug", required=True)
    stop.add_argument("--summary", required=True)
    stop.add_argument("--pr-url")
    stop.add_argument("--head")
    stop.add_argument("--decisions")
    return ap


def _cli_stop_key(slug, summary, head):
    """``stop:<slug>:<12 hex of sha1(summary)>:<head>`` for the CLI stop."""
    digest = hashlib.sha1(summary.encode(),
                          usedforsecurity=False).hexdigest()[:12]
    return f"stop:{slug}:{digest}:{head or ''}"


def main(argv=None):
    """CLI: one JSON line on stdout, the marked ping on stderr, exit 0."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code in (None, 2) else int(exc.code)
    if args.command == "ready":
        result = ping_ready(args.pr_url, args.head, decisions=args.decisions)
    else:
        result = ping("stop", slug=args.slug, pr=pr_number(args.pr_url),
                      head=args.head, summary=args.summary,
                      ledger=ledger_path(args.slug),
                      key=_cli_stop_key(args.slug, args.summary, args.head),
                      decisions=args.decisions)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
