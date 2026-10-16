"""Tests for the /tp-merge unnumbered-issue-ID refusal (design: basesync-autoresolve-coverage).

`placeholder_gate` finds `### <S>-new-<slug>` headings in the PR *head* commit's issue
files; the `land.py` CLI (main) refuses before the gate, library `land()` never checks.

Run with: pytest skills/tp-merge/scripts/test_land_placeholder.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent.parent / "_shared"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "tp-merge-from-main" / "scripts"))
sys.path.insert(0, str(SHARED))

import land  # noqa: E402
import placeholder_gate  # noqa: E402
from task_scope import _git_env as clean_git_env  # noqa: E402  shipped scrub; git_env is dev-only

PR_URL = "https://github.com/example/repo/pull/7"
KNOWN = "three-pillars-docs/known_issues.md"
RESOLVED = "three-pillars-docs/known_issues_resolved.md"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
PLACEHOLDER_DOC = "# Known issues\n\n### M-new-x: a thing\n\nbody\n\n### L-new-y-z (note)\n"
NUMBERED_DOC = "# Known issues\n\n### M7: a thing\n\nbody\n"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=clean_git_env(**IDENTITY)).stdout.strip()


def commit_issue_file(repo: Path, text: str, path: str = KNOWN) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", "--", path)
    git(repo, "commit", "-q", "-m", "issues")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    return r


@pytest.fixture
def split_repo(repo) -> tuple:
    """(repo, pr_sha): checked-out HEAD is numbered; the PR head commit is on another
    branch (not checked out) and still holds a placeholder."""
    commit_issue_file(repo, NUMBERED_DOC)
    git(repo, "checkout", "-q", "-b", "pr")
    pr_sha = commit_issue_file(repo, PLACEHOLDER_DOC)
    git(repo, "checkout", "-q", "main")
    return repo, pr_sha


class TestUnnumberedIds:
    def test_returns_sorted_placeholder_ids(self):
        texts = {KNOWN: PLACEHOLDER_DOC, RESOLVED: "### H-new-a: gone\n"}
        assert placeholder_gate.unnumbered_ids(texts) == ["H-new-a", "L-new-y-z", "M-new-x"]

    def test_empty_when_none(self):
        assert placeholder_gate.unnumbered_ids({KNOWN: NUMBERED_DOC}) == []

    def test_empty_when_files_absent(self):
        assert placeholder_gate.unnumbered_ids({}) == []
        assert placeholder_gate.unnumbered_ids({"other.md": PLACEHOLDER_DOC}) == []

    def test_citation_without_heading_is_not_unnumbered(self):
        assert placeholder_gate.unnumbered_ids({KNOWN: "see M-new-x in prose\n"}) == []


class TestUnnumberedIdsAt:
    def test_reads_committed_blob_not_worktree(self, repo):
        commit_issue_file(repo, PLACEHOLDER_DOC)
        (repo / KNOWN).write_text(NUMBERED_DOC, encoding="utf-8")  # uncommitted edit
        assert placeholder_gate.unnumbered_ids_at(repo, "HEAD") == ["L-new-y-z", "M-new-x"]

    def test_reads_every_issue_file_and_skips_missing(self, repo):
        commit_issue_file(repo, "# Known issues\n")
        sha = commit_issue_file(repo, "### H-new-a: old\n", path=RESOLVED)
        assert placeholder_gate.unnumbered_ids_at(str(repo), sha) == ["H-new-a"]

    def test_no_issue_files_is_empty(self, repo):
        commit_issue_file(repo, "x\n", path="README.md")
        assert placeholder_gate.unnumbered_ids_at(repo, "HEAD") == []

    def test_unresolvable_ref_raises(self, repo):
        commit_issue_file(repo, NUMBERED_DOC)
        with pytest.raises(placeholder_gate.PlaceholderGateError):
            placeholder_gate.unnumbered_ids_at(repo, "no-such-ref")


class TestHeadUnnumberedIds:
    def test_reads_pr_head_not_local_head(self, split_repo):
        repo, pr_sha = split_repo
        assert placeholder_gate.unnumbered_ids_at(repo, "HEAD") == []
        got = placeholder_gate.head_unnumbered_ids(
            PR_URL, repo, pr_state_fn=lambda url: {"headRefOid": pr_sha})
        assert got == ["L-new-y-z", "M-new-x"]

    def test_default_pr_state_fn_is_the_live_gate_fetch(self, split_repo, monkeypatch):
        import deterministic_gate
        repo, pr_sha = split_repo
        seen = []

        def live(url):
            seen.append(url)
            return {"headRefOid": pr_sha}

        monkeypatch.setattr(deterministic_gate, "_live_pr_state_fn", live)
        assert placeholder_gate.head_unnumbered_ids(PR_URL, repo) == ["L-new-y-z", "M-new-x"]
        assert seen == [PR_URL]

    def test_numbered_head_is_clean(self, split_repo):
        repo, _ = split_repo
        head = git(repo, "rev-parse", "HEAD")
        assert placeholder_gate.head_unnumbered_ids(
            PR_URL, repo, pr_state_fn=lambda url: {"headRefOid": head}) == []

    @pytest.mark.parametrize("payload", [{}, {"headRefOid": ""}, {"headRefOid": None},
                                         {"headRefOid": "--upload-pack=x"}, None, []])
    def test_payload_without_usable_head_raises(self, split_repo, payload):
        repo, _ = split_repo
        with pytest.raises(placeholder_gate.PlaceholderGateError):
            placeholder_gate.head_unnumbered_ids(PR_URL, repo, pr_state_fn=lambda url: payload)

    def test_sha_missing_after_failed_fetch_raises(self, split_repo):
        repo, _ = split_repo  # no `origin` remote: the fetch fails
        with pytest.raises(placeholder_gate.PlaceholderGateError, match="fetch"):
            placeholder_gate.head_unnumbered_ids(
                PR_URL, repo, pr_state_fn=lambda url: {"headRefOid": "ab" * 20})

    def test_sha_still_missing_after_fetch_raises(self, split_repo):
        repo, _ = split_repo
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd[3:])
            rc = 1 if cmd[3] == "cat-file" else 0
            return subprocess.CompletedProcess(cmd, rc, "", "")

        with pytest.raises(placeholder_gate.PlaceholderGateError, match="still missing"):
            placeholder_gate.head_unnumbered_ids(
                PR_URL, repo, pr_state_fn=lambda url: {"headRefOid": "ab" * 20}, run=run)
        assert [c[0] for c in calls] == ["cat-file", "fetch", "cat-file"]
        assert calls[1] == ["fetch", "origin", "ab" * 20]

    def test_local_commit_is_not_fetched(self, split_repo):
        repo, pr_sha = split_repo
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd[3])
            return subprocess.run(cmd, **kwargs)

        placeholder_gate.head_unnumbered_ids(
            PR_URL, repo, pr_state_fn=lambda url: {"headRefOid": pr_sha}, run=run)
        assert "fetch" not in calls

    def test_pr_state_error_propagates(self, split_repo):
        repo, _ = split_repo

        def boom(url):
            raise RuntimeError("gh pr view failed: nope")

        with pytest.raises(RuntimeError, match="gh pr view failed"):
            placeholder_gate.head_unnumbered_ids(PR_URL, repo, pr_state_fn=boom)


class TestLandMainRefusal:
    """`main` runs the unnumbered-ID check after the gate PASSES and before the merge."""

    @pytest.fixture
    def gate(self, monkeypatch):
        seen = []

        def passing(pr_url, *, config=None, **kw):
            seen.append(kw)
            return object()

        monkeypatch.setattr(land, "require_merge_gate_pass", passing)
        monkeypatch.setattr(land, "_load_repo_config",
                            lambda *a, **k: {"review": {"require_human_approval": True}})
        monkeypatch.setattr(land, "_print_roster", lambda outcome: None)
        return seen

    @pytest.fixture
    def recorded(self, monkeypatch, repo, gate):
        monkeypatch.chdir(repo)
        merges = []
        monkeypatch.setattr(land, "_gh_pr_merge", merges.append)
        return merges

    def test_refuses_on_unnumbered_ids_and_never_lands(self, monkeypatch, recorded, repo, capsys):
        seen = []

        def fake(pr_url, repo_root, **kw):
            seen.append((pr_url, repo_root))
            return ["L-new-y-z", "M-new-x"]

        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids", fake)
        assert land.main([PR_URL]) == 2
        out = capsys.readouterr().out
        assert "unnumbered issue IDs: run number_issues.py" in out
        for issue_id in ("L-new-y-z", "M-new-x"):
            assert issue_id in out, f"refusal must name every unnumbered ID; missing {issue_id}"
        assert recorded == []
        assert seen == [(PR_URL, str(repo.resolve()))]

    def test_multiple_ids_are_all_named(self, monkeypatch, recorded, capsys):
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids",
                            lambda *a, **k: ["L-new-y", "M-new-x"])
        assert land.main([PR_URL]) == 2
        assert "L-new-y, M-new-x" in capsys.readouterr().out
        assert recorded == []

    def test_refuses_when_check_raises(self, monkeypatch, recorded, capsys):
        def boom(*a, **k):
            raise RuntimeError("gh pr view failed:\nno network")

        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids", boom)
        assert land.main([PR_URL]) == 2
        lines = [l for l in capsys.readouterr().out.splitlines() if "gh pr view failed" in l]
        assert len(lines) == 1 and lines[0].startswith("REFUSED — cannot check the PR head")
        assert recorded == []

    def test_clean_head_lands(self, monkeypatch, recorded, gate):
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids", lambda *a, **k: [])
        assert land.main([PR_URL]) == 0
        assert recorded == [PR_URL]
        assert gate == [{}]

    def test_clean_head_with_repo_flag_lands_with_repo_root(self, monkeypatch, recorded, repo, gate):
        seen = []
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids",
                            lambda pr_url, repo_root, **k: seen.append(repo_root) or [])
        assert land.main(["--repo", str(repo), PR_URL]) == 0
        assert recorded == [PR_URL]
        assert gate == [{"repo_root": str(repo.resolve())}]
        assert seen == [str(repo.resolve())]

    def test_blocked_gate_prints_its_refusal_and_never_runs_the_check(self, monkeypatch, repo, capsys):
        """The plugin-parity A6 shape: a gate that refuses reports its own predicates first."""
        monkeypatch.chdir(repo)

        def blocked(pr_url, *, config=None, **kw):
            outcome = SimpleNamespace(verdict=SimpleNamespace(value="INDETERMINATE"), blocking=[])
            raise land.MergeGateBlocked(outcome)

        monkeypatch.setattr(land, "require_merge_gate_pass", blocked)
        monkeypatch.setattr(land, "_load_repo_config",
                            lambda *a, **k: {"review": {"require_human_approval": True}})
        monkeypatch.setattr(land, "_gh_pr_merge", lambda *a: pytest.fail("must not merge"))
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids",
                            lambda *a, **k: pytest.fail("check must not run on a blocked gate"))
        assert land.main([PR_URL]) == 2
        assert "merge gate did not PASS" in capsys.readouterr().out

    def test_unresolvable_cwd_refuses_before_check(self, monkeypatch, recorded, tmp_path):
        monkeypatch.setattr(land, "_resolve_repo_toplevel", lambda path: None)
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids",
                            lambda *a, **k: pytest.fail("must not run"))
        monkeypatch.setattr(land, "require_merge_gate_pass",
                            lambda *a, **k: pytest.fail("must not gate"))
        assert land.main([PR_URL]) == 2
        assert recorded == []

    def test_usage_error_runs_no_check(self, monkeypatch, recorded):
        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids",
                            lambda *a, **k: pytest.fail("must not run"))
        assert land.main([]) == 2
        assert land.main(["--flag", PR_URL]) == 2


class TestLibraryLandNeverReadsAmbientCheckout:
    def test_land_does_not_run_the_check(self, monkeypatch):
        def forbidden(*a, **k):
            raise AssertionError("library land() must never run the placeholder check")

        monkeypatch.setattr(placeholder_gate, "head_unnumbered_ids", forbidden)
        monkeypatch.setattr(placeholder_gate, "unnumbered_ids_at", forbidden)
        merged = []
        rc = land.land(
            PR_URL,
            require_fn=lambda pr_url, *, config=None: object(),
            merge_fn=merged.append,
            config={"review": {"require_human_approval": True}},
        )
        assert rc == 0
        assert merged == [PR_URL]
