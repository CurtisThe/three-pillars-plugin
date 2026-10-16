"""Part 2: the round-1 flush keeps round 1's findings so a scoped round-2 prepare succeeds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import round_plan  # noqa: E402
import round_scratch  # noqa: E402

URL = "https://github.com/o/r/pull/7"
FINDING = {"severity": "blocking", "file": "a.py", "line": 3, "summary": "bug"}


def test_flush_r1_then_scoped_prepare_finds_r1_findings(tmp_path):
    rd = tmp_path / "rounds" / "7" / "r1"
    (rd / "a1").mkdir(parents=True)
    (rd / "tail").mkdir()
    (rd / "angles.json").write_text(
        json.dumps({"paths": {"proof_root": str(tmp_path)}, "angles": [],
                    "head": "aaa", "base": "000"}), encoding="utf-8")
    (rd / "a1" / "reply.md").write_text("reply", encoding="utf-8")
    (rd / "tail" / "envelope.json").write_text(json.dumps({"terminal": "fix"}), encoding="utf-8")
    (rd / "tail" / "findings.json").write_text(json.dumps([FINDING]), encoding="utf-8")
    log, dec = tmp_path / "loop.md", tmp_path / "decisions.md"
    log.write_text("entry\n", encoding="utf-8")
    dec.write_text("", encoding="utf-8")

    rc = round_scratch.main(["flush", "--log", str(log), "--decisions", str(dec),
                             "--root", str(tmp_path), "--pr-url", URL])

    assert rc == 0
    assert json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8")) == [FINDING]
    assert round_plan.prior_reviewed_head(tmp_path / "rounds" / "7", "bbb") == "aaa"
