"""`converge.py --round-dir` refuses a LOST state mid-loop: absent, zero-length or unparseable.

design: iterate-convergence-budget (PR #158 round r1 fix)

Parity with `run_round_boundary.refuse_mid_loop_bootstrap`: a zero-length (crash
residue) or unparseable state at round > 1 must stop the loop, not be re-seeded
by `converge._seed_state` as round 0 (which run_round.py could then no longer refuse).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import angles  # noqa: E402
import converge  # noqa: E402
import converge_rounddir  # noqa: E402
import round_scratch  # noqa: E402

PR = "https://github.com/o/r/pull/7"
FENCE = "`" * 3


@pytest.mark.parametrize("content", ["", "{not json", "[]"])
def test_lost_state_mid_loop_refused_like_absent(tmp_path, monkeypatch, content):
    proof = tmp_path / "proof"
    state = proof / "iterate-state.7.v1.json"
    kw = dict(base="b0", head="h1", effort="high", state_path=str(state),
              log_path=str(proof / "iterate-log.7.md"))
    r1 = round_scratch.prepare(proof, PR, angles.DEFAULT_ANGLES, **kw)
    (r1 / "tail" / "envelope.json").write_text('{"action":"fix"}', encoding="utf-8")
    r2 = round_scratch.prepare(proof, PR, angles.DEFAULT_ANGLES, **kw)
    m = json.loads((r2 / "angles.json").read_text(encoding="utf-8"))
    for e in m["angles"]:
        Path(e["reply_path"]).write_text(FENCE + "json\n{\"findings\": []}\n" + FENCE, encoding="utf-8")
    (r2 / "tail" / "findings.json").write_text("[]", encoding="utf-8")
    state.write_text(content, encoding="utf-8")
    called = []
    monkeypatch.setattr(converge, "_finish_clean", lambda **k: called.append(k) or 0)
    out = io.StringIO()
    rc = converge_rounddir.run(r2, config={}, seams={"out": out, "err": io.StringIO(),
                                                      "repo_root": tmp_path})
    assert rc == 2 and not called
    assert json.loads(out.getvalue())["reason"] == "state-bootstrapped-mid-loop"
    assert state.read_text(encoding="utf-8") == content
