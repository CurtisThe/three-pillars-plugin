"""Tests for tp-pr-iterate reproducers adopted from the scaffold.

design: cheap-tier-review-prep (Tasks 5.4, 5.5)

Task 5.4: the ``normalized-finding.v1`` schema accepts an optional
``reproducer_origin`` field, enum-restricted to ``"scaffold-adopted"``,
while ``additionalProperties`` stays ``false``.

Task 5.5: ``reproduce.run_cli(..., adopted=)`` / ``--adopted`` restores a
claim's reproducer from an accepted scaffold — adoption only restores the
claim; the scaffold still has to reproduce against the reviewed head.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import reproduce  # noqa: E402
import review_merge  # noqa: E402
import round_tail  # noqa: E402
import review_prep_scaffold as rps  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "normalized-finding.v1.json"
SRC = "def test_adopted():\n    assert 1 == 2\n"
PASSING = {"kind": "command", "argv": [sys.executable, "-c", "print('fine')"],
           "expect": {"exit": 0, "stdout_contains": "fine"}}
_GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1", "HOME": "/nonexistent"}


def _load_schema() -> dict:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _base_finding() -> dict:
    return {
        "source": "code-review",
        "file": "src/a.py",
        "line_range": [3, 5],
        "summary": "boom",
        "verdict": "structural",
        "class": "P",
        "blocking": True,
        "reproducer": {"kind": "test", "source": "def test_x():\n    assert 0\n"},
    }


def test_schema_reproducer_origin():
    """Task 5.4: reproducer_origin is optional, enum 'scaffold-adopted' only."""
    schema = _load_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    # Valid origin value validates.
    finding = _base_finding()
    finding["reproducer_origin"] = "scaffold-adopted"
    assert validator.is_valid(finding), (
        "a finding with reproducer_origin='scaffold-adopted' must validate"
    )

    # Any other origin value fails.
    finding = _base_finding()
    finding["reproducer_origin"] = "other"
    assert not validator.is_valid(finding), (
        "a finding with reproducer_origin='other' must not validate"
    )

    # The field is optional — absent still validates.
    assert validator.is_valid(_base_finding()), (
        "a finding without reproducer_origin must still validate"
    )

    # additionalProperties stays false — unknown keys still fail.
    finding = _base_finding()
    finding["bogus"] = 1
    assert not validator.is_valid(finding), (
        "a finding with an unknown top-level key must not validate"
    )


# -- Task 5.5: adoption in run_cli ------------------------------------------


def _git(repo, *args):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                         env=env, check=True)
    return out.stdout.strip()


def _head_or_empty(repo):
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
                          "HEAD"], capture_output=True, text=True, env=env, check=False)
    return out.stdout.strip() if out.returncode == 0 else ""


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _reply(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```\n"


def _round(tmp_path, round_id, findings):
    repo = tmp_path / "wt"
    rd = tmp_path / "proof" / "rounds" / "pr1" / round_id
    log = tmp_path / "proof" / f"iterate-log.{round_id}.md"
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _git(repo, "init", "-q", "-b", "main")
    _write(repo, ".three-pillars/config.json", "{}\n")
    _write(repo, "three-pillars-docs/tp-designs/d/decisions.md", "# log\n")
    _write(repo, "src/a.py", "a = 1\n")
    _git(repo, "add", "-A")
    if not _head_or_empty(repo):
        _git(repo, "commit", "-q", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD")
    rp = rd / "angle0" / "reply.md"
    _write(rp.parent, rp.name, _reply(findings))
    manifest = {"pr_url": "https://github.com/o/r/pull/1", "round": 2, "ordinal": round_id,
                "base": "BASE",
                "paths": {"proof_root": str(tmp_path / "proof"),
                          "state_path": str(tmp_path / "proof" / "s.json"),
                          "log_path": str(log)},
                "angles": [{"name": "angle0", "role": "confirmer", "model": "opus",
                           "tier": "claude", "reply_path": str(rp)}]}
    _write(rd, "angles.json", json.dumps(manifest))
    return repo, head, rd, log


def _target_claim():
    """A target claim: blocking, no reproducer."""
    return {"file": "src/a.py", "line_range": [1, 1], "summary": "real defect",
            "class": "P", "blocking": True}


def _passes_claim():
    """A structural claim with a passing-command reproducer — non-target."""
    return {"file": "src/b.py", "line_range": [1, 1], "summary": "not a target",
            "class": "P", "blocking": True, "reproducer": PASSING}


def _target_findings():
    """A target claim plus a non-target structural claim (passing command)."""
    return [_target_claim(), _passes_claim()]


def test_adopted_red_scaffold_blocks(tmp_path):
    """An adopted red scaffold restores the claim to structural/blocking."""
    repo, head, rd, log = _round(tmp_path, "r1", [_target_claim()])
    key = rps.targets(rd)[0]["key"]
    rps.write_note(rd, key, {"source": SRC, "test_name": "test_adopted"}, head)
    adopted = rd / "tail" / "adopted.json"
    _write(rd, "tail/adopted.json", json.dumps([{"key": key}]))
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head,
                         "--adopted", str(adopted)])
    assert rc == 0
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    adopted_f = [f for f in findings if f.get("reproducer_origin") == "scaffold-adopted"]
    assert len(adopted_f) == 1
    f = adopted_f[0]
    assert f["verdict"] == "structural" and f["blocking"] is True
    assert "schema_note" not in f
    assert "downgrade" not in f
    assert f["reproducer"] == {"kind": "test", "source": SRC}
    assert f["reproduction"] == "reproduced"
    assert f["origin_source"] == "reviewer"  # round 1 → reviewer fallback
    assert "severity_note" not in f
    assert Draft202012Validator(_load_schema()).is_valid(f)
    assert Draft202012Validator(_load_schema()).is_valid(
        {**f, "dispositioned": True, "disposition_note": "audit"})
    assert reproduce.tally(findings)["blocking"] == 1
    assert not log.exists() or "downgrade" not in log.read_text(encoding="utf-8")


def test_adopted_passing_scaffold_is_minor(tmp_path):
    """Adoption only restores the claim; a passing scaffold still downgrades."""
    repo, head, rd, _log = _round(tmp_path, "r1", _target_findings())
    key = rps.targets(rd)[0]["key"]
    rps.write_note(rd, key,
                   {"source": "def test_ok():\n    assert 1 == 1\n",
                    "test_name": "test_ok"}, head)
    adopted = rd / "tail" / "adopted.json"
    _write(rd, "tail/adopted.json", json.dumps([{"key": key}]))
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head,
                         "--adopted", str(adopted)])
    assert rc == 0
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    f = [x for x in findings if x.get("reproducer_origin") == "scaffold-adopted"][0]
    assert f["verdict"] == "minor" and f["blocking"] is False
    assert f["downgrade"]["reason"] == "not-reproduced"


def test_adopt_refusals_logged(tmp_path):
    """Unknown key, stale head and a non-target adoption are refused and logged."""
    repo, head, rd, log = _round(tmp_path, "r1", [_target_claim(), _passes_claim()])
    key = rps.targets(rd)[0]["key"]
    bkey = rps.finding_key(_passes_claim())
    unknown = "0123456789" "abcdef"
    rps.write_note(rd, key, {"source": SRC, "test_name": "test_adopted"}, "0" * 40)
    # Hand-written note for the non-target finding key (write_note would refuse).
    scaffolds = rd / "prep" / "scaffolds"
    scaffolds.mkdir(parents=True, exist_ok=True)
    _write(rd, "prep/scaffolds/index.json", json.dumps([
        {"key": bkey, "file": "src/b.py", "summary": "not a target",
         "note": str(scaffolds / f"{bkey}.json")}]))
    (scaffolds / f"{bkey}.json").write_text(json.dumps({
        "key": bkey, "head": head, "accepted": True, "source": "def t():\n    pass\n",
        "test_name": "t", "finding": _passes_claim()}) + "\n", encoding="utf-8")
    adopted = rd / "tail" / "adopted.json"
    _write(rd, "tail/adopted.json",
           json.dumps([{"key": unknown}, {"key": key}, {"key": bkey}]))
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head,
                         "--adopted", str(adopted)])
    assert rc == 0
    refusals = [l for l in log.read_text(encoding="utf-8").splitlines()
                if l.startswith("scaffold-adopt-refused:")]
    assert refusals == [
        f"scaffold-adopt-refused: {unknown}: unknown key",
        f"scaffold-adopt-refused: {key}: stale head",
        f"scaffold-adopt-refused: {bkey}: not a target",
    ]
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    t = [f for f in findings if f["summary"] == "real defect"][0]
    assert t["verdict"] == "minor" and t["blocking"] is False
    assert t.get("schema_note") == "blocking-without-reproducer"
    assert "reproducer_origin" not in t
    b = [f for f in findings if f["summary"] == "not a target"][0]
    assert b["verdict"] == "minor" and "reproducer_origin" not in b


def test_no_adopted_is_byte_identical(tmp_path):
    """Without --adopted nothing changes: findings and log match today's path."""
    findings_in = _target_findings() + [
        {"file": "src/a.py", "line_range": [9, 9], "summary": "note claim",
         "class": "C", "blocking": False},
    ]
    repo, head, rd, log = _round(tmp_path, "r1", findings_in)
    out1 = reproduce.run_cli(rd, repo, head)
    b1 = (rd / "tail" / "findings.json").read_bytes()
    l1 = log.read_text(encoding="utf-8").splitlines()
    assert "scaffold-adopt-refused" not in " ".join(l1)
    assert not any("reproducer_origin" in f for f in
                   json.loads(b1.decode("utf-8")))
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    expected, _ = reproduce.run_reproducers(
        review_merge.merge_codereview_angles(
            [reproduce._read_reply(rd, e) for e in manifest["angles"]]),
        cwd=str(repo), scratch_dir=tmp_path / "scratch")
    # The CLI's own last pass is the round tail — the pin follows it, byte for byte.
    expected = round_tail.annotate(expected, manifest=manifest, cwd=str(repo),
                                   head=head, rounds_dir=rd.parent)
    assert b1 == (json.dumps(expected, indent=2) + "\n").encode("utf-8")

    # Explicitly adopted=None, SAME repo and head: byte-identical again (its own
    # round dir + log; a second git repo would only compare commit SHAs).
    rd2 = tmp_path / "proof" / "rounds" / "pr1" / "r2"
    log2 = tmp_path / "proof" / "iterate-log.r2.md"
    rp2 = rd2 / "angle0" / "reply.md"
    _write(rp2.parent, rp2.name, _reply(findings_in))
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    manifest["ordinal"] = "r2"
    manifest["angles"][0]["reply_path"] = str(rp2)
    manifest["paths"]["log_path"] = str(log2)
    _write(rd2, "angles.json", json.dumps(manifest))
    out2 = reproduce.run_cli(rd2, repo, head, adopted=None)
    assert out1 == out2
    assert (rd2 / "tail" / "findings.json").read_bytes() == b1
    assert log2.read_text(encoding="utf-8").splitlines() == l1

    # No --adopted → the scaffold module stays out of the import graph.
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import reproduce\n"
        "reproduce.main(['--round-dir', %r, '--cwd', %r, '--head', %r])\n"
        "print('review_prep_scaffold' in sys.modules)"
    ) % (str(Path(__file__).parent), str(rd), str(repo), head)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "False"
