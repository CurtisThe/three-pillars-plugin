"""Tests for `fix_round.run_round` — the single-round worker.

Each integration test stands up a real tmp_path git repo (bare origin + clone)
and PATH-shims `gh` via a Python script that returns canned JSON / exit codes.
That keeps the production codepath honest about subprocess plumbing while
isolating tests from network and the host's real `gh` install.

Run with: pytest skills/tp-pr-fix/scripts/test_fix_round.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import fix_round  # noqa: E402


# ---------- fixture plumbing ----------


def _base_env(tmp_path: Path) -> dict:
    return {
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
    }


def _git(cwd: Path, *args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=check
    )


_GH_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""PATH-shim for `gh` — routes subcommands to canned responses."""
import sys

MODE = "{mode}"
HEAD_REF = "{head_ref}"

argv = sys.argv[1:]

def _is_collaborator_check() -> bool:
    return len(argv) >= 2 and argv[0] == "api" and "collaborators/" in argv[1]

def _is_pr_view_headref() -> bool:
    return (
        len(argv) >= 4
        and argv[0] == "pr"
        and argv[1] == "view"
        and "--json" in argv
        and "headRefName" in argv
    )

def _is_pr_view_labels() -> bool:
    return (
        len(argv) >= 4
        and argv[0] == "pr"
        and argv[1] == "view"
        and "--json" in argv
    )

def _is_pr_edit() -> bool:
    return len(argv) >= 2 and argv[0] == "pr" and argv[1] == "edit"

def _is_label_create() -> bool:
    return len(argv) >= 2 and argv[0] == "label" and argv[1] == "create"

def _is_pr_diff() -> bool:
    return len(argv) >= 2 and argv[0] == "pr" and argv[1] == "diff"


if _is_collaborator_check():
    if MODE == "collaborator":
        sys.exit(0)
    elif MODE == "non-collaborator":
        print("gh: HTTP 404 Not Found", file=sys.stderr)
        sys.exit(1)
    else:  # unreachable
        print("gh: HTTP 503 Service Unavailable", file=sys.stderr)
        sys.exit(1)

if _is_pr_view_headref():
    # `-q .headRefName` makes real gh emit the bare branch name.
    print(HEAD_REF)
    sys.exit(0)

if _is_pr_view_labels():
    print('{{"labels":[]}}')
    sys.exit(0)

if _is_pr_edit():
    sys.exit(0)

if _is_label_create():
    sys.exit(0)

if _is_pr_diff():
    print("")
    sys.exit(0)

sys.exit(0)
'''


def _make_repo_fixture(
    tmp_path: Path, mode: str = "collaborator", head_ref: str = "tp/foo"
) -> tuple[Path, dict]:
    """Build (clone, env) with origin + tracking branch + PATH-shimmed gh.

    `head_ref` is what the gh shim returns for `pr view --json headRefName`
    (F1). It defaults to "tp/foo" — the fixture's own branch — so rounds that
    don't exercise F1 see a matching head and take the normal commit path.
    """
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))

    env = _base_env(tmp_path)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(remote), str(clone), env=env)

    _git(clone, "checkout", "-b", "tp/foo", env=env)
    (clone / "README").write_text("hello\n")
    _git(clone, "add", "README", env=env)
    _git(clone, "commit", "-m", "init", env=env)
    _git(clone, "push", "-u", "origin", "tp/foo", env=env)

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "gh"
    shim.write_text(_GH_SHIM_TEMPLATE.format(mode=mode, head_ref=head_ref))
    shim.chmod(0o755)
    env["PATH"] = f"{shim_dir}:{env['PATH']}"

    return clone, env


def _make_classified(comment_id: str, reviewer: str, verdict: str = "structural") -> dict:
    return {
        "comment_id": comment_id,
        "reviewer": reviewer,
        "verdict": verdict,
        "file": "src/foo.py",
        "line_range": [10, 12],
        "issue_class": "incorrect-behavior",
        "issue_phrase": "fix the bug",
        "diff_hunk_ref": "@@ -10,3 +10,3 @@",
    }


# ---------- the five tests ----------


def test_envelope_schema_valid():
    from jsonschema import Draft202012Validator

    schema_path = HERE.parent / "schemas" / "fix-envelope.v1.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)


def test_end_to_end_with_stub_gh(tmp_path, monkeypatch):
    clone, env = _make_repo_fixture(tmp_path, mode="collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "alice")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    # (a) single commit lands with prefix [tp-pr-fix iter-1]
    subj = _git(clone, "log", "-1", "--format=%s", env=env).stdout.strip()
    assert subj.startswith("[tp-pr-fix iter-1]"), f"got commit subject: {subj!r}"

    # (e) envelope validates
    from jsonschema import Draft202012Validator
    schema = json.loads((HERE.parent / "schemas" / "fix-envelope.v1.json").read_text())
    Draft202012Validator(schema).validate(envelope)

    assert envelope["verdict"] == "applied"
    assert envelope["iteration"] == 1
    assert len(envelope["fixes_applied"]) == 1
    assert envelope["fixes_applied"][0]["comment_id"] == "c1"


def test_identity_gate_via_gh_collaborators(tmp_path, monkeypatch):
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    classified = [_make_classified("c1", "rando")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    # (c) non-collaborator is excluded from the fix pass, deferred with reason
    assert envelope["verdict"] == "no-applicable-fixes"
    deferred_reasons = [d["reason"] for d in envelope["fixes_deferred"]]
    assert "non-collaborator" in deferred_reasons
    assert len(envelope["fixes_applied"]) == 0


def test_copilot_bot_reviewer_is_trusted_despite_404(tmp_path, monkeypatch):
    """F3 (pr-fix-targeting): Copilot is a requested-reviewer *Bot*, not a repo
    collaborator, so `gh api .../collaborators/Copilot` 404s. Its review comments
    are legitimate and must be actioned — a trusted-reviewer-bot allowlist
    short-circuits the gate so a structural Copilot comment is applied, NOT
    deferred as 'non-collaborator'. Runs in non-collaborator mode so a regression
    (removing the allowlist) re-defers it and fails this test."""
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "Copilot")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    deferred_reasons = [d["reason"] for d in envelope["fixes_deferred"]]
    assert "non-collaborator" not in deferred_reasons, envelope
    assert envelope["verdict"] == "applied", envelope
    assert any(f["comment_id"] == "c1" for f in envelope["fixes_applied"])


def test_identity_gate_failure_aborts_round_only_returns_envelope_marking_deferred(
    tmp_path, monkeypatch
):
    """Per design constraint: 'Identity-gate failure aborts the round, not the loop.'

    A transient 5xx for every comment in the round must NOT raise — the caller
    (loop_driver) needs to retry on the next poll cycle. We return cleanly with
    verdict='no-applicable-fixes' and every comment in fixes_deferred[] with
    reason='identity-gate-unreachable'.
    """
    clone, env = _make_repo_fixture(tmp_path, mode="unreachable")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    classified = [_make_classified("c1", "alice"), _make_classified("c2", "bob")]

    # Must NOT raise.
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    assert envelope["verdict"] == "no-applicable-fixes"
    assert len(envelope["fixes_deferred"]) == 2
    assert all(
        d["reason"] == "identity-gate-unreachable" for d in envelope["fixes_deferred"]
    )
    assert len(envelope["fixes_applied"]) == 0


def test_commit_uses_orchestrator_committer_email(tmp_path, monkeypatch):
    """(b) git log -1 --format=%ce equals 'orchestrator+<localpart>@<domain>'."""
    clone, env = _make_repo_fixture(tmp_path, mode="collaborator")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "alice")]
    fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )

    ce = _git(clone, "log", "-1", "--format=%ce", env=env).stdout.strip()
    assert ce == "orchestrator+curtis.theoret@gmail.com", f"got committer email: {ce!r}"


# ---------- F1: head-ref targeting ----------


def test_standalone_mismatch_refuses(tmp_path, monkeypatch):
    """F1: standalone, when the checked-out branch ('tp/foo') is not the PR head
    ('feature/bar'), run_round refuses with HeadRefMismatch and lands no commit."""
    clone, env = _make_repo_fixture(
        tmp_path, mode="collaborator", head_ref="feature/bar"
    )
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")
    head_before = _git(clone, "rev-parse", "HEAD", env=env).stdout.strip()

    classified = [_make_classified("c1", "alice")]
    with pytest.raises(fix_round.HeadRefMismatch):
        fix_round.run_round(
            design="foo",
            pr_url="https://github.com/o/r/pull/1",
            iteration=1,
            classified=classified,
            head_ref=None,
            loop_mode=False,
        )

    head_after = _git(clone, "rev-parse", "HEAD", env=env).stdout.strip()
    assert head_after == head_before, "no commit must land on a refused round"
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD", env=env).stdout.strip() == "tp/foo"


def test_standalone_matching_commits(tmp_path, monkeypatch):
    """F1: standalone, when the branch matches the resolved PR head, the normal
    commit path runs (head_ref self-resolves to the current branch)."""
    clone, env = _make_repo_fixture(tmp_path, mode="collaborator", head_ref="tp/foo")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "alice")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
        head_ref=None,
        loop_mode=False,
    )
    assert envelope["verdict"] == "applied"
    subj = _git(clone, "log", "-1", "--format=%s", env=env).stdout.strip()
    assert subj.startswith("[tp-pr-fix iter-1]")


def test_loop_mode_checks_out_head_ref(tmp_path, monkeypatch):
    """F1: loop_mode auto-checks-out the PR head before committing. Branch starts
    on 'tp/foo'; head_ref='feature/bar' (which exists); the commit lands there."""
    clone, env = _make_repo_fixture(tmp_path, mode="collaborator", head_ref="feature/bar")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    # Create feature/bar off tp/foo with an origin upstream (it's the PR head,
    # so in the real loop it already exists on origin) and return to tp/foo.
    _git(clone, "checkout", "-b", "feature/bar", env=env)
    _git(clone, "push", "-u", "origin", "feature/bar", env=env)
    _git(clone, "checkout", "tp/foo", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    (clone / "fix.py").write_text("# fix applied\n")

    classified = [_make_classified("c1", "alice")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
        head_ref="feature/bar",
        loop_mode=True,
    )
    assert envelope["verdict"] == "applied"
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD", env=env).stdout.strip() == "feature/bar"
    subj = _git(clone, "log", "-1", "--format=%s", env=env).stdout.strip()
    assert subj.startswith("[tp-pr-fix iter-1]")


def test_no_op_round_never_touches_branch(tmp_path, monkeypatch):
    """F1: a no-op round (all comments deferred → empty working tree) must not
    resolve/checkout the head ref even on a mismatch — the decision point sits
    after the no-applicable-fixes early-exit."""
    clone, env = _make_repo_fixture(tmp_path, mode="collaborator", head_ref="feature/bar")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    # 'minor' verdict → deferred, no working-tree change → early-exit fires.
    classified = [_make_classified("c1", "alice", verdict="minor")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
        head_ref=None,
        loop_mode=False,
    )
    assert envelope["verdict"] == "no-applicable-fixes"
    # Branch untouched despite the head-ref mismatch — no refuse, no checkout.
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD", env=env).stdout.strip() == "tp/foo"


def test_trusted_bots_env_var_extends_allowlist(tmp_path, monkeypatch):
    """F3: TP_PR_FIX_TRUSTED_BOTS extends the trusted-reviewer-bot allowlist, so a
    custom bot login that 404s on the collaborators API is gated through (applied),
    not deferred as non-collaborator. Pins the env-var extension path + casing."""
    clone, env = _make_repo_fixture(tmp_path, mode="non-collaborator", head_ref="tp/foo")
    _git(clone, "config", "user.email", "curtis.theoret@gmail.com", env=env)
    monkeypatch.chdir(clone)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("TP_PR_FIX_TRUSTED_BOTS", "mybot")

    (clone / "fix.py").write_text("# fix applied\n")

    # Mixed-case login must match the lowercased allowlist.
    classified = [_make_classified("c1", "MyBot")]
    envelope = fix_round.run_round(
        design="foo",
        pr_url="https://github.com/o/r/pull/1",
        iteration=1,
        classified=classified,
    )
    deferred_reasons = [d["reason"] for d in envelope["fixes_deferred"]]
    assert "non-collaborator" not in deferred_reasons, envelope
    assert envelope["verdict"] == "applied", envelope
    assert any(f["comment_id"] == "c1" for f in envelope["fixes_applied"])
