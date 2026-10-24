"""archive_allowlist.py — design-archive allowlist + reference check (Task 1.8).

`plan_prune_many(design_dirs, repo_root)` computes one global *least fixpoint*
over every given design dir:

- **candidates** — each dir's tracked files whose top-level name is not in
  `ALLOWLIST` (only top-level names are allowlistable; nested files are always
  candidates);
- **kept (seed)** — the allowlisted tracked files plus the untracked
  non-ignored files inside the given dirs;
- **sources** — the kept files plus every tracked text file in the repo outside
  the union of all candidates;
- a candidate *named* by a source becomes kept and a source; iterate until
  stable (least fixpoint — nothing extra is kept).

A reference names a candidate when it resolves, repo-relative, to the
candidate's path or to a proper ancestor directory of it within the same design
dir. A design-root reference (`tp-designs/<slug>/`) names the dir alone and
keeps nothing extra. A token may name a candidate under either
`tp-designs/` or `completed-tp-designs/` (ambiguity keeps). Only tracked files
are drop candidates; an untracked non-ignored file is kept (design-complete
stages it), and a gitignored file is reported under `ignored` and never
touched.

`plan_prune(design_dir, repo_root)` is `plan_prune_many([design_dir], ...)`.
Every design dir must be an archived one (`completed-tp-designs/<slug>`, present,
holding a tracked file) — otherwise `DesignDirError`: could-not-evaluate is never
a clean empty plan. `apply(plan, repo_root)` `git rm`s only the tracked drops; it
refuses (raises `UncommittedDropError` from `archive_drop_guard`, removes
nothing) when a drop's content is in no commit.

CLI: `archive_allowlist.py plan|apply --design-dir D [--design-dir D ...]
[--json] [--repo-root R]`. Exit 0 on success, 1 when `apply` refuses a drop,
2 when a design dir cannot be evaluated. Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from archive_drop_guard import (  # noqa: F401 (re-export)
    UncommittedDropError, never_committed_of, uncommitted_drops)
from task_scope import _git_env

# Top-level design-dir file names always kept (fnmatch on the top-level name
# only). Nested files are never allowlist-exempt.
ALLOWLIST = [
    "design.md",
    "detailed-design*.md",
    "plan.md",
    "decisions.md",
    "review*.md",
    "spike-results.md",
    "handoff.md",
    "seed.md",
    "research.md",
    "lock.json",
    "implementation-audit.md",
    "dispatch-telemetry.ndjson",  # Decision 12 measurement data (run-throughput H1)
    "escape-ledger.ndjson",  # escape_ledger.NDJSON_NAME
    "finalizer-ledger.json",  # finalizer.py ledger
    "brief.md",  # explainer PR brief (skills/_shared/explainer.md)
    "rulings.ndjson",  # explainer auto-ruling ledger
    "retro-findings.json",  # run_retro.FINDINGS: pr-section reads the archived dir
    "retro-outbox.json",  # run_retro_file.OUTBOX_NAME: the sealed board outbox
]

# Repo-form reference: `tp-designs/<slug>/<rest>` or
# `completed-tp-designs/<slug>/<rest>`; the `completed-` prefix is optional so
# a token names a candidate under either root (ambiguity keeps).
_REPO_TOKEN_RE = re.compile(
    r"(?:completed-)?tp-designs/([A-Za-z0-9._-]+)/([^\s`'\"()\[\]<>|,;*]*)"
)
_REL_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-/]+")
_CHUNK = 200
ARCHIVE_ROOT = "three-pillars-docs/completed-tp-designs"


@dataclass
class PrunePlan:
    """A prune plan: repo-relative paths to keep, drop, and to leave alone."""

    keep: list[str]
    drop: list[str]
    ignored: list[str]
    bytes: int

    def to_json(self) -> dict:
        return {"keep": list(self.keep), "drop": list(self.drop),
                "ignored": list(self.ignored), "bytes": self.bytes}


def _gitls(root: Path, flags: list[str], spec: str | None) -> list[str]:
    cmd = ["git", "-C", str(root), "ls-files", *flags, "-z"]
    if spec is not None:
        cmd += ["--", spec]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                       env=_git_env())
    return [x for x in r.stdout.split("\0") if x]


def _to_rel(repo_root: Path, d: str) -> str:
    p = Path(d)
    if not p.is_absolute():
        p = Path(repo_root) / p
    return posixpath.normpath(os.path.relpath(p, repo_root).replace(os.sep, "/"))


def _is_allowlisted(rest: str) -> bool:
    return "/" not in rest and any(fnmatch.fnmatch(rest, pat) for pat in ALLOWLIST)


def _text_of(path: Path) -> str | None:
    """Decoded text of a readable file, or None (binary / unreadable)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8192)
            if b"\x00" in head:
                return None
            rest = f.read()
        return (head + rest).decode("utf-8", errors="replace")
    except OSError:
        return None


def _clean_rest(t: str) -> str:
    if "#" in t:
        t = t.split("#", 1)[0]
    t = re.sub(r":\d+$", "", t)
    return t.rstrip(".:").rstrip("/")


def _repo_tokens(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), _clean_rest(m.group(2)))
            for m in _REPO_TOKEN_RE.finditer(text)]


def _rel_tokens(text: str, source: str, design_dir: str) -> set[str]:
    """Path tokens resolved against the source's dir, kept only when they are
    a proper descendant of `design_dir` (a design-root reference names nothing)."""
    base = posixpath.dirname(source)
    out: set[str] = set()
    for m in _REL_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if "." not in tok and "/" not in tok:
            continue
        resolved = posixpath.normpath(posixpath.join(base, tok))
        if resolved.startswith(design_dir + "/"):
            out.add(resolved)
    return out


def _named_by_repo(rest_c: str, tokens: list[tuple[str, str]], slug_c: str) -> bool:
    return any(
        slug == slug_c and rest and (rest_c == rest or rest_c.startswith(rest + "/"))
        for slug, rest in tokens
    )


def _named_by_rel(path_c: str, resolved: set[str]) -> bool:
    return any(
        path_c == r or path_c.startswith(r.rstrip("/") + "/") for r in resolved
    )


def _dir_of(cand: str, dirs: list[str]) -> str | None:
    for d in dirs:
        if cand.startswith(d + "/"):
            return d
    return None


class DesignDirError(ValueError):
    """A design dir that cannot be evaluated: plan/apply refuse rather than
    report a clean, empty plan."""


def design_dir_problem(repo_root: str | Path, design_dir: str) -> str | None:
    """Why `design_dir` is not an evaluable archived design dir, or None.

    It must be `three-pillars-docs/completed-tp-designs/<slug>`, exist, and
    hold at least one tracked file (an archived dir always tracks its
    `design.md`; none means design-complete's `git mv` is not in the index)."""
    root = Path(repo_root)
    rel = _to_rel(root, design_dir)
    parent, _, slug = rel.rpartition("/")
    if parent != ARCHIVE_ROOT or slug in ("", ".", ".."):
        return f"{design_dir}: not an archived design dir (expected {ARCHIVE_ROOT}/<slug>)"
    if not (root / rel).is_dir():
        return f"{rel}: no such directory"
    if not _gitls(root, [], rel):
        return (f"{rel}: holds no tracked file — the `git mv` that archives the "
                "design is not in the index")
    return None


def plan_prune_many(design_dirs: list[str], repo_root: str | Path) -> PrunePlan:
    root = Path(repo_root)
    dirs = [_to_rel(root, d) for d in design_dirs if str(d).strip()]
    if not dirs:
        raise DesignDirError("no design dir given")
    problems = [p for p in (design_dir_problem(root, d) for d in dirs) if p]
    if problems:
        raise DesignDirError("; ".join(problems))

    kept: set[str] = set()
    ignored: set[str] = set()
    cand_union: set[str] = set()
    for d in dirs:
        for f in _gitls(root, [], d):
            if _is_allowlisted(f[len(d) + 1:]):
                kept.add(f)
            else:
                cand_union.add(f)
        kept.update(_gitls(root, ["--others", "--exclude-standard"], d))
        ignored.update(_gitls(root, ["--others", "--ignored",
                                    "--exclude-standard"], d))
    external = set(_gitls(root, [], None)) - cand_union

    # Token cache: each source is tokenized once, no O(sources x candidates).
    token_cache: dict[str, tuple[list[tuple[str, str]], dict[str, set[str]]] | None] = {}

    def tokens_for(s: str):
        if s in token_cache:
            return token_cache[s]
        t = _text_of(root / s)
        val = None
        if t is not None:
            val = (_repo_tokens(t),
                   {d: _rel_tokens(t, s, d) for d in dirs if s.startswith(d + "/")})
        token_cache[s] = val
        return val

    def candidate_named(cand: str, s: str) -> bool:
        val = tokens_for(s)
        if val is None:
            return False
        repo_tok, rel_tok = val
        d = _dir_of(cand, dirs)
        if d is None:
            return False
        slug_c = d.rsplit("/", 1)[-1]
        if _named_by_repo(cand[len(d) + 1:], repo_tok, slug_c):
            return True
        return _named_by_rel(cand, rel_tok.get(d, ()))

    # Least fixpoint: seeds are kept + external; newly kept candidates become
    # sources; repeat until a pass adds nothing.
    sources: set[str] = kept | external
    scanned: set[str] = set()
    while True:
        added: list[str] = []
        for s in sorted(sources - scanned):
            scanned.add(s)
            for c in cand_union:
                if c not in kept and candidate_named(c, s):
                    kept.add(c)
                    added.append(c)
        if not added:
            break
        sources.update(added)

    drop = sorted(cand_union - kept)
    total = 0
    for f in drop:
        try:
            total += os.path.getsize(root / f)
        except OSError:
            pass
    return PrunePlan(
        keep=sorted(kept),
        drop=drop,
        ignored=sorted(ignored),
        bytes=total,
    )


def plan_prune(design_dir: str, repo_root: str | Path) -> PrunePlan:
    return plan_prune_many([design_dir], repo_root)


def apply(plan: PrunePlan, repo_root: str | Path) -> None:
    """`git rm -f` the tracked drops in chunks; ignored/untracked files untouched.

    `-f` because design-complete runs this after its `git mv` (step 6c) and
    before the commit (6f): every drop is staged-added vs HEAD, which a plain
    `git rm` refuses. `-f` also skips git's lost-work check, so `apply` checks
    first: any drop with uncommitted changes raises `UncommittedDropError` and
    nothing is removed.
    """
    drops = list(plan.drop)
    if not drops:
        return
    bad = uncommitted_drops(drops, repo_root)
    if bad:
        raise UncommittedDropError(bad, never_committed_of(bad, repo_root))
    for i in range(0, len(drops), _CHUNK):
        subprocess.run(
            ["git", "-C", str(repo_root), "rm", "-q", "-f", "--", *drops[i:i + _CHUNK]],
            capture_output=True, text=True, check=True, env=_git_env(),
        )


def _print(plan: PrunePlan, as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan.to_json(), indent=2))
        return
    for p in plan.drop:
        print(p)
    print(f"total: {plan.bytes} bytes")


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="design-archive allowlist + reference check")
    ap.add_argument("action", choices=["plan", "apply"])
    ap.add_argument("--design-dir", action="append", required=True,
                    dest="design_dirs", help="design dir (repeatable)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo-root", default=os.getcwd())
    args = ap.parse_args(argv)
    try:
        plan = plan_prune_many(args.design_dirs, args.repo_root)
    except DesignDirError as exc:
        print(f"archive_allowlist: cannot evaluate: {exc}", file=sys.stderr)
        return 2
    if args.action == "apply":
        try:
            apply(plan, args.repo_root)
        except UncommittedDropError as exc:
            print(f"archive_allowlist: {exc}", file=sys.stderr)
            return 1
    _print(plan, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
