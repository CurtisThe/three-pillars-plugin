"""converge.py — the convergence-ONLY Tier-7 "reviewed-stable" finish primitive.

Invoked when a `/tp-pr-iterate` / `/tp-run-full-design` Tier-7 round is already
**structurally clean**, to finalize the two-stable `[code-review-only]` state in a
single load-bearing, order-sensitive call. It **composes** the existing primitives
(no forks) and shells the existing `run_round.py`:

    read angle files → merge_codereview_angles  (B1 guard: refuse non-clean rounds)
    → review_proof.capture_proof
    → review_proof.format_proof_digest
    → review_merge.post_codereview_comment   (trusted author; the LAST head-binding action)
    → seed the UNTRACKED iterate-state.v1.json (last_verdict="minor-only")
    → shell run_round.py (paths str()-ed, decisions_path OMITTED, config explicit)
    → convergence_proof.non_degraded_proof_on_head  (independent PASS oracle)
    → emit terminal JSON; HEAD invariant across the whole call.

Composition-only: NO second implementation of the digest format, the head-bound
predicate, or the round decision. `review_proof.py` (at the 500-line cap) gets zero
additions. Stdlib + local scripts only (C1-clean; no anthropic, no claude subprocess).
Every external interaction is behind an injectable seam so the unit tests run with no
live `gh` and no network. The CLI `main()` lives in the sibling `converge_cli.py`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
_SHARED = SCRIPTS_DIR.parent.parent / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import review_merge  # noqa: E402
import review_proof  # noqa: E402
import convergence_proof  # noqa: E402 — skills/_shared, on path via the shim above

RUN_ROUND_PY = SCRIPTS_DIR / "run_round.py"


# ---------- digest label-counts (trap c) ----------


def parse_label_counts(args: "list[str] | None") -> "list[tuple[str, int]]":
    """Parse `--label-count L:N` args into a `list[tuple[str, int]]`.

    Trap (c): `review_proof.format_proof_digest(meta, angle_finding_counts)` takes
    a **list of `(label, count)` tuples**, NOT a dict — passing a dict would make
    the digest's `for label, count in ...` unpack the dict keys. Each arg is
    `LABEL:COUNT`; the LAST colon separates the int count (labels never contain a
    colon here, but rpartition is robust if one did). A malformed arg (no colon,
    empty label, or non-int count) raises `ValueError` with a clear message.
    """
    out: "list[tuple[str, int]]" = []
    for raw in args or []:
        if ":" not in raw:
            raise ValueError(f"--label-count must be LABEL:COUNT, got {raw!r}")
        label, _, count_str = raw.rpartition(":")
        label = label.strip()
        if not label:
            raise ValueError(f"--label-count LABEL must be non-empty, got {raw!r}")
        try:
            count = int(count_str.strip())
        except ValueError:
            raise ValueError(
                f"--label-count COUNT must be an integer, got {count_str!r} in {raw!r}"
            )
        out.append((label, count))
    return out


def label_counts_to_json(counts: "list[tuple[str, int]]") -> "list[list]":
    """Serialize label-counts for a JSON boundary (state file / logged verdict).

    Tuples do not survive a JSON round-trip (they become lists), so cross-boundary
    counts are stored as `[[label, count], …]` and reconstructed as tuples on read.
    """
    return [[label, count] for label, count in (counts or [])]


def label_counts_from_json(data) -> "list[tuple[str, int]]":
    """Reconstruct label-counts as a `list[tuple[str, int]]` from JSON-decoded data.

    Accepts the list-of-pairs form (`[[label, count], …]`) written by
    `label_counts_to_json`, OR a plain dict of `{label: count}` — both normalize to
    a list of tuples so the result is never passed to `format_proof_digest` as a
    dict (trap c). `None` / empty → `[]`.
    """
    if not data:
        return []
    if isinstance(data, dict):
        return [(str(label), int(count)) for label, count in data.items()]
    out: "list[tuple[str, int]]" = []
    for pair in data:
        label, count = pair
        out.append((str(label), int(count)))
    return out


# ---------- run_round stdin payload (trap b) ----------


def build_run_round_stdin(
    state_path,
    head_sha,
    codereview_findings,
    review_proof_root,
    review_base,
    config,
    pr_url,
) -> dict:
    """Build the JSON-serializable stdin object for `run_round.py`.

    Trap (b): `review_proof_root` (from `default_proof_root()`, a `PosixPath`) and
    `state_path` are `str()`-converted so `json.dumps(payload)` never raises
    ``TypeError: Object of type PosixPath is not JSON serializable`` (hit live).

    Trap (d) shape: `unresolved_actionable=0`, `ci_rollup=[]`, `reviewed=None`
    (null is OK on `expects_copilot=false`), and `decisions_path` is **omitted**
    entirely (its readiness write dirties the tree / risks moving HEAD).
    `codereview_findings` is the REAL `merge_codereview_angles(...)` result (`[]`
    on a clean round) — never the `merge_codereview_angles([])` NO-ANGLES sentinel.
    """
    return {
        "state_path": str(state_path),
        "head_sha": head_sha,
        "codereview_findings": codereview_findings,
        "reviewed": None,
        "unresolved_actionable": 0,
        "ci_rollup": [],
        "config": config,
        "review_proof_root": str(review_proof_root),
        "review_base": review_base,
        "pr_url": pr_url,
    }


# ---------- angle files + convergence-only guard (B1, B5) ----------


def _read_angle_texts(angle_files) -> "list[str]":
    """Read each `--angle-file` path's raw text (files, never a shell heredoc —
    trap d: command substitution would execute backticks → sentinel findings)."""
    texts: "list[str]" = []
    for p in angle_files or []:
        texts.append(Path(p).read_text(encoding="utf-8"))
    return texts


def guard_refusal(findings: "list[dict]") -> "str | None":
    """Return a refusal diagnostic when a round is NOT structurally clean, else None.

    B1 / B5: `converge.py` is the *finish*, not the fix loop. It proceeds ONLY on a
    genuinely clean round (`merge_codereview_angles(...) == []`). Any non-empty
    result refuses:
      - real structural findings → point at the fix loop (`run_round.py` / `/tp-pr-fix`);
      - degraded sentinels (`no-angles` / unparseable) → never a false convergence.
    """
    if not findings:
        return None
    if review_merge.is_degraded_review(findings):
        return (
            "converge.py refuses: the review is DEGRADED (no angles ran, or an angle "
            "failed to parse) — this is NOT a clean round. Re-run the review fan-out on "
            "this head and write real angle replies to the --angle-file paths, then "
            "converge; never converge on an unparseable/no-angles review."
        )
    return (
        f"converge.py refuses: {len(findings)} structural finding(s) present — this is a "
        "FIX round, not a finish. Run the fix loop (run_round.py / /tp-pr-fix) until the "
        "round is structurally clean, then re-run converge.py."
    )


# ---------- helpers ----------


def _emit(out, obj: dict) -> None:
    out.write(json.dumps(obj) + "\n")


def _diag(err, msg: str) -> None:
    err.write(msg + "\n")


def _git_head(run_git) -> "str | None":
    """`git rev-parse HEAD` via the injectable git seam; None on any failure."""
    rc, stdout, _stderr = (run_git or review_proof._default_run_git)(
        ["git", "rev-parse", "HEAD"]
    )
    if rc != 0:
        return None
    return stdout.strip() or None


# ---------- ordered convergence orchestration (B2, B6, B7) ----------

# Exit codes: 0 converged · 2 guard-refusal (not a clean round) · 3 fail-closed
# (degraded capture / post failure / non-PASS oracle / run_round not converged /
# HEAD moved). Any non-zero leaves the working tree clean (untracked artifacts only).
_EXIT_CONVERGED = 0
_EXIT_REFUSED = 2
_EXIT_BLOCKED = 3


def converge(
    *,
    base,
    head,
    pr_url,
    config,
    angle_files,
    label_counts=None,
    state_path=None,
    review_base=None,
    proof_root=None,
    post_fn=None,
    comments_fn=None,
    self_login_fn=None,
    run_git=None,
    run_round_fn=None,
    derive_base_ref_fn=None,
    repo_root=None,
    now_iso=None,
    out=None,
    err=None,
) -> int:
    """Finalize a structurally-clean round to two-stable `[code-review-only]`.

    See the module docstring for the load-bearing ordered seam. Returns an exit
    code; emits the terminal JSON on `out` (stdout) and diagnostics on `err`
    (stderr). HEAD is invariant across the whole call. Every external interaction
    is behind an injected seam so the unit tests run hermetically.
    """
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr

    # 1. Read angle files → merge findings.
    texts = _read_angle_texts(angle_files)
    findings = review_merge.merge_codereview_angles(texts)

    # 2. Convergence-only guard (B1, B5): refuse non-clean / empty-angle rounds.
    refusal = guard_refusal(findings)
    if refusal is not None:
        _diag(err, refusal)
        return _EXIT_REFUSED

    return _finish_clean(
        base=base, head=head, pr_url=pr_url, config=config, texts=texts,
        findings=findings, label_counts=label_counts, state_path=state_path,
        review_base=review_base, proof_root=proof_root, post_fn=post_fn,
        comments_fn=comments_fn, self_login_fn=self_login_fn, run_git=run_git,
        run_round_fn=run_round_fn, derive_base_ref_fn=derive_base_ref_fn,
        repo_root=repo_root, now_iso=now_iso, out=out, err=err,
    )


def _seed_state(state_path: Path, head: str, *, now_iso=None) -> None:
    """Write the UNTRACKED iterate-state.v1.json used by the shelled run_round.py.

    Seeds `last_verdict="minor-only"` (the convergence-eligibility precondition) and
    `last_codereview_head_sha=head` (so `_independent_review_ran`'s current-head match
    holds) plus the required loop-state fields. The file lives under the gitignored
    review-proof root, so writing it never dirties the tree (No branch mutation).
    """
    now = now_iso or datetime.now(tz=timezone.utc).isoformat()
    state = {
        "phase": "awaiting-copilot",
        "iteration": 1,
        "max_iterations": 8,
        "max_wall_clock_sec": 14400,
        "started_at": now,
        "transitions": [],
        "cumulative_diff_lines": 0,
        "original_diff_lines": 100,
        "consecutive_structural_rounds": 0,
        "last_loop_sha": None,
        "last_comment_seen_at": None,
        "last_verdict": "minor-only",
        "last_codereview_head_sha": head,
        "last_codereview_findings": [],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _default_run_round(stdin: dict) -> dict:
    """Shell the real run_round.py, JSON on stdin → parsed envelope on stdout."""
    proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
        [sys.executable, str(RUN_ROUND_PY)],
        input=json.dumps(stdin).encode(),
        capture_output=True,
    )
    try:
        return json.loads(proc.stdout.decode().strip())
    except Exception:
        return {
            "converged": False, "terminal": None,
            "_stdout": proc.stdout.decode(errors="replace"),
            "_stderr": proc.stderr.decode(errors="replace"),
        }


def _blocked_reason(rr_converged, proof_pass, head_stable, envelope) -> str:
    if not head_stable:
        return "HEAD moved during convergence (a commit landed after the proof comment)"
    if not proof_pass:
        return ("no non-degraded trusted proof digest on head "
                "(pred_review_proof_on_head != PASS)")
    if not rr_converged:
        detail = (envelope.get("not_converged_reason")
                  or envelope.get("terminal") or "run_round did not converge")
        return f"run_round did not reach two-stable ({detail})"
    return "unknown"


def _finish_clean(
    *, base, head, pr_url, config, texts, findings, label_counts, state_path,
    review_base, proof_root, post_fn, comments_fn, self_login_fn, run_git,
    run_round_fn, derive_base_ref_fn, repo_root, now_iso, out, err,
) -> int:
    """The clean-round finish: capture → digest → post → seed → run_round → oracle
    → terminal JSON. Post is the LAST head-binding action; HEAD is invariant."""
    review_base = review_base or base
    proof_root = Path(proof_root) if proof_root is not None else review_proof.default_proof_root()
    state_path = (
        Path(state_path) if state_path is not None
        else proof_root / "iterate-state.v1.json"
    )

    head_before = _git_head(run_git)

    # 3. capture_proof — the untracked per-head artifact (numstat + transcripts + meta).
    meta = review_proof.capture_proof(
        base, head, texts, root=proof_root, run_git=run_git, now_iso=now_iso)

    # 4. digest — full head SHA; label-counts as a list of tuples.
    digest = review_proof.format_proof_digest(meta, label_counts)

    # B7: a degraded capture (empty/failed diff, no-review-angles) fails closed —
    # NO post, no false converged, tree clean (the artifact is untracked).
    if meta.get("degraded"):
        _diag(err, f"converge.py blocked: degraded proof capture ({meta.get('reason')}).")
        _emit(out, {"converged": False, "terminal": None, "head_sha": head,
                    "proof_verified": False, "reason": "degraded-capture",
                    "digest": digest})
        return _EXIT_BLOCKED

    # 5. Post the proof comment BEFORE run_round — the LAST head-binding action.
    posted = review_merge.post_codereview_comment(
        pr_url, findings, head_sha=head, digest=digest, post_fn=post_fn)
    if not posted:
        _diag(err, "converge.py blocked: proof-comment post failed (gh).")
        _emit(out, {"converged": False, "terminal": None, "head_sha": head,
                    "proof_verified": False, "reason": "post-failed"})
        return _EXIT_BLOCKED

    # 6. Seed/update the UNTRACKED iterate-state.v1.json.
    _seed_state(state_path, head, now_iso=now_iso)

    # 7. Shell run_round.py (paths str()-ed, decisions_path OMITTED, config explicit).
    stdin = build_run_round_stdin(
        state_path=state_path, head_sha=head, codereview_findings=findings,
        review_proof_root=proof_root, review_base=review_base, config=config,
        pr_url=pr_url)
    envelope = (run_round_fn or _default_run_round)(stdin)
    rr_converged = (bool(envelope.get("converged"))
                    and "two-stable" in str(envelope.get("terminal") or ""))

    # 8. Independent oracle — the SAME predicate the merge gate reads.
    proof_pass = convergence_proof.non_degraded_proof_on_head(
        pr_url, head, config=config, comments_fn=comments_fn,
        self_login_fn=self_login_fn, run_git=run_git,
        derive_base_ref_fn=derive_base_ref_fn, repo_root=repo_root)

    head_after = _git_head(run_git)
    head_stable = head_before == head_after

    if not (rr_converged and proof_pass and head_stable):
        reason = _blocked_reason(rr_converged, proof_pass, head_stable, envelope)
        _diag(err, f"converge.py blocked: {reason}.")
        _emit(out, {"converged": False, "terminal": envelope.get("terminal"),
                    "head_sha": head, "proof_verified": bool(proof_pass),
                    "reason": reason})
        return _EXIT_BLOCKED

    # 9. Terminal verdict — byproduct-only, proof-verified. HEAD unchanged throughout.
    terminal = envelope.get("terminal") or "two-stable [code-review-only]"
    _emit(out, {"converged": True, "terminal": terminal, "head_sha": head,
                "proof_verified": True})
    return _EXIT_CONVERGED


if __name__ == "__main__":
    from converge_cli import main  # arg-parse lives in the sibling CLI module

    sys.exit(main())
