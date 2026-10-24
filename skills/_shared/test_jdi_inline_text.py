"""The inline Slot 7 section of the Tier 2-4 build doc (dev repo only).

design: lean-default-followups (task 1.5, Behavior 3). The `## Inline Slot 7` section must carry
the `Targets: none` branch of step 2 and the full Tier 3.5 stdin in step 3. These checks read
parsed structure only, as `test_weight_class_lean_prose.py` does: the code spans of the section
(through `skill_spans`), the references (through `skill_refs`) and the payload that
`tier_3_5_rerun.validate_rerun` accepts. The exit handling (0 -> Tier 5, 1 -> retry, 2 -> escalate)
is wording only and stays a prose claim.

Run with: pytest skills/_shared/test_jdi_inline_text.py -q
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parent
REPO_ROOT = SHARED.parents[1]
SCRIPTS = REPO_ROOT / "skills" / "tp-run-full-design" / "scripts"
DOC = REPO_ROOT / "skills" / "tp-run-full-design" / "tier-2-4-build.md"
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

_STEP = re.compile(r"^(\d+)\. ")


def _lines() -> list[str]:
    return DOC.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def _spans(first: int, last: int) -> list[str]:
    skill_spans = pytest.importorskip("skill_spans")
    text = "\n".join(_lines())
    return [span for line, span, _shell in skill_spans.code_spans(text) if first <= line < last]


def _section(prefix: str) -> tuple[int, int]:
    lines = _lines()
    start = next(n for n, line in enumerate(lines, 1) if line.startswith(prefix))
    end = next((n for n, line in enumerate(lines, 1) if n > start and line.startswith("## ")),
               len(lines) + 1)
    return start, end


def _inline_step_spans(number: str) -> list[str]:
    start, end = _section("## Inline Slot 7")
    lines = _lines()
    first = next(n for n in range(start, end)
                 if (m := _STEP.match(lines[n - 1])) and m.group(1) == number)
    last = next((n for n in range(first + 1, end) if _STEP.match(lines[n - 1])), end)
    return _spans(first, last)


def _stdin_span(spans: list[str]) -> str | None:
    return next((s for s in spans if s.startswith("{worker_response")), None)


def _wrapper_stdin() -> str:
    start, end = _section("### Wrapper-driven pipeline")
    # the wrapper section ends at the next heading of any level
    lines = _lines()
    end = next((n for n in range(start + 1, len(lines) + 1) if lines[n - 1].startswith("#")),
               len(lines) + 1)
    span = _stdin_span(_spans(start, end))
    assert span is not None
    return span


def _keys(span: str) -> list[str]:
    """Names (with any `?`) at brace depth 1 of a `{k: v, k2, ...}` span."""
    body = span.strip()
    assert body.startswith("{") and body.endswith("}"), span
    keys, depth, cur = [], 0, ""
    for ch in body[1:-1]:
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch == "," and depth == 0:
            keys.append(cur)
            cur = ""
        else:
            cur += ch
    keys.append(cur)
    return [k.split(":", 1)[0].strip() for k in keys if k.strip()]


def _nested(span: str, name: str) -> str:
    """The `{...}` value of key `name` at depth 1 of the span."""
    m = re.search(rf"\b{name}:\s*(\{{)", span)
    assert m, (name, span)
    depth, i = 0, m.start(1)
    for j in range(i, len(span)):
        depth += {"{": 1, "}": -1}.get(span[j], 0)
        if depth == 0:
            return span[i:j + 1]
    raise AssertionError(span)


def _load_rerun(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("tier_3_5_rerun_under_test",
                                                  SCRIPTS / "tier_3_5_rerun.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inline_stdin_names_the_wrapper_top_level_keys():
    span = _stdin_span(_inline_step_spans("3"))
    assert span is not None, "no stdin span in inline step 3"
    assert set(_keys(span)) == set(_keys(_wrapper_stdin()))


def test_inline_agent_meta_keys():
    span = _stdin_span(_inline_step_spans("3"))
    assert span is not None
    assert set(_keys(_nested(span, "agent_meta"))) == {"agentId", "worktreePath"}


def test_inline_rerun_keys_and_validate_rerun(monkeypatch):
    span = _stdin_span(_inline_step_spans("3"))
    assert span is not None
    assert sorted(_keys(_nested(span, "rerun"))) == sorted(
        ["plan_path", "phase", "phase_base_sha", "test_cmd?"])
    module = _load_rerun(monkeypatch)
    module.validate_rerun({"rerun": {"plan_path": "p", "phase": 1, "phase_base_sha": "s"}})
    module.validate_rerun({"rerun": {"plan_path": "p", "phase": 1, "phase_base_sha": "s",
                                     "test_cmd": "c"}})


def test_inline_step_two_targets_none_spans():
    spans = _inline_step_spans("2")
    assert "Targets: none" in spans
    assert "Implement: <task>" in spans


def test_doc_references_resolve(tmp_path):
    skill_refs = pytest.importorskip("skill_refs")
    assert skill_refs.check(REPO_ROOT, [DOC], cache_dir=tmp_path).issues == []
