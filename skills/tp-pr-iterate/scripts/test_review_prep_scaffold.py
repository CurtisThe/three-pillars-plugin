"""Tests for review_prep_scaffold.finding_key and .targets (selection + cap).

design: cheap-tier-review-prep (Task 5.2)

`targets` must return exactly the findings `finding_class.coerce` left
blocking without a reproducer (schema_note == "blocking-without-reproducer"),
skipping sentinels, non-blocking claims and claims with a valid reproducer.
It caps at SCAFFOLD_CAP and logs the overflow as `scaffold-cap` lines; the
`finding_key` is stable across the merge path `reproduce.run_cli` uses.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402
import review_merge  # noqa: E402
import review_prep_scaffold  # noqa: E402
from review_prep_scaffold import SCAFFOLD_CAP, finding_key  # noqa: E402


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _reply(findings):
    """`build_prompt` reply shape: one `{"findings": [...]}` object in one fence (M27)."""
    return "```json\n" + json.dumps({"findings": findings}) + "\n```\n"


def _finding(summary, file="src/a.py", line_range=(1, 2), blocking=True, repro=None):
    f = {"file": file, "line_range": list(line_range), "summary": summary,
         "class": "P", "blocking": blocking}
    if repro is not None:
        f["reproducer"] = repro
    return f


def _key(file, start, end, summary) -> str:
    return hashlib.sha256(f"{file}|{start}|{end}|{summary}".encode("utf-8")).hexdigest()[:16]


@pytest.fixture()
def setup(tmp_path):
    def build(*replies):
        rd = tmp_path / "proof" / "rounds" / "pr1" / "r2"
        log = tmp_path / "proof" / "iterate-log.1.md"
        manifest = {"pr_url": "https://github.com/o/r/pull/1", "round": 2,
                    "ordinal": "r2", "base": "BASE",
                    "paths": {"proof_root": str(tmp_path / "proof"),
                              "state_path": str(tmp_path / "proof" / "s.json"),
                              "log_path": str(log)},
                    "angles": []}
        for i, text in enumerate(replies):
            rp = rd / f"angle{i}" / "reply.md"
            _write(rd, rp.relative_to(rd), text)
            manifest["angles"].append({"name": f"angle{i}", "role": "confirmer",
                                       "model": "opus", "tier": "claude",
                                       "reply_path": str(rp)})
        _write(rd, "angles.json", json.dumps(manifest, indent=2) + "\n")
        return rd, log
    return build


def test_finding_key_is_exact_sha256_prefix():
    f = {"file": "src/a.py", "line_range": [3, 5], "summary": "boom"}
    assert finding_key(f) == hashlib.sha256(b"src/a.py|3|5|boom").hexdigest()[:16]


def test_finding_key_missing_range_falls_back_to_zeros():
    f = {"file": "src/a.py", "summary": "boom"}
    assert finding_key(f) == hashlib.sha256(b"src/a.py|0|0|boom").hexdigest()[:16]


def test_targets_picks_blocking_without_reproducer_only(setup):
    rd, log = setup(
        "garbage",  # unparseable reply → angle sentinel
        _reply([_finding("style nit", file="src/b.py", blocking=False)]),
        _reply([_finding("real bug with repro", file="src/c.py", line_range=(4, 6),
                         repro={"kind": "test", "source": "def test_x():\n    assert 0\n"})]),
        _reply([_finding("boom", file="src/a.py", line_range=(3, 5))]),
    )
    ts = review_prep_scaffold.targets(rd)
    assert len(ts) == 1
    assert ts[0]["finding"]["summary"] == "boom"
    assert ts[0]["finding"]["file"] == "src/a.py"
    assert ts[0]["key"] == _key("src/a.py", 3, 5, "boom")
    # No overflow → no log file written.
    assert not log.exists()


def test_targets_caps_at_cap_and_logs_overflow(setup):
    replies = [_reply([_finding(f"s{i} unique-{i}", file=f"src/a{i}.py")])
               for i in range(7)]
    rd, log = setup(*replies)
    ts = review_prep_scaffold.targets(rd)
    assert len(ts) == SCAFFOLD_CAP == 5
    assert [t["key"] for t in ts] == [
        _key(f"src/a{i}.py", 1, 2, f"s{i} unique-{i}") for i in range(5)]
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines == [
        f"[cheap-tier] scaffold-cap: {_key('src/a5.py', 1, 2, 's5 unique-5')} src/a5.py:1",
        f"[cheap-tier] scaffold-cap: {_key('src/a6.py', 1, 2, 's6 unique-6')} src/a6.py:1",
    ]


def test_targets_no_log_when_under_cap(setup):
    replies = [_reply([_finding(f"s{i} unique-{i}", file=f"src/a{i}.py")])
               for i in range(SCAFFOLD_CAP)]
    rd, log = setup(*replies)
    ts = review_prep_scaffold.targets(rd)
    assert len(ts) == SCAFFOLD_CAP
    assert not log.exists()


def test_key_matches_reproduce_merge_path(setup):
    rd, _log = setup(
        _reply([_finding("boom", file="src/a.py", line_range=(3, 5))]),
        _reply([_finding("style nit", file="src/b.py", blocking=False)]),
    )
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    merged = review_merge.merge_codereview_angles(
        [reproduce._read_reply(rd, e) for e in manifest["angles"]])
    ts = review_prep_scaffold.targets(rd)
    assert len(ts) == 1
    match = [f for f in merged
             if f.get("file") == "src/a.py" and f.get("summary") == "boom"]
    assert len(match) == 1
    assert ts[0]["key"] == finding_key(match[0])
