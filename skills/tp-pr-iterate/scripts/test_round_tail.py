"""Tests for round_tail.annotate — the round's ordered tail pass.

design: review-convergence (Task 2.3, detailed-design-pr-loop §B)

`annotate` runs origin (Task 2.1) then severity (Phase 1) over a round's findings.
Step 2 (dispositions) and step 4 (round freeze) land in later tasks, so
`dispositions` is accepted and ignored here.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import round_tail  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "normalized-finding.v1.json"
_GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t",
                          "-c", "user.email=t@t", *args], capture_output=True,
                         text=True, env=env, check=True)
    return out.stdout.strip()


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path):
    """A repo whose round-1 head has 3 untouched lines and whose fix commit rewrites line 3."""
    repo = tmp_path / "wt"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "src/a.py", "a = 1\nb = 2\nc = 3\n")
    _git(repo, "add", "-A")
    first = _git(repo, "commit", "-q", "-m", "base") or _git(repo, "rev-parse", "HEAD")
    _write(repo, "src/a.py", "a = 1\nb = 2\nc = 33\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fix round 1")
    return repo, first, _git(repo, "rev-parse", "HEAD")


def _rounds(tmp_path, first, head):
    root = tmp_path / "proof" / "rounds" / "pr1"
    _write(root / "r1", "angles.json", json.dumps({"round": 1, "head": first}))
    _write(root / "r2", "angles.json", json.dumps({"round": 2, "head": head}))
    return root / "r2", root


def _finding(line, **extra):
    f = {"source": "code-review", "file": "src/a.py", "line_range": [line, line],
         "summary": "boom", "verdict": "structural", "blocking": True}
    f.update(extra)
    return f


def _by_summary(out):
    return {f["summary"]: f for f in out}


def test_round_two_blames_the_fix_commit(tmp_path):
    """Fix-line findings read regression; untouched lines stay original/blame."""
    repo, first, head = _repo(tmp_path)
    rd, rounds_dir = _rounds(tmp_path, first, head)
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    out = round_tail.annotate(
        [_finding(3, summary="fix line"), _finding(1, summary="untouched line")],
        manifest=manifest, cwd=str(repo), head=head, rounds_dir=rounds_dir)
    by = _by_summary(out)
    assert by["fix line"]["origin"] == "regression"
    assert by["fix line"]["origin_source"] == "blame"
    assert by["untouched line"]["origin"] == "original"
    assert by["untouched line"]["origin_source"] == "blame"


def test_finalize_is_the_last_word(tmp_path):
    """An Opus-downgraded claim ends non-blocking — severity ran after origin."""
    repo, first, head = _repo(tmp_path)
    rd, rounds_dir = _rounds(tmp_path, first, head)
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    out = round_tail.annotate(
        [_finding(1, escape={"disposition": "downgraded", "reason": "not real"})],
        manifest=manifest, cwd=str(repo), head=head, rounds_dir=rounds_dir)
    assert out[0]["blocking"] is False
    assert out[0]["verdict"] == "minor"
    assert out[0]["severity_note"] == "opus-downgraded"
    assert out[0]["origin_source"] == "blame"


def test_round_one_is_the_reviewer_fallback(tmp_path):
    """Round 1 has no earlier head, so every finding keeps the reviewer's tag."""
    repo, first, head = _repo(tmp_path)
    root = tmp_path / "proof" / "rounds" / "pr1"
    _write(root / "r1", "angles.json", json.dumps({"round": 1, "head": head}))
    manifest = json.loads((root / "r1" / "angles.json").read_text(encoding="utf-8"))
    out = round_tail.annotate([_finding(3)], manifest=manifest, cwd=str(repo),
                              head=head, rounds_dir=root / "r1")
    assert out[0]["origin_source"] == "reviewer"
    assert out[0]["origin"] == "unclassified"


def test_missing_rounds_dir_is_the_reviewer_fallback(tmp_path):
    """rounds_dir=None (or an unreadable dir) → reviewer, never a guess."""
    repo, _first, head = _repo(tmp_path)
    manifest = {"round": 2}
    out = round_tail.annotate([_finding(3)], manifest=manifest, cwd=str(repo),
                              head=head, rounds_dir=None)
    assert out[0]["origin_source"] == "reviewer"
    missing = round_tail.annotate([_finding(3)], manifest=manifest, cwd=str(repo),
                                  head=head, rounds_dir=tmp_path / "nope")
    assert missing[0]["origin_source"] == "reviewer"


def test_inputs_are_never_mutated(tmp_path):
    """The caller's list and dicts come back untouched."""
    repo, first, head = _repo(tmp_path)
    rd, rounds_dir = _rounds(tmp_path, first, head)
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    findings = [_finding(3), _finding(1)]
    snapshot = copy.deepcopy(findings)
    round_tail.annotate(findings, manifest=manifest, cwd=str(repo), head=head,
                        rounds_dir=rounds_dir)
    assert findings == snapshot


def test_dispositions_are_accepted_and_ignored(tmp_path):
    """Step 2 (audit dispositions) lands in Task 6.3 — the signature accepts it now."""
    repo, first, head = _repo(tmp_path)
    rd, rounds_dir = _rounds(tmp_path, first, head)
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    plain = round_tail.annotate([_finding(3)], manifest=manifest, cwd=str(repo),
                                head=head, rounds_dir=rounds_dir)
    with_disp = round_tail.annotate([_finding(3)], manifest=manifest, cwd=str(repo),
                                    head=head, rounds_dir=rounds_dir,
                                    dispositions=[{"finding": "x", "status": "ignored"}])
    assert with_disp == plain


def test_annotated_findings_validate_against_the_schema(tmp_path):
    """The tail's output stays inside normalized-finding.v1."""
    repo, first, head = _repo(tmp_path)
    rd, rounds_dir = _rounds(tmp_path, first, head)
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    out = round_tail.annotate(
        [_finding(3), _finding(1), _finding(1, blocking=False)],
        manifest=manifest, cwd=str(repo), head=head, rounds_dir=rounds_dir)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for f in out:
        assert validator.is_valid(f), f
