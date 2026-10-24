"""test_escalate_first_hook.py — the escalate-first PreToolUse hook decision.

design: fable-escalation 5.1 — deny untagged / resolved / unknown AskUserQuestion
cards, allow an `escalate` ruling, scope gates, fail-open. Every fixture is a tmp
git repo; no network, no real environment.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import escalate_first_hook as hook  # noqa: E402
import ruling_file  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
# The inv-50 pin reads framework-check.sh, which never ships (dev-repo only).
_needs_framework_check = pytest.mark.skipif(
    not (REPO_ROOT / "framework-check.sh").is_file(),
    reason="reads framework-check.sh (dev-repo only)")

ENV = {"TP_DESIGN_RUN": "1"}
DOC_PATH = "skills/_shared/escalation.md"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path, *, owner="orchestrator:x", phase="tier-2", branch="tp/demo"):
    """tmp git repo on `branch` with the demo design lock (owner/phase)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", branch, "-q")
    lock = {"owner": owner}
    if phase is not None:
        lock["phase"] = phase
    lock_dir = repo / "three-pillars-docs/tp-designs/demo"
    lock_dir.mkdir(parents=True)
    (lock_dir / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=fixture@test", "-c", "user.name=fixture",
         "commit", "-q", "-m", "fixture: lock")
    return repo


def _ruling(repo, *, scope="demo", outcome="escalate"):
    """Write one ruling file through ruling_file.write; return its id."""
    path = ruling_file.write(
        repo, scope=scope, entry="run",
        stop={"source": "question", "detail": {"question": "Which route?"}},
        key="q1", result={"outcome": outcome}, model="fable",
        at="2026-10-12T00:00:00Z")
    return ruling_file.parse(path)["front"]["id"]


def _payload(cwd, questions):
    return {"tool_name": "AskUserQuestion", "cwd": str(cwd),
            "tool_input": {"questions": questions}}


def _question(text):
    return {"question": text,
            "options": [{"label": "A"}, {"label": "B"}],
            "header": "Route"}


def _denied(out):
    return bool(out) and json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def _reason(out):
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]


def test_deny_untagged(tmp_path):
    repo = _repo(tmp_path)
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert rc == 0 and _denied(out)
    reason = _reason(out)
    assert reason.startswith("escalate-first: denied — ")
    assert DOC_PATH in reason


def test_allow_escalate_ruling(tmp_path):
    repo = _repo(tmp_path)
    rid = _ruling(repo, outcome="escalate")
    out, rc = hook.run(
        _payload(repo, [_question("Which route?\nruling: " + rid)]), env=ENV)
    assert (out, rc) == ("", 0)


def test_deny_resolved_ruling(tmp_path):
    repo = _repo(tmp_path)
    rid = _ruling(repo, outcome="resolved")
    out, rc = hook.run(
        _payload(repo, [_question("Which route?\nruling: " + rid)]), env=ENV)
    assert rc == 0 and _denied(out)


def test_deny_unknown_id(tmp_path):
    repo = _repo(tmp_path)
    out, rc = hook.run(
        _payload(repo, [_question("Which route?\nruling: demo-20261012-ffffff")]),
        env=ENV)
    assert rc == 0 and _denied(out)


def test_allow_without_design_run_env(tmp_path):
    repo = _repo(tmp_path)
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env={})
    assert (out, rc) == ("", 0)


def test_allow_human_owned_lock(tmp_path):
    repo = _repo(tmp_path, owner="curtis")
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert (out, rc) == ("", 0)


def test_allow_phase_design(tmp_path):
    repo = _repo(tmp_path, phase="design")
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert (out, rc) == ("", 0)


@pytest.mark.parametrize("phase", ["detail", "tier-2"])
def test_enforce_phase_detail_and_tier2(tmp_path, phase):
    repo = _repo(tmp_path, phase=phase)
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert rc == 0 and _denied(out)


def test_allow_missing_phase(tmp_path):
    repo = _repo(tmp_path, phase=None)
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert (out, rc) == ("", 0)


def test_allow_branch_not_design(tmp_path):
    repo = _repo(tmp_path, branch="master")
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert (out, rc) == ("", 0)


def test_enforce_archived_lock(tmp_path):
    """Task 8.2: after the Tier 5.6 archive the lock sits in completed-tp-designs/."""
    repo = _repo(tmp_path, phase="cleanup-pending")
    (repo / "three-pillars-docs/tp-designs/demo/lock.json").unlink()
    archived = repo / "three-pillars-docs/completed-tp-designs/demo"
    archived.mkdir(parents=True)
    (archived / "lock.json").write_text(
        json.dumps({"owner": "orchestrator:x", "phase": "cleanup-pending"}), encoding="utf-8")
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert rc == 0 and _denied(out)
    rid = _ruling(repo, outcome="escalate")
    out, rc = hook.run(
        _payload(repo, [_question("Which route?\nruling: " + rid)]), env=ENV)
    assert (out, rc) == ("", 0)


def test_allow_missing_lock(tmp_path):
    repo = _repo(tmp_path)
    (repo / "three-pillars-docs/tp-designs/demo/lock.json").unlink()
    out, rc = hook.run(_payload(repo, [_question("Which route?")]), env=ENV)
    assert (out, rc) == ("", 0)


def test_allow_other_scope_ruling(tmp_path):
    repo = _repo(tmp_path)
    rid = _ruling(repo, scope="other", outcome="escalate")
    out, rc = hook.run(
        _payload(repo, [_question("Which route?\nruling: " + rid)]), env=ENV)
    assert rc == 0 and _denied(out)


def test_second_untagged_question_denies(tmp_path):
    repo = _repo(tmp_path)
    rid = _ruling(repo, outcome="escalate")
    out, rc = hook.run(_payload(repo, [
        _question("Which route?\nruling: " + rid),
        _question("And the second?")]), env=ENV)
    assert rc == 0 and _denied(out)


HOOK_PATH = _SHARED / "escalate_first_hook.py"
LIVE_MANIFEST = _SHARED / "hooks" / "claude-code-hooks.json"


def _check_manifest(path):
    return subprocess.run([sys.executable, str(HOOK_PATH), "--check-manifest", str(path)],
                          input="", capture_output=True, text=True, timeout=30)


def test_check_manifest_registered():
    """Task 5.2: the live manifest registers the AskUserQuestion entry."""
    r = _check_manifest(LIVE_MANIFEST)
    assert r.returncode == 0, r.stderr


def test_check_manifest_missing(tmp_path):
    """Task 5.2: a manifest without the entry exits 1 with one stderr line."""
    cfg = json.loads(LIVE_MANIFEST.read_text(encoding="utf-8"))
    cfg["hooks"]["PreToolUse"] = [e for e in cfg["hooks"]["PreToolUse"]
                                  if e["matcher"] != "AskUserQuestion"]
    copy = tmp_path / "claude-code-hooks.json"
    copy.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    r = _check_manifest(copy)
    assert r.returncode == 1, r.stderr
    err = [ln for ln in r.stderr.splitlines() if ln.strip()]
    assert len(err) == 1 and err[0].startswith("escalate-first:")


def test_malformed_stdin_allows_with_one_line(capsys):
    real_stdin, sys.stdin = sys.stdin, io.StringIO("{not json")
    try:
        code = hook.main()
    finally:
        sys.stdin = real_stdin
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert code == 0
    assert len(lines) == 1 and lines[0].startswith("escalate-first:")


@_needs_framework_check
def test_framework_check_inv50_advisory():
    from invariant_map import parse_invariant_map

    fc = REPO_ROOT / "framework-check.sh"
    assert parse_invariant_map(fc)[50].status == "active"
    text = fc.read_text(encoding="utf-8")
    block = text[text.index("# 50. "):].split('if [[ "$ERRORS" -gt 0 ]]')[0].split("# 51. ")[0]
    assert 'escalate_first_hook.py" --check-manifest' in block
    assert "warn" in block
    assert "fail " not in block
