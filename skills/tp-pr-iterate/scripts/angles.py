"""angles — review angles as declared data for /tp-pr-iterate.

design: iterate-convergence-budget (Task 6.1)

Each angle is `{name, prompt, role: finder|confirmer, model}`. The default puts
every angle on Claude Opus as a confirmer (reviews are always Opus). A clean
`[]` round signs the proof only if at least one confirmer angle ran on Claude
and returned a parseable reply (`confirmer_ran`); a finder-only `[]` never
converges.

Stdlib only; computes, never shells out (C1).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from review_merge import parse_codereview_result  # noqa: E402

REVIEW_BAR = ("Only a demonstrated shipped-behaviour defect with a reproducer blocks; "
              "mutation survivors, test-tightening, exotic env, lint-guard bypasses, "
              "style and perf are non-blocking notes.")

ROLES = ("finder", "confirmer")
CLAUDE_MODELS = {"opus", "sonnet", "haiku"}
_NOT_OPUS = ("sonnet", "haiku")

DEFAULT_ANGLES = [
    {"name": "correctness-leak", "role": "confirmer", "model": "opus",
     "prompt": "Hunt fail-closed/correctness leaks: any path to a wrong result, a "
               "non-handled error, an unsafe edge case."},
    {"name": "edge-cases", "role": "confirmer", "model": "opus",
     "prompt": "Boundary/degenerate inputs, ordering dependence, off-by-one, "
               "type-coercion, missing-key, empty-collection behavior."},
    {"name": "test-quality", "role": "confirmer", "model": "opus",
     "prompt": "Find a shipped behaviour no test guards, shown by a concrete failing "
               "input."},
]


def tier(angle: dict) -> str:
    """`"claude"` for an Opus/Sonnet/Haiku or `claude*` model, else `"local"`."""
    model = str(angle.get("model") or "").strip().lower()
    if model in CLAUDE_MODELS or model.startswith("claude"):
        return "claude"
    return "local"


def _validate(angle, seen: set) -> dict:
    if not isinstance(angle, dict):
        raise ValueError(f"angle must be an object: {angle!r}")
    name, model = angle.get("name"), angle.get("model")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"angle name must be a non-empty string: {angle!r}")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"angle {name!r}: model must be a non-empty string")
    if angle.get("role") not in ROLES:
        raise ValueError(f"angle {name!r}: role must be one of {ROLES}")
    if not isinstance(angle.get("prompt"), str):
        raise ValueError(f"angle {name!r}: prompt must be a string")
    if any(bad in model.lower() for bad in _NOT_OPUS):
        raise ValueError(f"angle {name!r}: reviews are always Opus, not {model!r}")
    if angle["role"] == "confirmer" and tier(angle) != "claude":
        raise ValueError(f"angle {name!r}: a confirmer must run on Claude, not {model!r}")
    if name in seen:
        raise ValueError(f"duplicate angle name {name!r}")
    seen.add(name)
    return {"name": name, "prompt": angle["prompt"], "role": angle["role"], "model": model}


def load_angles(config: dict | None) -> list[dict]:
    """`config.review.angles` validated, or a copy of `DEFAULT_ANGLES`.

    `ValueError` on a bad role, empty name/model, duplicate names, a
    Sonnet/Haiku model, or a confirmer that is not on Claude.
    """
    declared = ((config or {}).get("review") or {}).get("angles")
    if declared is None:
        return copy.deepcopy(DEFAULT_ANGLES)
    if not isinstance(declared, list) or not declared:
        raise ValueError("review.angles must be a non-empty list")
    seen: set = set()
    return [_validate(a, seen) for a in declared]


def _reply_text(entry: dict, round_dir) -> str:
    path = Path(str(entry.get("reply_path") or ""))
    if not path.is_absolute() and round_dir is not None:
        path = Path(round_dir) / path
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def confirmer_ran(manifest: dict, round_dir=None) -> bool:
    """True iff >= 1 confirmer angle on Claude left a parseable reply."""
    for entry in manifest.get("angles") or ():
        if entry.get("role") != "confirmer" or tier(entry) != "claude":
            continue
        if parse_codereview_result(_reply_text(entry, round_dir))[1]:
            return True
    return False


def digest_labels(manifest: dict, counts: dict) -> list[tuple[str, int]]:
    """`[("name[model/role]", count), ...]` so the proof digest records each tier."""
    return [(f"{e['name']}[{e['model']}/{e['role']}]", int(counts.get(e["name"], 0)))
            for e in manifest.get("angles") or ()]


def build_prompt(angle: dict, *, base: str, head: str, effort: str, reply_path: str) -> str:
    """The angle's review prompt: range, effort, the bar verbatim, shape, reply path."""
    return (
        f"Review `git diff {base}...{head}` for: {angle['prompt']} "
        f"Run at --effort {effort}. Read .github/review-instructions.md for what counts "
        f"as a real defect here.\n\n"
        f"Review bar: {REVIEW_BAR}\n\n"
        "Each finding is {file, line_range:[start,end], summary, class, blocking, "
        "reproducer?} where class is P (defect in shipped behaviour), X (edge case in "
        "loop-added code), T (test quality / mutation) or C (the change reviewing itself). "
        "blocking=true requires a reproducer: {\"kind\":\"test\",\"source\":<pytest code>} or "
        "{\"kind\":\"command\",\"argv\":[...],\"expect\":{\"exit\":int,\"stdout_contains\":str}} "
        "describing correct behaviour.\n\n"
        f"Write the full reply, ending in a fenced ```json array of findings ([] only if "
        f"genuinely clean), to `{reply_path}` and touch nothing else. Return one line: "
        '{"angle","findings","blocking","reply_path"} as JSON '
        f'(angle="{angle["name"]}", findings and blocking are counts).'
    )
