"""round_tail step 2 — the impl audit's dispositions in the round tail.

design: review-convergence (Task 6.3, detailed-design-pr-loop §B, §D4)

`annotate` runs `audit_dispositions.mark` between origin and severity, but only in
round 1 and only when `dispositions` names the carry file (a str / `os.PathLike`).
A round-1 finding the audit already dispositioned comes back `dispositioned`,
non-blocking and `minor` — and because severity ran afterwards, that non-blocking
call is the last word. Round 2 never reads the carry, so its findings stay as the
reviewer filed them, and a `dispositions` value that is not a path is ignored.
`reproduce.py --dispositions P` threads the same carry into the CLI's tail.

The carry's `audit_head` is the reviewed head itself, so the §D4 diff
(`git diff --quiet <audit_head> <head> -- <file>`) is clean for every file here.
"""

from __future__ import annotations

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

# Both sides say this, so the claim-token Jaccard is 1.0 >= the 0.5 floor.
CLAIM = "unchecked null dereference in parser loop"


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
    """One commit, so the audited file is unchanged from the audit head to `head`."""
    repo = tmp_path / "wt"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, "src/parser.py", "def parse(s):\n    return s.strip()\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _rounds(tmp_path, head):
    """Round dirs r1/r2 under one proof root; both manifests name a state file."""
    root = tmp_path / "proof" / "rounds" / "pr1"
    for n in (1, 2):
        _write(root / f"r{n}", "angles.json", json.dumps({
            "round": n, "head": head,
            "paths": {"state_path": str(tmp_path / "proof" / "state.json")}}))
    return root


def _carry(tmp_path, head, *, claim=CLAIM, line=2):
    """The carry `audit_dispositions.write` produces for one dispositioned finding."""
    path = tmp_path / "audit-dispositions.json"
    path.write_text(json.dumps([{
        "file": "src/parser.py", "area": "src", "claim": claim,
        "disposition": "fixed", "severity": "medium", "audit_head": head, "line": line,
    }], indent=2) + "\n", encoding="utf-8")
    return path


def _finding(summary=CLAIM, line=2, **extra):
    f = {"source": "code-review", "file": "src/parser.py", "line_range": [line, line],
         "summary": summary, "verdict": "structural", "blocking": True}
    f.update(extra)
    return f


def _schema() -> dict:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _annotate(manifest, repo, head, rounds_dir, **over):
    return round_tail.annotate([_finding()], manifest=manifest, cwd=str(repo),
                                head=head, rounds_dir=rounds_dir, **over)


def test_round_one_marks_the_carry_match(tmp_path):
    """Round 1 + carry → the match is dispositioned, and severity keeps it minor."""
    repo, head = _repo(tmp_path)
    root = _rounds(tmp_path, head)
    manifest = json.loads((root / "r1" / "angles.json").read_text(encoding="utf-8"))
    out = _annotate(manifest, repo, head, root / "r1",
                    dispositions=_carry(tmp_path, head))
    assert out[0]["dispositioned"] is True
    assert out[0]["blocking"] is False
    assert out[0]["verdict"] == "minor"
    assert "fixed" in out[0]["disposition_note"]
    # severity.finalize ran after mark, so it added no flip note of its own.
    assert "severity_note" not in out[0]
    # The tail's output stays inside the finding schema (G2's other half).
    Draft202012Validator.check_schema(_schema())
    assert Draft202012Validator(_schema()).is_valid(out[0]), out[0]


def test_round_two_never_reads_the_carry(tmp_path):
    """Round 2's audit verdict is stale — the finding stays blocking, unmarked."""
    repo, head = _repo(tmp_path)
    root = _rounds(tmp_path, head)
    manifest = json.loads((root / "r2" / "angles.json").read_text(encoding="utf-8"))
    out = _annotate(manifest, repo, head, root / "r2",
                    dispositions=_carry(tmp_path, head))
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True
    assert out[0]["verdict"] == "structural"


def test_non_path_dispositions_are_ignored(tmp_path):
    """A `dispositions` that is not a path never reaches the carry reader."""
    repo, head = _repo(tmp_path)
    root = _rounds(tmp_path, head)
    manifest = json.loads((root / "r1" / "angles.json").read_text(encoding="utf-8"))
    plain = _annotate(manifest, repo, head, root / "r1")
    for value in ([{"finding": "x", "status": "ignored"}], 7, object()):
        assert _annotate(manifest, repo, head, root / "r1",
                         dispositions=value) == plain


def test_missing_carry_leaves_the_finding_blocking(tmp_path):
    """A named-but-absent carry is fail-soft: nothing matched, nothing changed."""
    repo, head = _repo(tmp_path)
    root = _rounds(tmp_path, head)
    manifest = json.loads((root / "r1" / "angles.json").read_text(encoding="utf-8"))
    out = _annotate(manifest, repo, head, root / "r1",
                    dispositions=tmp_path / "no-such-carry.json")
    assert "dispositioned" not in out[0]
    assert out[0]["blocking"] is True


def test_cli_dispositions_mark_a_round_one_match(tmp_path, capsys):
    """`reproduce.py --dispositions P` puts the carry's judgement in the round tail.

    The claim's reproducer cannot run, so its outcome is inconclusive: without the
    carry the claim stays blocking (the runner never fails open), with it the audit's
    settled disposition wins.
    """
    import reproduce  # noqa: E402 — the CLI under test

    repo, head = _repo(tmp_path)
    _write(repo, ".three-pillars/config.json", "{}\n")
    _write(repo, "three-pillars-docs/tp-designs/d/decisions.md", "# log\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bookkeeping")
    head = _git(repo, "rev-parse", "HEAD")
    root = _rounds(tmp_path, head)
    rd = root / "r1"
    log = tmp_path / "proof" / "iterate-log.r1.md"
    reply = rd / "angle0" / "reply.md"
    incon = {"kind": "test", "source": "import no_such_module_xyz\n"}
    _write(reply.parent, reply.name, "```json\n"
           + json.dumps({"findings": [_finding(reproducer=incon)]}) + "\n```\n")
    manifest = json.loads((rd / "angles.json").read_text(encoding="utf-8"))
    manifest["pr_url"] = "https://github.com/o/r/pull/1"
    manifest["ordinal"] = "r1"
    manifest["paths"]["log_path"] = str(log)
    manifest["angles"] = [{"name": "angle0", "role": "confirmer", "model": "opus",
                           "tier": "claude", "reply_path": str(reply)}]
    _write(rd, "angles.json", json.dumps(manifest))

    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head,
                         "--dispositions", str(_carry(tmp_path, head))])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["blocking"] == 0
    findings = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))
    assert len(findings) == 1
    marked = findings[0]
    assert marked["dispositioned"] is True
    assert marked["blocking"] is False
    assert marked["verdict"] == "minor"
    assert Draft202012Validator(_schema()).is_valid(marked), marked

    # Without the flag the same claim still blocks — the carry is opt-in.
    rc = reproduce.main(["--round-dir", str(rd), "--cwd", str(repo), "--head", head])
    assert rc == 0
    unmarked = json.loads((rd / "tail" / "findings.json").read_text(encoding="utf-8"))[0]
    assert "dispositioned" not in unmarked
    assert unmarked["blocking"] is True
