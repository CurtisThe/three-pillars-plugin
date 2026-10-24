"""converge_rounddir — the `converge.py --round-dir R` branch.

design: iterate-convergence-budget (Task 6.3)

The round dir's `angles.json` manifest is the path authority: state path, proof
root, base, head, PR url, round and ordinal come only from it, never from
`default_proof_root()` or cwd. Before any seed it refuses (exit 2, one JSON
line on stdout):
- `manifest-invalid` — no readable manifest;
- `state-path-mismatch` — a `--state` that resolves elsewhere;
- `state-bootstrapped-mid-loop` — `round > 1` and the state file is absent,
  zero-length or unparseable, so a lost state stops the loop instead of
  resetting the cap;
- `no-confirmer` — no confirmer angle on Claude left a parseable reply (a
  finder-only `[]` never converges);
- `findings-missing` — no `R/tail/findings.json` (the reproducer's output);
- `unparseable-review-angle` — a reply that fails the strict one-object contract
  beside a clean `findings.json` (defence in depth: a consistent round tail already
  turns it into a sentinel), so it is never digested as `:0`.
Then `converge.guard_refusal` refuses only on blocking findings; non-blocking
notes do not block. The finish itself is `converge._finish_clean`, with
`round`, `ordinal` and `class_log_path` added to the run_round stdin and
`class_tally` added to the terminal JSON.
An identity stop (`bot-auth-unavailable`, `proof-author-untrusted`) from the
finish is returned as-is (exit 3), never turned into an evidence-complete accept.

Stdlib only.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import angles  # noqa: E402
import closeout_gate  # noqa: E402
import converge  # noqa: E402
import evidence_complete  # noqa: E402
import finder_round  # noqa: E402
import finding_class  # noqa: E402
import proof_post  # noqa: E402
import round_scratch  # noqa: E402
from review_merge import parse_codereview_result  # noqa: E402

_FINISH_SEAMS = ("post_fn", "comments_fn", "self_login_fn", "run_git",
                 "derive_base_ref_fn", "repo_root", "now_iso", "ready_ping_fn")


class _Refusal(Exception):
    pass


def _refuse(out, reason: str, detail: str = "") -> int:
    out.write(json.dumps({"converged": False, "terminal": "needs-human-attention",
                          "reason": reason, "detail": detail}) + "\n")
    return converge._EXIT_REFUSED


def _load(round_dir: Path) -> dict:
    try:
        m = json.loads((round_dir / round_scratch.MANIFEST).read_text(encoding="utf-8"))
        paths = m["paths"]
        for key in ("state_path", "proof_root"):
            if not isinstance(paths[key], str):
                raise TypeError(f"paths.{key}")
        for key in ("base", "head", "pr_url", "ordinal"):
            if not isinstance(m[key], str):
                raise TypeError(key)
        if not isinstance(m["round"], int):
            raise TypeError("round")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _Refusal("manifest-invalid", str(exc)) from exc
    return m


def _findings(round_dir: Path) -> list:
    try:
        data = json.loads((round_dir / round_scratch.TAIL / "findings.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _Refusal("findings-missing", str(exc)) from exc
    if not isinstance(data, list):
        raise _Refusal("findings-missing", "findings.json is not a list")
    return data


def _state_lost(state_path: Path) -> bool:
    """Absent, zero-length or not a JSON object: a lost state, never re-seeded mid-loop.

    Parity with `run_round_boundary.refuse_mid_loop_bootstrap` (absent or zero-length),
    plus an unparseable file, which `converge._seed_state` would otherwise read as
    `{}` and overwrite with a round-0 state that run_round.py can no longer refuse.
    """
    try:
        doc = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    return not isinstance(doc, dict)


def _accept(out, manifest: dict, reason: str) -> int:
    """§D8: the evidence is in, the bookkeeping is not → stop at 4 with the accept hint."""
    head = manifest["head"]
    out.write(json.dumps({"converged": False, "terminal": "evidence-complete",
                          "head_sha": head, "reason": reason,
                          "accept_hint": evidence_complete.accept_hint(head, reason)}) + "\n")
    return evidence_complete.EXIT_EVIDENCE


def _check(round_dir: Path, manifest: dict, state_arg) -> list:
    state_path = Path(manifest["paths"]["state_path"])
    if state_arg is not None and Path(state_arg).resolve() != state_path.resolve():
        raise _Refusal("state-path-mismatch", f"--state {state_arg} != {state_path}")
    if manifest["round"] > 1 and _state_lost(state_path):
        raise _Refusal("state-bootstrapped-mid-loop", str(state_path))
    if not angles.confirmer_ran(manifest, round_dir):
        raise _Refusal("no-confirmer", "no confirmer angle on Claude left a parseable reply")
    return _findings(round_dir)


def run(round_dir, *, config, state_arg=None, class_log_path=None, seams=None) -> int:
    """The `--round-dir` finish. Returns converge's exit code."""
    seams = dict(seams or {})
    out = seams.get("out") or sys.stdout
    err = seams.get("err") or sys.stderr
    round_dir = Path(round_dir)
    try:
        manifest = _load(round_dir)
    except _Refusal as exc:  # no manifest → nothing to be complete about
        return _refuse(out, *exc.args)
    gate = closeout_gate.head_refusal(run_git=seams.get("run_git"),
                                      repo_root=seams.get("repo_root"))
    if gate is not None:  # never an evidence-complete accept for an un-archived head
        return converge.emit_head_refusal({**gate, "head_sha": manifest["head"]}, out, err)
    try:
        findings = _check(round_dir, manifest, state_arg)
    except _Refusal as exc:
        # §D8: a bookkeeping refusal on a round whose evidence is in is a terminal.
        if evidence_complete.check(round_dir, run_git=seams.get("run_git"))[0]:
            return _accept(out, manifest, exc.args[0])
        return _refuse(out, *exc.args)
    refusal = converge.guard_refusal(findings)
    if refusal is not None:
        err.write(refusal + "\n")
        return converge._EXIT_REFUSED

    pairs = finder_round.aligned_replies(round_dir)
    texts = [t for _e, t in pairs]
    need = {e["name"] for e in finder_round.parse_required(manifest)}
    parsed = [(e["name"], *parse_codereview_result(t)) for e, t in pairs if e["name"] in need]
    bad = [n for n, _f, ok in parsed if not ok]
    if bad:  # M27: never digest an unparseable reply as `:0` beside a clean findings.json
        return _refuse(out, "unparseable-review-angle", ", ".join(bad))
    counts = {n: len(f) for n, f, _ok in parsed}
    base_fn = seams.get("run_round_fn") or converge._default_run_round
    extra = {"round": manifest["round"], "ordinal": manifest["ordinal"],
             "class_log_path": str(class_log_path) if class_log_path else None}

    def run_round_fn(stdin):
        return base_fn({**stdin, **extra})

    buf = io.StringIO()
    rc = converge._finish_clean(
        base=manifest["base"], head=manifest["head"], pr_url=manifest["pr_url"],
        config=config, texts=texts, findings=findings,
        label_counts=angles.digest_labels(manifest, counts),
        state_path=Path(manifest["paths"]["state_path"]),
        review_base=manifest.get("pr_base", manifest["base"]),
        proof_root=Path(manifest["paths"]["proof_root"]), run_round_fn=run_round_fn,
        out=buf, err=err, **{k: seams.get(k) for k in _FINISH_SEAMS})
    tally = finding_class.tally(findings)
    reasons, stopped = set(), False
    for line in buf.getvalue().splitlines():
        doc = json.loads(line)
        reasons.add(doc.get("reason"))
        stopped = stopped or bool(doc.get("finalizer_stop"))
        out.write(json.dumps({**doc, "class_tally": tally}) + "\n")
    if reasons & proof_post.IDENTITY_STOPS:  # its own terminal (round-topology step 2)
        return rc
    if rc and not stopped and evidence_complete.check(round_dir, run_git=seams.get("run_git"))[0]:
        return _accept(out, manifest, f"finish exit {rc}")
    return rc
