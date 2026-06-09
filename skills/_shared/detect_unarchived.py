"""detect_unarchived.py — the merged-but-unarchived backstop detector.

Content-based, squash-safe, needs no git history: given the repo tree, it returns
the set of `three-pillars-docs/tp-designs/{slug}/` dirs that carry *implementation
evidence* (`implementation-audit.md` or `spike-results.md`) and therefore should
have been archived to `completed-tp-designs/`. Seed-only / design-only dirs (still
in flight) are exempt.

One detector, several surfaces (all read this same module):
  1. framework-check.sh invariant #27 — the HARD CI gate (default-branch only;
     the enforcement guard lives in the caller, not here).
  2. /tp-guide + /tp-session-restore — the SOFT, non-blocking closeout nudges
     (callers pass --exclude {current-design} so you aren't nagged about your
     own in-flight work).
  3. /tp-merge-from-main — a pre-push closeout warning (warn, never block).

This module is a *reporter*, never a gate: `main()` ALWAYS exits 0, and every
function fails open (any OS/IO error → empty result) so a hygiene check can never
false-fail a correctly-closed design.

Design refs:
  - three-pillars-docs/tp-designs/merged-design-closeout/design.md
  - three-pillars-docs/tp-designs/merged-design-closeout/detailed-design.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DESIGNS_SUBDIR = "three-pillars-docs/tp-designs"


@dataclass
class Finding:
    """A merged-but-unarchived design dir. `learn_skill` routes the remediation:
    spike-results.md → tp-spike-learn, else implementation-audit.md → tp-design-learn."""

    slug: str
    evidence: str
    learn_skill: str


def find_unarchived(repo_root) -> list[Finding]:
    """Scan three-pillars-docs/tp-designs/*/; flag a dir iff it carries impl evidence."""
    designs = Path(repo_root) / DESIGNS_SUBDIR
    findings: list[Finding] = []
    try:
        if not designs.is_dir():
            return []
        for d in sorted(designs.iterdir()):
            if not d.is_dir():
                continue
            # spike-results.md wins routing over implementation-audit.md (hybrid
            # case: a spike-flavored dir that also shipped a production skill).
            if (d / "spike-results.md").is_file():
                findings.append(
                    Finding(slug=d.name, evidence="spike-results.md", learn_skill="tp-spike-learn")
                )
            elif (d / "implementation-audit.md").is_file():
                findings.append(
                    Finding(slug=d.name, evidence="implementation-audit.md", learn_skill="tp-design-learn")
                )
    except OSError:
        return []  # fail-open: a hygiene check must never false-fail on IO error
    return findings


def main(argv=None) -> int:
    """CLI reporter. ALWAYS returns 0 — the framework-check caller decides
    enforcement; this only reports. Fail-open on any error."""
    parser = argparse.ArgumentParser(
        description="Report merged-but-unarchived three-pillars design dirs (impl evidence present)."
    )
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument("--slugs-only", action="store_true", help="print one slug per line")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print findings as JSON")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SLUG",
        help="exclude a slug (repeatable); nudge callers pass the current in-flight design",
    )
    args = parser.parse_args(argv)
    try:
        excluded = set(args.exclude or [])
        findings = [f for f in find_unarchived(args.repo) if f.slug not in excluded]
        if args.as_json:
            print(json.dumps([asdict(f) for f in findings]))
        elif args.slugs_only:
            for f in findings:
                print(f.slug)
        else:
            for f in findings:
                print(f"{f.slug}\t{f.evidence}\t{f.learn_skill}")
    except Exception:
        pass  # reporter, never a gate — swallow everything and still exit 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
