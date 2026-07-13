"""review_proof.py — per-round proof-of-review artifact capture and gate predicate.

Stdlib-only (subprocess, json, pathlib, os, datetime). No anthropic / claude
imports (C1-clean, matching run_round.py). Imported by run_round.py via the
same SCRIPTS_DIR sys.path shim.

Public surface:
    default_proof_root(start=None) -> Path
    resolve_numstat(base, head, *, run_git=None) -> dict
    capture_proof(base, head, angle_responses, *, root=None, run_git=None, now_iso=None) -> dict
    proof_present_and_nonempty(head, *, root=None) -> bool
    empty_diff_sentinel() -> dict
    format_proof_digest(meta, angle_finding_counts) -> str
    proof_comment_on_head(pr_url, head, *, comments_fn/config/self_login_fn) -> bool
    proof_ok(head, *, pr_url/root/comments_fn/config/self_login_fn) -> bool
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# _shared project_root is resolved at import time once.
_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from project_root import find_project_root  # noqa: E402

_MAX_TRANSCRIPT_CHARS = 20000
_MAX_NUMSTAT_CHARS = 20000


# ---------- root resolution ----------


def default_proof_root(start=None) -> Path:
    """Return <repo-root>/.three-pillars/review-proof (host-agnostic).

    Falls back to Path(start or cwd()) / '.three-pillars' / 'review-proof'
    when not in a git repo.
    """
    git_root = find_project_root(start)
    base = git_root if git_root is not None else Path(start) if start is not None else Path.cwd()
    return base / ".three-pillars" / "review-proof"


# ---------- numstat ----------


def _default_run_git(args: list[str]) -> tuple[int, str, str]:
    """Default subprocess shim for git commands."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_numstat(raw: str) -> tuple[int, int, int]:
    """Parse `git diff --numstat` stdout into (files_changed, insertions, deletions).

    Whitespace-tolerant; ignores malformed rows.  Binary rows (-\\t-\\t<path>)
    count toward files_changed but contribute 0 insertions/deletions.
    """
    files_changed = 0
    insertions = 0
    deletions = 0
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        ins_str, del_str, _ = parts
        ins_str = ins_str.strip()
        del_str = del_str.strip()
        # Binary files have '-' for both counts
        if ins_str == "-" and del_str == "-":
            files_changed += 1
            continue
        try:
            ins = int(ins_str)
            dels = int(del_str)
        except ValueError:
            continue  # malformed row — ignore
        files_changed += 1
        insertions += ins
        deletions += dels
    return files_changed, insertions, deletions


def resolve_numstat(
    base: str,
    head: str,
    *,
    run_git: "Callable[[list[str]], tuple[int, str, str]] | None" = None,
) -> dict:
    """Run `git diff --numstat {base}...{head}` and return a stats dict.

    Returns:
        {
          "base": base, "head": head,
          "files_changed": int, "insertions": int, "deletions": int,
          "numstat_raw": str,  # raw stdout, truncated to 20000 chars
          "ok": bool,          # git exited 0
          "degraded": bool,    # NOT ok OR (files_changed == 0 and ins+del == 0)
          "reason": str | None,  # "git-failed" / "empty-diff" / None
        }
    """
    _git = run_git or _default_run_git
    rc, stdout, _stderr = _git(["git", "diff", "--numstat", f"{base}...{head}"])
    numstat_raw = stdout[:_MAX_NUMSTAT_CHARS]

    if rc != 0:
        return {
            "base": base,
            "head": head,
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "numstat_raw": numstat_raw,
            "ok": False,
            "degraded": True,
            "reason": "git-failed",
        }

    files_changed, ins, dels = _parse_numstat(stdout)

    if files_changed == 0 and ins == 0 and dels == 0:
        return {
            "base": base,
            "head": head,
            "files_changed": 0,
            "insertions": 0,
            "deletions": 0,
            "numstat_raw": numstat_raw,
            "ok": True,
            "degraded": True,
            "reason": "empty-diff",
        }

    return {
        "base": base,
        "head": head,
        "files_changed": files_changed,
        "insertions": ins,
        "deletions": dels,
        "numstat_raw": numstat_raw,
        "ok": True,
        "degraded": False,
        "reason": None,
    }


# ---------- capture ----------


def capture_proof(
    base: str,
    head: str,
    angle_responses: list,
    *,
    root: "Path | None" = None,
    run_git: "Callable | None" = None,
    now_iso: "str | None" = None,
) -> dict:
    """Capture per-round proof artifact under <root>/<head>/.

    Writes:
        <root>/<head>/numstat.txt
        <root>/<head>/transcripts.json
        <root>/<head>/meta.json   ← load-bearing

    Returns the meta dict augmented with "proof_dir".
    A meta-write OSError returns degraded=True, reason="capture-write-failed".
    Zero angle_responses returns degraded=True, reason="no-review-angles" —
    proof-of-REVIEW requires at least one angle to have actually run; a
    non-empty diff alone (nm["degraded"] is False) is not evidence a review
    happened (review finding on PR #109: an empty angle_responses list on a
    real diff previously still yielded a non-degraded, gate-passing digest).
    """
    nm = resolve_numstat(base, head, run_git=run_git)
    if not nm["degraded"] and len(angle_responses) == 0:
        nm = {**nm, "degraded": True, "reason": "no-review-angles"}
    proof_root = root if root is not None else default_proof_root()
    proof_dir = proof_root / head
    try:
        proof_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {
            "degraded": True,
            "reason": "capture-write-failed",
            "proof_dir": str(proof_dir),
        }

    # --- numstat.txt (best-effort) ---
    try:
        (proof_dir / "numstat.txt").write_text(nm["numstat_raw"], encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"review_proof: warning: could not write numstat.txt: {exc}\n")

    # --- transcripts.json (best-effort) ---
    transcripts = []
    for resp in angle_responses:
        raw = str(resp)
        transcripts.append(raw[:_MAX_TRANSCRIPT_CHARS])
    try:
        (proof_dir / "transcripts.json").write_text(
            json.dumps(transcripts, ensure_ascii=False), encoding="utf-8"
        )
    except OSError as exc:
        sys.stderr.write(f"review_proof: warning: could not write transcripts.json: {exc}\n")

    # --- meta.json (load-bearing) ---
    captured_at = now_iso or datetime.now(tz=timezone.utc).isoformat()
    meta = {
        "base": base,
        "head": head,
        "files_changed": nm["files_changed"],
        "insertions": nm["insertions"],
        "deletions": nm["deletions"],
        "degraded": nm["degraded"],
        "reason": nm["reason"],
        "angle_count": len(angle_responses),
        "captured_at": captured_at,
    }
    try:
        (proof_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # Fail-closed: meta write failure → caller blocks convergence
        return {
            "degraded": True,
            "reason": "capture-write-failed",
            "proof_dir": str(proof_dir),
        }

    meta["proof_dir"] = str(proof_dir)
    return meta


# ---------- gate predicate ----------


def proof_present_and_nonempty(head: str, *, root: "Path | None" = None) -> bool:
    """Gate predicate — True iff a valid, non-empty proof artifact exists for head.

    Five-way fail-closed AND:
    1. head is truthy
    2. meta.json exists and parses as JSON
    3. meta["head"] == head  (bound to THIS head, not stale)
    4. meta["degraded"] is not True
    5. (meta["files_changed"] or 0) > 0

    Never raises. Any miss → False.
    """
    try:
        if not head:
            return False
        proof_root = root if root is not None else default_proof_root()
        meta_path = proof_root / head / "meta.json"
        if not meta_path.exists():
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            return False
        if meta.get("head") != head:
            return False
        if meta.get("degraded") is True:
            return False
        if (meta.get("files_changed") or 0) <= 0:
            return False
        return True
    except Exception:
        return False


# ---------- sentinel ----------


def empty_diff_sentinel() -> dict:
    """Return a degraded finding with source='empty-diff'.

    Delegates to review_merge._unparseable_finding so the existing
    is_degraded_review predicate covers it with no edit.
    """
    import review_merge  # local import to avoid circular deps
    return review_merge._unparseable_finding(source="empty-diff")


# ---------- digest ----------


def format_proof_digest(
    meta: dict,
    angle_finding_counts: "list[tuple[str, int]] | None" = None,
) -> str:
    """Render the compact PII-light digest for appending to a PR comment.

    Non-degraded (head is the FULL SHA — currency compare is exact-match; a
    truncated head would be prefix-grindable, round-2 finding):
        <sub>proof: base `abc1234` · head `<full-sha>` · 7 files +123 −45 · angles [correctness:2, edge:0]</sub>

    Degraded:
        <sub>proof: ⚠️ DEGRADED (empty-diff) — review refused convergence</sub>
    """
    if meta.get("degraded"):
        reason = meta.get("reason") or "degraded"
        return f"<sub>proof: ⚠️ DEGRADED ({reason}) — review refused convergence</sub>"

    base_sha = str(meta.get("base") or "")[:7]
    head_sha = str(meta.get("head") or "")
    files = meta.get("files_changed", 0)
    ins = meta.get("insertions", 0)
    dels = meta.get("deletions", 0)

    parts = [f"proof: base `{base_sha}` · head `{head_sha}` · {files} files +{ins} −{dels}"]

    if angle_finding_counts:
        angles_str = ", ".join(f"{label}:{count}" for label, count in angle_finding_counts)
        parts.append(f"angles [{angles_str}]")

    return "<sub>" + " · ".join(parts) + "</sub>"


# ---------- posted-comment detector (enforce-review-proof) ----------

# Built to match format_proof_digest's exact output (verified against the live
# function). Non-degraded: `proof: base \`abc1234\` · head \`<full-sha>\` · …`.
# Degraded: `proof: ⚠️ DEGRADED (reason) — …`.
_DIGEST_HEAD_RE = re.compile(r"proof:\s*base\s*`[^`]*`\s*·\s*head\s*`([0-9a-fA-F]+)`")
_DEGRADED_RE = re.compile(r"proof:\s*⚠️\s*DEGRADED")


def _default_comments_fn(pr_url: str) -> list:
    """Live default: `gh pr view <pr_url> --json comments` → list of
    {"author": <login>, "body": <str>} dicts (every PR-level comment).

    The author login rides along so proof_comment_on_head can enforce digest
    authenticity (review finding on PR #109: bodies alone let ANY commenter
    fabricate a passing digest). NOT guaranteed not to raise here — the CALLER
    (proof_comment_on_head) wraps this in try/except and fails closed. Chosen
    over `gh api .../issues/{n}/comments` (OQ1): single call, full bodies, no
    pagination, parity with the gate's `gh pr view --json` idiom.
    """
    out = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "comments"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh pr view failed")
    payload = json.loads(out.stdout)
    comments = payload.get("comments") or []
    return [
        {
            "author": ((c.get("author") or {}).get("login") or ""),
            "body": c.get("body", ""),
        }
        for c in comments
        if isinstance(c, dict)
    ]


def _default_self_login_fn() -> "str | None":
    """Live gh-authenticated login (mirrors human_approval's self_login_fn shape)."""
    out = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "gh api user failed")
    return out.stdout.strip() or None


def _trusted_digest_authors(config, self_login_fn) -> frozenset:
    """Lowercased logins whose posted digests count as proof.

    DELIBERATELY NARROWER than human_approval.automation_identities (review
    finding on PR #109, round 2): the digest allowlist is the DUAL of the
    approval denylist — extra members make a denylist stricter but make THIS
    allowlist weaker. The hardcoded Copilot/native-bot floor is excluded: those
    identities never legitimately post digests (only the framework's gh self
    login does, via post_codereview_comment), and on expects_copilot=true repos
    Copilot's comment bodies are model-generated from attacker-influencible PR
    context — trusting them would let a prompt-injected Copilot comment mint
    proof. Trusted = the gh self login + config review.automation_identities
    extras (a team that posts digests from a dedicated identity names it
    there). An unresolvable self login only SHRINKS the set — the framework's
    own digests stop matching → fail-closed (dual of human_approval's F2,
    where a shrunken set fails OPEN and must hard-abort).
    """
    try:
        self_login = (self_login_fn or _default_self_login_fn)()
    except Exception:
        self_login = None
    members = set()
    if isinstance(self_login, str) and self_login:
        members.add(self_login.lower())
    review = config.get("review") if isinstance(config, dict) else None
    extra = review.get("automation_identities") if isinstance(review, dict) else None
    if isinstance(extra, list):
        for login in extra:
            if isinstance(login, str) and login:
                members.add(login.lower())
    return frozenset(members)


def proof_comment_on_head(pr_url, head, *, comments_fn=None, config=None,
                          self_login_fn=None) -> bool:
    """True iff a TRUSTED-authored PR comment carries a non-degraded
    format_proof_digest whose parsed head equals the query head EXACTLY.
    Fresh-checkout safe (the gate's arm — reads the posted comment, not the
    gitignored local artifact). NEVER raises — any miss/error → False.

    Authenticity contract (review finding on PR #109): a digest only counts when
    its comment's author is in _trusted_digest_authors (the automation set that
    actually posts digests) — a drive-by commenter pasting a matching digest does
    NOT pass. comments_fn items are {"author", "body"} dicts; a bare-string item
    carries no author and is IGNORED (fail-closed), never trusted by shape.

    Currency contract: the parsed digest head must equal the query head EXACTLY
    (behavior 9) — the comment-arm analogue of proof_present_and_nonempty's
    meta["head"] == head rule. Never a prefix: a 7-hex prefix is grindable in
    seconds (lucky-commit), minting proof for an unreviewed head off an older
    digest (round-2 finding; format_proof_digest emits the full head). Format
    coupling: matched per-line; a multi-line digest shape fails *closed*.
    """
    try:
        if not head or not pr_url:
            return False
        want = str(head)
        fn = comments_fn or _default_comments_fn
        items = fn(pr_url)
        if not isinstance(items, list):
            return False
        trusted = None  # built lazily — the self-login lookup runs ONLY when a
        # digest-bearing candidate needs an author check (a garbage authored
        # comment must not trigger a live `gh api user` — round-2 finding)
        for item in items:
            if not isinstance(item, dict):
                continue  # authorless (legacy bare-string) item — never trusted
            author = item.get("author")
            if not isinstance(author, str) or not author:
                continue
            body = item.get("body")
            text = body if isinstance(body, str) else str(body or "")
            hit = False
            for line in text.splitlines():
                if _DEGRADED_RE.search(line):
                    continue  # ⚠️ DEGRADED digest is NOT proof
                m = _DIGEST_HEAD_RE.search(line)
                if m and m.group(1) == want:
                    hit = True
                    break
            if not hit:
                continue
            if trusted is None:
                trusted = _trusted_digest_authors(config, self_login_fn)
            if author.lower() in trusted:
                return True
        return False
    except Exception:
        return False


def proof_ok(head, *, pr_url=None, root=None, comments_fn=None, config=None,
             self_login_fn=None) -> bool:
    """Shared head-bound predicate — the single source BOTH call sites reuse.

    True iff EITHER:
      - the local artifact proves it: proof_present_and_nonempty(head, root=root)
        (the loop's arm — local artifact present), OR
      - the posted comment proves it: proof_comment_on_head(pr_url, head,
        comments_fn=comments_fn) (the gate's arm — fresh checkout, comment only).

    Loop call sites pass root; gate call sites pass pr_url (+ comments_fn).
    config/self_login_fn feed the comment arm's trusted-author set. Both arms
    absent → False. NEVER raises (both arms are themselves fail-closed).
    """
    try:
        if proof_present_and_nonempty(head, root=root):
            return True
        if pr_url is not None:
            return proof_comment_on_head(
                head=head, pr_url=pr_url, comments_fn=comments_fn,
                config=config, self_login_fn=self_login_fn,
            )
        return False
    except Exception:
        return False
