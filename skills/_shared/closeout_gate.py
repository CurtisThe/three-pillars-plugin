"""closeout_gate.py — preflight: refuse PR-iterate work on an un-archived design.

Verdict by tree state for slug S under repo root R:
  S == "orchestration"                          -> exempt   (reserved non-design slot)
  tp-designs/S/design.md absent, completed dir  -> archived
  tp-designs/S/design.md absent, no completed   -> exempt   (seed-only / no dir)
  design.md present with `completed:` frontmatter -> archived
  design.md present, no stamp                   -> unarchived (refuse)
  OS/IO error                                   -> exempt, reason `unreadable: ...`

Stdlib only; no forge call. Reuses detect_unarchived (not edited) for routing.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from detect_unarchived import DESIGNS_SUBDIR, find_unarchived
from weight_class import parse_frontmatter

COMPLETED_SUBDIR = "three-pillars-docs/completed-tp-designs"
RESERVED = "orchestration"
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Verdict:
    slug: str
    status: str  # "unarchived" | "archived" | "exempt"
    reason: str
    remedy: str = ""


def _remedy(root, slug: str) -> str:
    learn = "tp-design-learn"
    for f in find_unarchived(root):
        if f.slug == slug:
            learn = f.learn_skill
    return (
        f"Run /{learn} {slug} then /tp-design-complete {slug} first; "
        "the loop converges the head the human merges."
    )


def check(repo_root, design: str) -> Verdict:
    root = Path(repo_root)
    if design == RESERVED:
        return Verdict(design, "exempt", "reserved non-design slot")
    try:
        design_md = root / DESIGNS_SUBDIR / design / "design.md"
        if not design_md.is_file():
            if (root / COMPLETED_SUBDIR / design).is_dir():
                return Verdict(design, "archived", "moved to completed-tp-designs")
            return Verdict(design, "exempt", "no design.md in flight")
        if "completed" in parse_frontmatter(design_md.read_text(encoding="utf-8")):
            return Verdict(design, "archived", "design.md carries completed: stamp")
        return Verdict(design, "unarchived", "design.md has no completed: stamp", _remedy(root, design))
    except (OSError, UnicodeDecodeError) as exc:
        return Verdict(design, "exempt", f"unreadable: {exc}")


def slug_from_branch(name):
    """`tp/<slug>` -> slug; anything else -> None."""
    if isinstance(name, str) and name.startswith("tp/") and _SLUG_RE.match(name[3:]):
        return name[3:]
    return None


def _default_run_git(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)
    return r.returncode, r.stdout, r.stderr


def head_refusal(*, run_git=None, repo_root=None):
    """Refusal doc when HEAD is a `tp/<slug>` branch of an un-archived design, else None."""
    git = run_git or _default_run_git
    rc, out, _e = git(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    slug = slug_from_branch(out.strip()) if rc == 0 else None
    if slug is None:
        return None
    root = repo_root
    if root is None:
        rc, out, _e = git(["git", "rev-parse", "--show-toplevel"])
        if rc != 0:
            return None
        root = out.strip()
    v = check(root, slug)
    if v.status != "unarchived":
        return None
    rc, sha, _e = git(["git", "rev-parse", "HEAD"])
    return {"converged": False, "terminal": None, "head_sha": sha.strip() if rc == 0 else None,
            "proof_verified": False, "reason": "design-not-archived",
            "not_converged_reason": "design-not-archived", "remedy": v.remedy}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Refuse PR-iterate on an un-archived design.")
    p.add_argument("--repo", default=".")
    p.add_argument("--design", required=True)
    p.add_argument("--json", action="store_true", dest="as_json")
    args = p.parse_args(argv)
    if not _SLUG_RE.match(args.design):
        print(f"closeout-gate: invalid design slug {args.design!r}", file=sys.stderr)
        return 2
    v = check(args.repo, args.design)
    refuse = v.status == "unarchived"
    if args.as_json:
        print(json.dumps(asdict(v)))
    if refuse:
        print(f"closeout-gate: REFUSED — {v.slug} is not archived. {v.remedy}", file=sys.stderr)
        return 1
    if not args.as_json:
        print(f"closeout-gate: proceed ({v.status}: {v.reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
