"""Tests for the candidate/* reaper apply path + CLI (Phase 2, B7 / B8).

Covers:
  Task 2.1: apply_deletions — dry-run inert (B7-), real deletes (B7+), batched
            fail-open (B8), age-axis remote suppression on fetch failure (B6/F3)
  Task 2.2: main() CLI — dry-run default + --slug scope + --json, and fail-closed
            under --apply (a classify raise deletes nothing, still exits 0)

Deletes are verified as GENUINELY gone (git ls-remote origin / git rev-parse),
not command-string no-ops. Fixtures mirror test_gc_candidate_branches.py: a
SEPARATE bare origin repo so a remote delete never touches a local ref.

Run with: python -m pytest skills/_shared/test_gc_candidate_branches_apply.py -n0 -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import gc_candidate_branches as gcb  # noqa: E402
import gc_candidate_branches_apply as gcba  # noqa: E402
import gc_candidate_branches_cli as cli  # noqa: E402

# ---------------------------------------------------------------------------
# Git fixtures — a REAL bare origin (separate from work) so remote deletes are
# genuine and verifiable, never a no-op that only builds command strings.
# ---------------------------------------------------------------------------

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@test.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@test.com",
    "HOME": os.environ.get("HOME", os.path.expanduser("~")),
    "PATH": os.environ.get("PATH", ""),
}


def _git(cwd: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        check=check, env=_GIT_ENV,
    )


def make_origin_and_work(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "master")
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "master")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "README").write_text("hello\n")
    _git(work, "add", "README")
    _git(work, "commit", "-m", "init")
    _git(work, "remote", "add", "origin", str(origin))
    _git(work, "push", "origin", "master")
    return origin, work


def add_local_candidate(work: Path, branch: str) -> None:
    _git(work, "branch", branch)


def push_candidate(work: Path, branch: str) -> None:
    _git(work, "push", "origin", branch)
    _git(work, "fetch", "origin")


def local_ref_exists(work: Path, branch: str) -> bool:
    return _git(work, "rev-parse", "--verify", f"refs/heads/{branch}",
                check=False).returncode == 0


def remote_ref_exists(work: Path, branch: str) -> bool:
    """True iff `branch` still exists on origin (queried live via ls-remote)."""
    out = _git(work, "ls-remote", "origin", branch).stdout.strip()
    return bool(out)


def _row(branch: str, surface: str, axis: str = "merge") -> gcb.CandidateRow:
    """A deletable CandidateRow pinned to one surface/axis for apply tests."""
    slug, cand_id = branch.split("/")[1], branch.split("/")[2]
    return gcb.CandidateRow(
        branch=branch, slug=slug, cand_id=cand_id, surface=surface,
        classification="deletable", action="deletable",
        evidence={"axis": axis},
    )


# ---------------------------------------------------------------------------
# Task 2.1 — B7 negative: dry-run mutates nothing
# ---------------------------------------------------------------------------


def test_dry_run_mutates_nothing(tmp_path):
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")

    rows = [_row("candidate/a/single", "local"),
            _row("candidate/a/single", "remote")]
    verdicts = gcba.apply_deletions(rows, repo=work, apply=False)

    # Nothing removed — both surfaces still present.
    assert local_ref_exists(work, "candidate/a/single")
    assert remote_ref_exists(work, "candidate/a/single")
    assert {v.action_taken for v in verdicts} == {"dry-run"}
    # The exact commands are surfaced for the operator.
    assert any("git branch -D candidate/a/single" == v.command
               for v in verdicts if v.surface == "local")
    assert any("push origin --delete candidate/a/single" in v.command
               for v in verdicts if v.surface == "remote")


# ---------------------------------------------------------------------------
# Task 2.1 — B7 positive: --apply really deletes (refs genuinely GONE)
# ---------------------------------------------------------------------------


def test_apply_really_deletes(tmp_path):
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")
    assert local_ref_exists(work, "candidate/a/single")
    assert remote_ref_exists(work, "candidate/a/single")

    rows = [_row("candidate/a/single", "local"),
            _row("candidate/a/single", "remote")]
    verdicts = gcba.apply_deletions(rows, repo=work, apply=True)

    # Genuinely gone on BOTH surfaces (queried live, not from stale cache).
    assert not local_ref_exists(work, "candidate/a/single")
    assert not remote_ref_exists(work, "candidate/a/single")
    assert all(v.action_taken == "deleted" for v in verdicts), verdicts


# ---------------------------------------------------------------------------
# Task 2.1 — B8: batched, fail-open — surviving batches delete for real
# ---------------------------------------------------------------------------


def test_apply_batches_and_fails_open(tmp_path, monkeypatch):
    origin, work = make_origin_and_work(tmp_path)
    branches = [f"candidate/e{i}/single" for i in range(5)]
    for b in branches:
        add_local_candidate(work, b)
        push_candidate(work, b)

    # 5 remote rows, batch_size=2 → batches [e0,e1] [e2,e3] [e4].
    # Force the FIRST batch to fail so genuinely-deletable batches run AFTER
    # the failure. A fail-CLOSED regression (break/return on a failed push)
    # would leave e2..e4 alive and this test would then FAIL — which is the
    # point: fail-open is proven by later batches actually deleting.
    rows = [_row(b, "remote") for b in branches]
    failed_batch = set(branches[:2])   # e0, e1 — the first batch
    survivors_after = branches[2:]     # e2, e3, e4 — batches AFTER the failure

    real_push = gcba._push_delete_batch

    def flaky_push(repo, batch):
        if set(batch) & failed_batch:
            return (False, "simulated push failure")
        return real_push(repo, batch)

    monkeypatch.setattr(gcba, "_push_delete_batch", flaky_push)

    verdicts = gcba.apply_deletions(rows, repo=work, apply=True, batch_size=2)

    # Batch grouping preserved: every remote command names ≤2 refs.
    remote_cmds = {v.command for v in verdicts}
    for cmd in remote_cmds:
        refs = cmd.split("--delete", 1)[1].split()
        assert len(refs) <= 2, f"batch exceeded size: {cmd}"

    # Fail-open proven: batches AFTER the failed first batch actually deleted.
    for b in survivors_after:
        assert not remote_ref_exists(work, b), f"{b} (a later batch) should be gone"
    # The forced-fail batch's refs remain (fail-open per batch, not a global abort).
    for b in failed_batch:
        assert remote_ref_exists(work, b), f"{b} (failed batch) must survive"

    # Every batch outcome reported; the failed batch does not abort the rest.
    by_branch = {v.branch: v for v in verdicts}
    assert all(by_branch[b].action_taken == "delete-failed" for b in failed_batch)
    assert all(by_branch[b].action_taken == "deleted" for b in survivors_after)


# ---------------------------------------------------------------------------
# Task 2.1 — B6/F3: fetch failure suppresses AGE-axis remote deletes only
# ---------------------------------------------------------------------------


def test_fetch_failure_suppresses_age_remote_deletes(tmp_path):
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/aged/single")
    push_candidate(work, "candidate/aged/single")
    add_local_candidate(work, "candidate/merged/single")
    push_candidate(work, "candidate/merged/single")

    rows = [
        _row("candidate/aged/single", "remote", axis="age"),
        _row("candidate/merged/single", "remote", axis="merge"),
    ]
    verdicts = gcba.apply_deletions(rows, repo=work, apply=True, fetch_ok=False)

    # Age-axis remote delete is withheld (stale-cache guard); ref survives.
    assert remote_ref_exists(work, "candidate/aged/single")
    # Merge-axis remote delete is a positive fact — proceeds regardless.
    assert not remote_ref_exists(work, "candidate/merged/single")

    by_branch = {v.branch: v for v in verdicts}
    assert by_branch["candidate/aged/single"].action_taken == "suppressed-stale-fetch"
    assert by_branch["candidate/merged/single"].action_taken == "deleted"


# ---------------------------------------------------------------------------
# Task 2.2 — CLI: dry-run default + --slug scope + --json
# ---------------------------------------------------------------------------


def _fake_pr(state):
    import pr_state as ps

    def _f(branch, cwd=None):
        return ps.PrVerdict(state=state, merged_at=None, evidence={})
    return _f


def test_cli_dry_run_default_and_slug_scope(tmp_path, monkeypatch, capsys):
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")
    add_local_candidate(work, "candidate/b/single")
    push_candidate(work, "candidate/b/single")
    # Parent MERGED → both would be deletable, so dry-run inertness is meaningful.
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))

    # No --apply → dry-run default: prints, mutates NOTHING, exits 0.
    rc = cli.main(["--repo", str(work)])
    assert rc == 0
    assert local_ref_exists(work, "candidate/a/single")
    assert remote_ref_exists(work, "candidate/a/single")
    assert local_ref_exists(work, "candidate/b/single")
    assert remote_ref_exists(work, "candidate/b/single")

    # --slug a scopes the report to candidate/a/*.
    capsys.readouterr()
    rc = cli.main(["--repo", str(work), "--slug", "a"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "candidate/a/single" in out
    assert "candidate/b/single" not in out

    # --json emits a machine-readable object (rows + verdicts), still scoped.
    rc = cli.main(["--repo", str(work), "--slug", "a", "--json"])
    payload = capsys.readouterr().out
    import json as _json
    data = _json.loads(payload)
    rows = data["rows"]
    assert rc == 0
    assert isinstance(rows, list) and rows
    assert {r["slug"] for r in rows} == {"a"}
    assert "verdicts" in data


def test_cli_enumeration_failure_deletes_nothing_under_apply(tmp_path, monkeypatch, capsys):
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/z/single")
    push_candidate(work, "candidate/z/single")
    # Would be deletable (MERGED) — but the fail-closed raise must beat apply.
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))

    def boom(repo):
        raise RuntimeError("git worktree list failed (simulated)")

    monkeypatch.setattr(gcb, "_live_worktree_slugs", boom)

    rc = cli.main(["--repo", str(work), "--apply"])
    err = capsys.readouterr().err

    # Fail-closed: nothing deleted, still exits 0, reports the failure.
    assert rc == 0
    assert local_ref_exists(work, "candidate/z/single")
    assert remote_ref_exists(work, "candidate/z/single")
    assert "nothing deleted" in err


def test_cli_batch_size_zero_no_traceback(tmp_path, monkeypatch, capsys):
    """--batch-size 0 must not ValueError out of main (reporter still exits 0)."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")
    # MERGED → a deletable REMOTE row, so the batching loop actually iterates;
    # pre-fix range(0, n, 0) raised ValueError OUTSIDE the CLI try/except.
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))

    rc = cli.main(["--repo", str(work), "--batch-size", "0"])
    err = capsys.readouterr().err

    assert rc == 0                       # no traceback; reporter contract intact
    assert "clamping to 1" in err        # the bogus value is surfaced, not silent
    # Dry-run default: the bogus batch size deletes nothing unexpectedly.
    assert remote_ref_exists(work, "candidate/a/single")
    assert local_ref_exists(work, "candidate/a/single")


def test_cli_json_apply_emits_delete_verdicts(tmp_path, monkeypatch, capsys):
    """--json --apply must surface the delete outcomes, not only classification."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    push_candidate(work, "candidate/a/single")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("MERGED"))

    rc = cli.main(["--repo", str(work), "--slug", "a", "--json", "--apply"])
    payload = capsys.readouterr().out
    import json as _json
    data = _json.loads(payload)

    assert rc == 0
    # A destructive run is machine-observable: verdicts carry the real outcomes.
    assert "verdicts" in data and data["verdicts"]
    assert "deleted" in {v["action_taken"] for v in data["verdicts"]}
    for v in data["verdicts"]:
        assert {"branch", "surface", "action_taken", "command"} <= set(v)
    # Verdicts reflect genuine deletes — the remote ref is really gone.
    assert not remote_ref_exists(work, "candidate/a/single")


def test_cli_main_delegate(tmp_path, monkeypatch):
    """gc_candidate_branches.main delegates to the CLI (the documented entry)."""
    origin, work = make_origin_and_work(tmp_path)
    add_local_candidate(work, "candidate/a/single")
    monkeypatch.setattr(gcb, "pr_state", _fake_pr("NO_PR"))
    assert gcb.main(["--repo", str(work)]) == 0
