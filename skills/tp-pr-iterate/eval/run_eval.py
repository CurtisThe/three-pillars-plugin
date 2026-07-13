"""Eval harness for the `classifier_judge` Sonnet prompt.

Reads `eval/comments.jsonl`, calls `classifier_judge.build_prompt` to
construct one prompt per entry, invokes Sonnet (via nested `claude -p
--model sonnet --allowedTools ""` to inherit the operator's session
auth), parses the response with `classifier_judge.parse_response`, and
reports two accuracy metrics:

  - structural_minor_accuracy: of entries with ground_truth in
    {"structural","minor"}, fraction where predicted verdict == ground_truth.
    Threshold: ≥ 0.90.

  - unclear_as_structural_rate: of entries with ground_truth == "unclear",
    fraction where predicted verdict == "structural" (safety bias — when
    in doubt, treat as needing a fix-round, not as a skip).
    Threshold: ≥ 0.80.

Exit code 0 if both thresholds met; 1 otherwise.

Run from repo root:

    python skills/tp-pr-iterate/eval/run_eval.py

(The plan's `python -m skills.tp_pr_iterate.eval.run_eval` is interpreted as
intent — the actual directory name uses dashes, so module-style import
doesn't apply. Use the path form above.)
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import classifier_judge  # noqa: E402

EVAL_PATH = HERE / "comments.jsonl"

STRUCTURAL_MINOR_THRESHOLD = 0.90
UNCLEAR_AS_STRUCTURAL_THRESHOLD = 0.80

# `claude -p` per-call timeout. Sonnet inference + Claude Code spin-up
# takes ~5-15s typically; 60s gives a safe ceiling.
CALL_TIMEOUT_S = 60
MAX_WORKERS = 8


@dataclass
class _Comment:
    """Duck-type matching what build_prompt reads off a comment."""

    id: int
    body: str
    path: str
    user: str


def _invoke_sonnet(prompt: str) -> str:
    """Run `claude -p --model sonnet` with the prompt on stdin.

    Returns the raw stdout text. Raises CalledProcessError or
    TimeoutExpired on failure.
    """
    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet", "--allowedTools", ""],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=CALL_TIMEOUT_S,
        check=True,
    )
    return result.stdout


def _classify_one(entry: dict) -> tuple[dict, str | None, str | None]:
    """Build prompt, call Sonnet, parse — return (entry, predicted, error).

    On success: (entry, "structural"|"minor"|"unclear", None).
    On failure: (entry, None, error_msg).
    """
    comment = _Comment(
        id=int(entry["comment_id"]),
        body=entry["body"],
        path=entry.get("path", "?"),
        user=entry.get("reviewer", "?"),
    )
    diff_context = {comment.path: entry.get("diff_hunk", "")}
    prompt = classifier_judge.build_prompt([comment], diff_context)
    try:
        raw = _invoke_sonnet(prompt)
        parsed = classifier_judge.parse_response(raw)
        if not parsed:
            return entry, None, "parse_response returned empty list"
        if len(parsed) != 1:
            return entry, None, f"expected 1 verdict, got {len(parsed)}"
        return entry, parsed[0]["verdict"], None
    except subprocess.TimeoutExpired:
        return entry, None, f"timeout after {CALL_TIMEOUT_S}s"
    except subprocess.CalledProcessError as e:
        return entry, None, f"subprocess error: {e.stderr[:200]}"
    except Exception as e:  # noqa: BLE001
        return entry, None, f"{type(e).__name__}: {e}"


def _read_entries() -> list[dict]:
    return [
        json.loads(line)
        for line in EVAL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _score(results: list[tuple[dict, str | None, str | None]]) -> dict:
    """Compute the two threshold metrics + per-entry breakdown."""
    sm_total = 0
    sm_correct = 0
    unclear_total = 0
    unclear_as_structural = 0
    errors: list[tuple[int, str]] = []
    mislabeled: list[tuple[int, str, str]] = []  # (comment_id, gt, predicted)

    for entry, predicted, err in results:
        cid = int(entry["comment_id"])
        gt = entry["ground_truth"]
        if err is not None:
            errors.append((cid, err))
            continue
        if gt in ("structural", "minor"):
            sm_total += 1
            if predicted == gt:
                sm_correct += 1
            else:
                mislabeled.append((cid, gt, predicted or "?"))
        elif gt == "unclear":
            unclear_total += 1
            if predicted == "structural":
                unclear_as_structural += 1
            elif predicted != "unclear":
                # unclear → minor is the bad case (silently skipped).
                # unclear → unclear is acceptable (escalates to human).
                # We only count "structural" as the safety-bias-met case.
                pass

    sm_acc = sm_correct / sm_total if sm_total else 0.0
    uas_rate = (
        unclear_as_structural / unclear_total if unclear_total else 0.0
    )

    return {
        "structural_minor_accuracy": sm_acc,
        "structural_minor_correct": sm_correct,
        "structural_minor_total": sm_total,
        "unclear_as_structural_rate": uas_rate,
        "unclear_as_structural_count": unclear_as_structural,
        "unclear_total": unclear_total,
        "errors": errors,
        "mislabeled": mislabeled,
    }


def _print_report(scores: dict, n_entries: int) -> bool:
    """Pretty-print the scoring report. Returns True if both thresholds met."""
    sm_pass = scores["structural_minor_accuracy"] >= STRUCTURAL_MINOR_THRESHOLD
    uas_pass = (
        scores["unclear_as_structural_rate"]
        >= UNCLEAR_AS_STRUCTURAL_THRESHOLD
    )

    print(f"== eval: {n_entries} entries ==")
    print(
        f"structural/minor accuracy: "
        f"{scores['structural_minor_correct']}/{scores['structural_minor_total']}"
        f" = {scores['structural_minor_accuracy']:.1%} "
        f"(threshold ≥{STRUCTURAL_MINOR_THRESHOLD:.0%}) "
        f"{'PASS' if sm_pass else 'FAIL'}"
    )
    print(
        f"unclear-as-structural rate: "
        f"{scores['unclear_as_structural_count']}/{scores['unclear_total']}"
        f" = {scores['unclear_as_structural_rate']:.1%} "
        f"(threshold ≥{UNCLEAR_AS_STRUCTURAL_THRESHOLD:.0%}) "
        f"{'PASS' if uas_pass else 'FAIL'}"
    )

    if scores["errors"]:
        print(f"\nerrors ({len(scores['errors'])}):")
        for cid, msg in scores["errors"]:
            print(f"  [{cid}] {msg}")

    if scores["mislabeled"]:
        print(f"\nmislabeled ({len(scores['mislabeled'])}):")
        for cid, gt, pred in scores["mislabeled"]:
            print(f"  [{cid}] ground_truth={gt} predicted={pred}")

    return sm_pass and uas_pass


def main() -> int:
    entries = _read_entries()
    print(f"running {len(entries)} entries via claude -p (parallelism={MAX_WORKERS})...")

    results: list[tuple[dict, str | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(_classify_one, e): e for e in entries}
        for i, fut in enumerate(as_completed(futures), start=1):
            res = fut.result()
            results.append(res)
            entry, predicted, err = res
            cid = entry["comment_id"]
            gt = entry["ground_truth"]
            tag = err or f"predicted={predicted}"
            print(f"  [{i}/{len(entries)}] cid={cid} gt={gt} → {tag}")

    scores = _score(results)
    both_pass = _print_report(scores, len(entries))
    return 0 if both_pass else 1


if __name__ == "__main__":
    sys.exit(main())
