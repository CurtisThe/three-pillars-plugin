"""pr_push_check.py -- skip a push to a PR that is already merged.

`check(repo, pr_url)` reads the PR through `forge.pr_read` and returns `(rc, line)`:
MERGED -> (1, "PR #n merged: push skipped, tail left for the seat"); OPEN/CLOSED -> (0, "");
a degraded read -> (0, "PR state unknown (<reason>): pushing"). The CLI exits 2 on a malformed URL.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge  # noqa: E402


def _number(pr_url: str):
    seg = str(pr_url).rstrip("/").rsplit("/", 1)[-1]
    return int(seg) if seg.isdigit() else None


def check(repo, pr_url, *, pr_read=forge.pr_read):
    number = _number(pr_url)
    if number is None:
        return 2, f"malformed --pr-url: {pr_url}"
    res = pr_read(repo, number)
    if getattr(res, "status", "") != "ok":
        reason = getattr(res, "line", "") or "unknown"
        return 0, f"PR state unknown ({reason}): pushing"
    if str(res.payload.get("state", "")).lower() == "merged":
        return 1, f"PR #{number} merged: push skipped, tail left for the seat"
    return 0, ""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr-url", required=True)
    args = p.parse_args(argv)
    rc, line = check(args.repo, args.pr_url)
    if line:
        print(line, file=sys.stderr if rc == 2 else sys.stdout)
    return rc


if __name__ == "__main__":
    sys.exit(main())
