"""Tests for gate_cli.py's `--repo <path>` flag — task 8.2 (dispatch-from-seat
ACTIVATION mechanism, Phase 8).

Split from test_gate_cli.py (already past the 300L soft-warn at the time this task
landed) per plan.md's named escape hatch — a NEW dedicated module for the new flag,
existing strict-parse tests in test_gate_cli.py stay in place and stay green.

Run with: pytest skills/tp-merge-from-main/scripts/test_gate_cli_repo.py -q
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

SHARED = Path(__file__).resolve().parent.parent.parent / "_shared"
sys.path.insert(0, str(SHARED))

_LOOP_DIR = Path(__file__).resolve().parent.parent.parent / "tp-pr-iterate" / "scripts"
if str(_LOOP_DIR) not in sys.path:
    sys.path.insert(0, str(_LOOP_DIR))

from deterministic_gate import GATE_LABEL, GateOutcome, GateVerdict  # noqa: E402
from gate_cli import main  # noqa: E402

PR_URL = "https://github.com/example/repo/pull/42"


def _make_pass_outcome() -> GateOutcome:
    return GateOutcome(verdict=GateVerdict.PASS, blocking=[], label=GATE_LABEL)


def _git_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    return repo


class TestRepoFlagThreading:
    def test_repo_flag_resolves_toplevel_and_threads_repo_root(self, tmp_path):
        """--repo <path> resolves to the git toplevel and calls
        evaluate_fn(pr_url, repo_root=<resolved toplevel>)."""
        repo = _git_repo(tmp_path)
        nested = repo / "sub" / "dir"
        nested.mkdir(parents=True)

        captured = {}

        def evaluate_fn(pr_url, *, repo_root=None):
            captured["pr_url"] = pr_url
            captured["repo_root"] = repo_root
            return _make_pass_outcome()

        # --repo may point at a NON-toplevel path inside the repo — it must still
        # resolve to the repo's toplevel (mirrors `git -C <path> rev-parse
        # --show-toplevel`'s own behavior from a nested cwd).
        exit_code = main(["--repo", str(nested), PR_URL], evaluate_fn=evaluate_fn)

        assert exit_code == 0
        assert captured["pr_url"] == PR_URL
        assert captured["repo_root"] == str(repo.resolve())

    def test_no_repo_flag_call_shape_unchanged(self):
        """Without --repo, evaluate_fn is called as evaluate_fn(pr_url) — the EXACT
        pre-task-8.2 call shape, so single-arg test doubles keep working."""
        captured = {}

        def evaluate_fn(pr_url):  # no repo_root param at all — would TypeError if called with one
            captured["pr_url"] = pr_url
            return _make_pass_outcome()

        exit_code = main([PR_URL], evaluate_fn=evaluate_fn)

        assert exit_code == 0
        assert captured["pr_url"] == PR_URL


class TestRepoFlagUsageErrors:
    def test_repo_path_that_does_not_resolve_is_usage_error(self, tmp_path, capsys):
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()

        exit_code = main(["--repo", str(not_a_repo), PR_URL], evaluate_fn=lambda **k: _make_pass_outcome())

        assert exit_code == 2
        out = capsys.readouterr().out
        assert GATE_LABEL in out
        assert "INDETERMINATE" in out

    def test_repo_flag_without_value_is_usage_error(self, capsys):
        exit_code = main(["--repo"], evaluate_fn=lambda **k: _make_pass_outcome())
        assert exit_code == 2
        assert "INDETERMINATE" in capsys.readouterr().out

    def test_repo_flag_missing_pr_url_is_usage_error(self, tmp_path, capsys):
        repo = _git_repo(tmp_path)
        exit_code = main(["--repo", str(repo)], evaluate_fn=lambda **k: _make_pass_outcome())
        assert exit_code == 2
        assert "INDETERMINATE" in capsys.readouterr().out

    def test_other_flag_is_still_usage_error(self, capsys):
        """--repo is the ONLY recognized option — any other flag stays a usage error."""
        exit_code = main(["--foo", PR_URL])
        assert exit_code == 2
        assert "INDETERMINATE" in capsys.readouterr().out

    def test_extra_positionals_with_repo_flag_is_usage_error(self, tmp_path, capsys):
        repo = _git_repo(tmp_path)
        exit_code = main(["--repo", str(repo), PR_URL, "extra"])
        assert exit_code == 2
        assert "INDETERMINATE" in capsys.readouterr().out

    def test_duplicate_repo_flag_is_usage_error(self, tmp_path, capsys):
        repo = _git_repo(tmp_path)
        exit_code = main(["--repo", str(repo), "--repo", str(repo), PR_URL])
        assert exit_code == 2
        assert "INDETERMINATE" in capsys.readouterr().out
