"""test_certify_fragment_wiring.py — Task 1.12: Tier 5.6 and the certification sweep file into the fragment.

design: living-doc-fragments, Task 1.12. Oracle: example. Structure only (skills/_shared/test-fragility.md):
each markdown file is read through ``skill_invocations`` and ``skill_spans`` (its code spans, never its
prose); the Tier 5.6 command is filled and run on a fixture, and the protocol is checked by
``skill_refs.check``. No test pins wording.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

skill_spans = pytest.importorskip("skill_spans")  # dev-only modules: a plugin copy skips this file
skill_refs = pytest.importorskip("skill_refs")
import certify_issues  # noqa: E402
import changes_fragment as cf  # noqa: E402
from skill_invocations import invocations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "skills" / "_shared"
CLOSEOUT = ROOT / "skills" / "tp-run-full-design" / "tier-5-closeout.md"
PROTOCOL = SHARED / ("certifica" + "tion-prot" + "ocol.md")
FILL = {"design": "three-pillars-docs/tp-designs/demo", "slug": "demo", "D": "three-pillars-docs/tp-designs/demo"}
ADD = "Known issues — add"
KNOWN = "# Known Issues\n\n## Medium\n\n### M3: an open one\n\nbody\n\n## Low\n"
FM = "---\nslug: demo\nkind: design\ndate: 2026-10-22\n---\n"
RESULT = {"complete": True, "name": "sweep-01", "sha": "a" * 40, "disposition": "ledger", "claims": [
    {"id": "s2", "status": "not-binding", "reasons": [], "guard": "g/s2.py::t", "evidence": {"red": [], "green": []}}]}


def _apply_calls(md: Path) -> list[list[str]]:
    """Every `python3 "$CL" issues apply …` command of ``md``, placeholders filled."""
    calls = invocations(md, "$CL", fill=FILL, root=ROOT)
    return [c for c in calls if c[2:4] == ["issues", "apply"]]


def _value(call: list[str], flag: str) -> str:
    return call[call.index(flag) + 1]


def _spans_of(text: str) -> list[list[str]]:
    """The tokens of every code span of ``text``, placeholders filled."""
    found = []
    for _line, span, shell in skill_spans.code_spans(text):
        tokens = skill_spans.tokens_of(span, shell)
        for name, value in FILL.items():
            tokens = [t.replace("{" + name + "}", value) for t in tokens]
        found.append(tokens)
    return found


def test_tier56_apply_invocation_writes_the_fragment(tmp_path):
    calls = _apply_calls(CLOSEOUT)
    assert len(calls) == 1, calls
    call = calls[0]
    assert "--fragment" in call and "--known-issues" not in call, call
    assert not any("{" in token for token in call), call
    assert _value(call, "--fragment") == "three-pillars-docs/changes/demo.md"
    # run it: the fixture holds the pending file where the command reads it, and a registration fragment
    docs = tmp_path / "three-pillars-docs"
    (docs / "changes").mkdir(parents=True)
    known = docs / "known_issues.md"
    known.write_text(KNOWN, encoding="utf-8")
    pending = tmp_path / _value(call, "--pending")
    pending.parent.mkdir(parents=True)
    pending.write_text(certify_issues.render([RESULT], None), encoding="utf-8")
    fragment = tmp_path / _value(call, "--fragment")
    fragment.write_text(FM, encoding="utf-8")
    argv = [sys.executable, str(SHARED / "certify_ledger.py"), *call[2:]]
    done = subprocess.run(argv, cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads(done.stdout.strip().splitlines()[-1]) == {"applied": ["M-new-cert-sweep-01-s2"]}
    parsed = cf.parse(fragment.read_text(encoding="utf-8"), stem="demo")
    assert cf.validate(parsed) == []
    assert [b.heading.split(":")[0] for b in parsed.sections[ADD]] == ["M-new-cert-sweep-01-s2"]
    assert known.read_text(encoding="utf-8") == KNOWN
    # and the closeout stages that fragment (a `git add` command naming the same path)
    adds = [t for t in _spans_of(CLOSEOUT.read_text(encoding="utf-8")) if t[:2] == ["git", "add"]]
    assert any(_value(call, "--fragment") in t for t in adds), adds


def test_certification_protocol_refs_resolve(tmp_path):
    report = skill_refs.check(ROOT, [PROTOCOL], cache_dir=tmp_path)
    assert report.issues == [], report.issues
    calls = _apply_calls(PROTOCOL)
    assert len(calls) == 2, calls  # Step 2b step 6 and the certify-sweep issues step
    for call in calls:
        assert "--fragment" in call and "--known-issues" not in call, call
    # the certify-sweep commit stages the fragment its issues step wrote
    text = PROTOCOL.read_text(encoding="utf-8")
    sweep = text[text.index("\n## Certify-sweep\n"):text.index("\n## KNOWN BYPASS list")]
    fragment = _value(calls[-1], "--fragment")
    assert [t for t in _spans_of(sweep) if "issues" not in t and fragment in t], fragment
