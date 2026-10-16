"""explainer/explain_gate.py — the deterministic gate every draft passes.

Public API:
    ONLY_REWRITE                       the sentence every rewrite prompt carries
    run_gates(env, request) -> {"pass": bool, "failures": [str], "diagrams_ok": [bool],
                                "diagram_reasons": [str | None]}
    rewrite_prompt(failures, diagram_reasons=None) -> str

run_gates runs four checks, in this order, and reports every failure (it
never stops at the first):

    1. schema    explain_envelope.validate_envelope(env, request["kind"]);
                 its codes pass through as-is (missing-section:<id>,
                 raw-diagram, bad-shape:<path>, ...)
    2. refs      evidence_refs.check_refs(env, request):
                     unknown-ref:<id>       a ref that is not a request
                                            evidence id
                     unsupported:<path>     a field with no ref, or with an
                                            unknown ref
    3. lint      ste_lint.lint(env); decided on the result's "passed", never
                 on "any issue" (soft issues are reported even when the
                 ratios pass). A failed lint adds lint:<rule> for each
                 distinct rule in its issues.
    4. diagrams  explain_diagram_check.problem per diagram_specs entry:
                     diagram:<i>            spec <i> is unusable or not
                                            connected (a REASONS slug)

Each code appears once, in the order found. "pass" is True only when there
is no failure. "diagrams_ok" holds one bool per diagram_specs entry ([] when
diagram_specs is not a list); "diagram_reasons" holds, per entry, the
explain_diagram_check slug that failed it, or None.

rewrite_prompt names each failure code with a one-line fix and ends with
ONLY_REWRITE. Given diagram_reasons, a diagram:<i> line also states the
REASONS sentence for entry <i>. The gate allows one rewrite; the caller counts attempts.

Stdlib only. Flat-import package — no __init__.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_DIR = _HERE.parent
for _p in (_SHARED_DIR, _HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import evidence_refs  # noqa: E402
import explain_diagram_check  # noqa: E402
import explain_envelope  # noqa: E402
import explain_spec  # noqa: E402
import ste_lint  # noqa: E402

ONLY_REWRITE = "This is your only rewrite."

# Code prefix -> the fix to state. The longest matching prefix wins; a code
# with no match gets _DEFAULT_FIX.
_FIXES = {
    "bad-shape:": "Give this field the envelope shape.",
    "bad-schema": f'Set "schema" to "{explain_envelope.SCHEMA}".',
    "kind-mismatch": 'Set "kind" to the request kind.',
    "missing-section:": "Add this required section, with at least one item.",
    "no-recommended": 'Mark one option with "recommended": true.',
    "raw-diagram": ("Write each diagram as a spec. Do not write svg, "
                    "mermaid, html or a code fence."),
    "unknown-ref:": "Cite only the evidence ids in the request.",
    "unsupported:": "Cite at least one request evidence id here, or remove it.",
    "lint:soft-length": "Shorten the long sentences.",
    "lint:hard-length": ("Split each sentence of more than "
                         f"{ste_lint.HARD_MAX_WORDS} words."),
    "lint:passive": "Write the sentences in the active voice.",
    "lint:banned": "Remove the banned words and use plain words.",
    "lint:": "Follow the STE writing rules.",
    "diagram:": ("Fix this diagram to the spec grammar, or remove it. "
                 f"The kinds are: {', '.join(explain_spec.ALLOWED_KINDS)}."),
}
_DEFAULT_FIX = "Fix this failure."


class _Codes:
    """Ordered, de-duplicated failure codes."""

    def __init__(self):
        self.codes: list = []

    def add(self, code: str) -> None:
        if code not in self.codes:
            self.codes.append(code)


def _refs_codes(env, request, out: _Codes) -> None:
    found = evidence_refs.check_refs(env, request)
    for ref in found["unknown"]:
        out.add(f"unknown-ref:{ref}")
    for path in found["unsupported"]:
        out.add(f"unsupported:{path}")


def _lint_codes(env, out: _Codes) -> None:
    result = ste_lint.lint(env)
    if result["passed"]:
        return
    for issue in result["issues"]:
        out.add(f"lint:{issue['rule']}")


def _diagram_codes(env, out: _Codes) -> list:
    """One reason slug (or None) per diagram_specs entry; adds diagram:<i>."""
    specs = env.get("diagram_specs") if isinstance(env, dict) else None
    if not isinstance(specs, list):
        return []
    reasons = []
    for i, spec in enumerate(specs):
        reason = explain_diagram_check.problem(spec)
        reasons.append(reason)
        if reason is not None:
            out.add(f"diagram:{i}")
    return reasons


def run_gates(env, request) -> dict:
    """Run schema, refs, lint and diagram checks on ``env``; report every failure.

    ``request["kind"]`` is the kind the envelope must be; an unknown kind
    raises ValueError (explain_envelope.validate_envelope).
    """
    kind = request.get("kind") if isinstance(request, dict) else None
    out = _Codes()
    for code in explain_envelope.validate_envelope(env, kind):
        out.add(code)
    _refs_codes(env, request, out)
    _lint_codes(env, out)
    reasons = _diagram_codes(env, out)
    return {"pass": not out.codes, "failures": out.codes,
            "diagrams_ok": [r is None for r in reasons],
            "diagram_reasons": reasons}


def _fix_for(code: str) -> str:
    matches = [p for p in _FIXES if code == p or (p.endswith(":")
                                                   and code.startswith(p))]
    if not matches:
        return _DEFAULT_FIX
    return _FIXES[max(matches, key=len)]


def _reason_for(code: str, diagram_reasons) -> str:
    """The REASONS sentence for a diagram:<i> code, or "" when none is known."""
    if not code.startswith("diagram:") or not isinstance(diagram_reasons, list):
        return ""
    index = code[len("diagram:"):]
    if not index.isdigit() or int(index) >= len(diagram_reasons):
        return ""
    slug = diagram_reasons[int(index)]
    return f" {explain_diagram_check.reason_text(slug)}" if slug else ""


def rewrite_prompt(failures, diagram_reasons=None) -> str:
    """The rewrite instruction for ``failures``: each code, its fix, one rewrite.

    ``diagram_reasons`` (run_gates' list) adds the reason to each diagram:<i> line.
    """
    lines = ["Your draft failed the explainer gate. Fix each failure below.",
             "Keep every other part of the envelope the same.", ""]
    lines.extend(f"- `{code}`:{_reason_for(code, diagram_reasons)} {_fix_for(code)}"
                 for code in failures)
    lines.extend(["", "Return the full envelope as JSON.", ONLY_REWRITE])
    return "\n".join(lines)
