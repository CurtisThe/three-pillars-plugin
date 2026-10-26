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
import os
import shlex
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
_SHARED = _HERE.parents[1] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import agent_caps  # noqa: E402
import finder_coverage  # noqa: E402
import finding_fields  # noqa: E402
import local_backend  # noqa: E402
import model_policy  # noqa: E402
import role_engine  # noqa: E402
import strata_effort  # noqa: E402
import trust_boundary  # noqa: E402
from review_merge import parse_codereview_result  # noqa: E402

REVIEW_BAR = ("Only a demonstrated shipped-behaviour defect with a reproducer blocks; "
              "mutation survivors, test-tightening, exotic env, lint-guard bypasses, "
              "style and perf are non-blocking notes.")

# The shipped-promises checklist item (consumer-repo-parity Task 9.5, A4): one key
# tags this clause here, in the review-instructions template, and in both
# `.github` guidance files, so all four carry the same item.
PROMISES_ITEM_KEY = "promises-vs-enforcement"
# forge-interface Task 2.3: forge-parity checklist key (skills/_shared/forge-parity-rule.md).
FORGE_PARITY_ITEM_KEY = "forge-parity"

ROLES = ("finder", "confirmer")
CLAUDE_MODELS = set(model_policy.AGENT_ALIASES)

DEFAULT_ANGLES = [
    {"name": "correctness-leak", "role": "confirmer", "model": "opus",
     "prompt": "Hunt fail-closed/correctness leaks: any path to a wrong result, a "
               "non-handled error, an unsafe edge case; "
               f"[{PROMISES_ITEM_KEY}] shipped text promising enforcement by a "
               "mechanism that does not ship or run where it is read; "
               f"[{FORGE_PARITY_ITEM_KEY}] a forge-facing change with no stated "
               "Gitea behaviour, a silent Gitea no-op, or a direct `gh` call that "
               "bypasses `forge.py`."},
    {"name": "edge-cases", "role": "confirmer", "model": "opus",
     "prompt": "Boundary/degenerate inputs, ordering dependence, off-by-one, "
               "type-coercion, missing-key, empty-collection behavior."},
    {"name": "test-quality", "role": "confirmer", "model": "opus",
     "prompt": "Find a shipped behaviour no test guards, shown by a concrete failing "
               "input."},
]


REVIEW_AGENT, DEEP_REVIEW_AGENT = "tp-review-confirmer", "tp-review-confirmer-deep"


def review_agent(round_no: int) -> str:
    """The ONE round → base review agent (operator ruling Q2): round 1 reads the full PR
    diff on the xhigh `-deep` variant; every later round runs the high base agent. (Effort
    lives in agent frontmatter; a spawn cannot set it, so each effort is its own agent.)
    A manifest entry's agent comes from `entry_agent`, which swaps in the Strata variant
    for a `local` angle; this base is what a Claude angle (the Opus check, the security
    lens) and a Sonnet run spawn."""
    return DEEP_REVIEW_AGENT if int(round_no) <= 1 else REVIEW_AGENT


def entry_agent(round_no: int, angle: dict) -> str:
    """The agent one manifest entry spawns (design strata-effort-every-call Task 3.1).

    A `local` angle spawns the Strata variant of the round's review agent — `-deep`
    (xhigh) on round 1, `-medium` after — because Strata never runs at a bare `high`;
    every other model spawns `review_agent(round_no)` unchanged."""
    base = review_agent(round_no)
    return strata_effort.strata_agent(base) if angle.get("model") == "local" else base


def tier(angle: dict) -> str:
    """`"claude"` iff the model maps to an Agent alias, else `"local"`.

    Tier and dispatch agree: an angle is Claude iff `agent_alias` yields a
    value the Agent tool accepts (any of `model_policy.AGENT_ALIASES`), so
    `fable` is a Claude tier and `claude-3-opus-…` ids are not.
    """
    return "claude" if model_policy.agent_alias(angle.get("model") or "") is not None else "local"


def dispatch_model(angle: dict, config: dict | None = None, *, root=".") -> str | None:
    """The Agent `model=` for an angle, or None (not dispatched / no alias).

    None when `skipped` is set. Only the literal model `local` takes the
    `role_engine` review_finder model (`config=None` loads `root`'s config); any
    other model is `model_policy.agent_alias(model)`, None for a non-alias.
    """
    if angle.get("skipped"):
        return None
    model = angle.get("model") or ""
    if model == "local":
        cfg = config if config is not None else role_engine.load_config(root)
        return role_engine.resolve("review_finder", cfg, root=root)["model"]
    return model_policy.agent_alias(model)


SECURITY_ANGLE = "security"  # design review-convergence (security companion, Phase 4)


def security_angle(brief: Path, surfaces: list[dict]) -> dict:
    """The security lens entry: a Claude confirmer pointed at the brief + the surfaces.

    `brief` is the brief the reviewer reads (`trust_boundary.brief_path(repo)`) and
    `surfaces` the detector's entries (`surfaces_for_range`). The bar is the shared
    `trust_boundary.SECURITY_BAR` text, so the angle and the impl-audit synth cannot
    drift. Round 1 appends this angle whatever the detector found, so an empty
    `surfaces` list is a normal call.
    """
    found = "; ".join(f"{s.get('surface', '')} {s.get('path', '')}".strip()
                      for s in surfaces or ())
    prompt = (f"Read the security brief at {brief}. {trust_boundary.SECURITY_BAR} "
              f"Surfaces the detector found: {found or 'none — review the diff anyway'}.")
    return {"name": SECURITY_ANGLE, "role": "confirmer", "model": "opus", "prompt": prompt}


def _validate(angle, seen: set, review_model="opus") -> dict:
    """Validate one angle and enforce the review floor (default model `opus`).

    The review floor is `models.review` (else `opus`): a Claude angle must be
    that model or `opus` — never below it, since `opus` is the policy default,
    never a downgrade. A `claude*` id with no Agent alias (e.g.
    `claude-3-opus-20240229`) is unrecognised and refused.
    """
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
    alias = model_policy.agent_alias(model)
    if tier(angle) != "claude":
        if str(model).strip().lower().startswith("claude"):
            raise ValueError(
                f"angle {name!r}: unrecognised Claude model id; use an alias "
                f"or claude-<family>-…")
        if angle["role"] == "confirmer":
            raise ValueError(
                f"angle {name!r}: a confirmer must run on Claude, not {model!r}")
    elif alias not in {review_model, "opus"}:
        raise ValueError(
            f"angle {name!r}: review model must be {review_model} (or opus), "
            f"not {model!r}")
    if name in seen:
        raise ValueError(f"duplicate angle name {name!r}")
    seen.add(name)
    return {"name": name, "prompt": angle["prompt"], "role": angle["role"], "model": model}


def load_angles(config: dict | None) -> list[dict]:
    """`config.review.angles` validated, or a copy of `DEFAULT_ANGLES`.

    `ValueError` on a bad role, empty name/model, duplicate names, a Claude
    angle below the review floor (`models.review`, else `opus`), an
    unrecognised `claude*` id, or a confirmer that is not on Claude.
    `DEFAULT_ANGLES` keep literal `opus` but are rewritten to `models.review`
    when that key is set; a local finder is marked
    `{"skipped": "local backend absent"}` when the local backend is not installed.
    """
    review_model = model_policy.model_for("review", config)
    declared = ((config or {}).get("review") or {}).get("angles")
    if declared is None:
        result = copy.deepcopy(DEFAULT_ANGLES)
        declared_review = ((config or {}).get("models") or {}).get("review")
        if declared_review is not None and review_model == declared_review:
            for a in result:
                a["model"] = review_model
    else:
        if not isinstance(declared, list) or not declared:
            raise ValueError("review.angles must be a non-empty list")
        seen: set = set()
        result = [_validate(a, seen, review_model) for a in declared]
    for a in result:
        if a.get("role") == "finder" and tier(a) == "local" and not local_backend.available():
            a["skipped"] = "local backend absent"
    return result


# A skipped local finder is never dispatched, so it has no reply: its readers use this
# genuine clean reply instead of the unparseable sentinel (L125). A finder never signs
# the proof on its own (`confirmer_ran`), so this cannot make a round converge.
SKIPPED_REPLY = '{"findings": []}\n'


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


def digest_labels(manifest: dict, counts: dict, coverage=None) -> list[tuple[str, int]]:
    """`[("name[model/role]", count), ...]` so the proof digest records each tier.

    Each label gains its `finder_coverage.label_suffix` (a skip or a capped, partial or
    unparseable segment says so). `coverage` is the round's coverage line
    (`finder_coverage.coverage_line`), appended to the `opus-check` label: never a label of
    its own, so the count is the manifest's angle count. `None` posts today's labels.
    """
    out = []
    for e in manifest.get("angles") or ():
        label = f"{e['name']}[{e['model']}/{e['role']}]" + finder_coverage.label_suffix(e)
        if coverage and e["name"] == "opus-check":
            label += f" [{coverage}]"
        out.append((label, int(counts.get(e["name"], 0))))
    return out


PUT_TAG = "TP_REPLY_EOF"  # the quoted-heredoc delimiter of the `put` delivery command


def put_command(put_script: str, round_dir: str, slot: str) -> str:
    """The Bash line that pipes a reply into `round_scratch.py put` (quoted heredoc:
    `$`, backticks and pytest source reach the file unexpanded)."""
    q = shlex.quote
    return (f"python3 {q(str(put_script))} put --round-dir {q(str(round_dir))} "
            f"--slot {q(str(slot))} <<'{PUT_TAG}'")


def build_prompt(angle: dict, *, base: str, head: str, effort: str, reply_path: str,
                 round_dir=None, put_script=None, instructions_present: bool = True) -> str:
    """The angle's review prompt: range, effort, the bar verbatim, shape, delivery.

    The reply is delivered ONLY through the `put` command (`put_command`), never a
    direct write: the proof root sits outside the reviewer's cwd. `round_dir`
    defaults to the reply's round dir, `put_script` to this dir's round_scratch.py.
    `instructions_present` (default True) switches the instructions line: the
    repo's `.github/review-instructions.md` is named when it exists; when the
    repo has no instructions file the prompt names no path and applies the
    bar below as the whole standard.
    """
    round_dir = round_dir if round_dir is not None else str(Path(reply_path).parent.parent)
    put_script = put_script if put_script is not None else str(_HERE / "round_scratch.py")
    if instructions_present:
        instructions = ("Read .github/review-instructions.md for what counts "
                        "as a real defect here.")
    else:
        instructions = ("This repo has no review-instructions file; apply the bar "
                        "below as the whole standard.")
    origin_enum = "|".join(finding_fields.ORIGINS)
    fragility_enum = "|".join(finding_fields.FRAGILITY_CLASSES)
    prompt = (
        f"TP_SCRATCH: {os.path.dirname(reply_path)}\n\n"
        f"Review `git diff {base}...{head}` for: {angle['prompt']} "
        f"Run at --effort {effort}. {instructions} See `skills/_shared/test-fragility.md` "
        "for what makes a test or check fragile.\n\n"
        f"Review bar: {REVIEW_BAR}\n\n"
        "Each finding is {file, line_range:[start,end], summary, class, origin, "
        "fragility_class, blocking, reproducer?} where class is P (defect in shipped "
        "behaviour), X (edge case in loop-added code), T (test fragility "
        "(`skills/_shared/test-fragility.md`)) or C (the change reviewing itself); "
        f"origin is one of {{{origin_enum}}}; fragility_class is one of "
        f"{{{fragility_enum}}}. "
        "blocking=true requires a reproducer: {\"kind\":\"test\",\"source\":<pytest code>} or "
        "{\"kind\":\"command\",\"argv\":[...],\"expect\":{\"exit\":int,\"stdout_contains\":str}} "
        "describing correct behaviour.\n\n"
        "Deliver exactly one JSON object, ONLY by running this one Bash command — never the "
        "Write tool, never a direct file write — and touch nothing else:\n\n"
        f"{put_command(put_script, round_dir, angle['name'])}\n<your one JSON object>\n{PUT_TAG}\n\n"
        'The object is {"findings": [...], "notes": "<optional context>"}, bare or inside one '
        "```json fence, with no prose before or after it and no repeated key. Every "
        "defect, lows included, is a finding (blocking=false unless it blocks); notes is "
        'never read as a finding. {"findings": []} only if genuinely clean. Anything else '
        "reads as a failed review. "
        "Return one line: "
        '{"angle","findings","blocking","reply_path"} as JSON '
        f'(angle="{angle["name"]}", reply_path="{reply_path}", findings and blocking are '
        "counts).")
    note = finder_coverage.partial_note(angle)
    if note:
        prompt += "\n\n" + note
    if angle.get("role") == "finder":
        prompt += "\n\n" + agent_caps.BUDGET_LINE
    return prompt
