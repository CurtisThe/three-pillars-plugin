"""CLI tests for github_pr_author.py's explicit `--repo` argument.

`--repo` is a LOCAL repository path (where `.three-pillars/config.json`
lives), not a GitHub `owner/name` slug. An explicit `--repo` that is not an
existing directory must fail loud: otherwise the config lookup misses, the
helper takes the unconfigured plain path, and `gh pr create` silently runs
as the ambient gh account instead of the configured bot.

Run with: pytest skills/_shared/test_github_pr_author_repo_arg.py -q
"""

from __future__ import annotations

from test_github_pr_author_cli import _env_with_stub, _make_stub_gh, _run_cli


class TestExplicitRepoMustBeDirectory:
    def test_create_with_github_slug_exits_2_without_calling_gh(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["create", "--context", "manual", "--repo", "Acme/widget", "--", "--base", "master"],
            env,
            cwd=tmp_path,
        )
        assert result.returncode == 2
        assert "pull/1" not in result.stdout  # gh pr create never ran
        assert "-R" in result.stderr  # points at the gh passthrough form

    def test_resolve_with_missing_dir_exits_2(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        env = _env_with_stub(bin_dir)
        result = _run_cli(
            ["resolve", "--context", "manual", "--repo", str(tmp_path / "nope")], env
        )
        assert result.returncode == 2
        assert result.stdout.strip() == ""

    def test_verify_with_file_path_exits_2(self, tmp_path):
        bin_dir = _make_stub_gh(tmp_path)
        env = _env_with_stub(bin_dir)
        not_a_dir = tmp_path / "config.json"
        not_a_dir.write_text("{}", encoding="utf-8")
        result = _run_cli(["verify", "--repo", str(not_a_dir)], env)
        assert result.returncode == 2
