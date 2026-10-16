"""test_changed_tests_runs.py — the head-bound 3-run record (design: fragile-test-prevention,
detailed-design-stages.md Part C4).

Oracle: ``example``. Each case builds a real tmp git repo, commits a change, and calls
`changed_tests_runs.record` / `read` over it with the real pytest runner the repo's own config
resolves. The verdict table is the spec's: no changed tests is a pass with no targets; three
green runs pass; a flaky test that fails on its second run fails; a non-pytest or absent runner
is ``unverified`` with the runner's own reason; `read` returns the record for its own head only.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import changed_tests_runs as ctr
import task_scope  # the shipped env scrub and runner resolution; git_env is dev-only
import task_scope_runner

IDENTITY = {"GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@test",
            "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@test"}
OK_TEST = "def test_ok():\n    assert 1 + 1 == 2\n"
RED_TEST = "def test_red():\n    assert 1 + 1 == 3\n"
OTHER_RUNNER = {".three-pillars/config.json": json.dumps(
    {"schema_version": 1, "test": {"command": "make test", "runner": "other"}})}


def git(repo, *args):
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True, env=task_scope._git_env(**IDENTITY))
    return done.stdout.strip()


def commit(repo, files, message="change"):
    for rel, text in files.items():
        path = Path(repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path, files=None):
    """A repo with one base commit → ``(repo, base sha)``; ``files`` replace the defaults."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    base = commit(repo, files or {"pytest.ini": "[pytest]\n", "lib.py": "VALUE = 1\n"}, "base")
    return repo, base


def runs_file(repo):
    return Path(repo) / ".git" / "three-pillars" / "fragility" / "runs.json"


def test_no_changed_tests_passes_with_no_targets(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"lib.py": "VALUE = 2\n", "notes.md": "text\n"})
    out = ctr.record(repo, base, head)
    assert out["written"] is True
    assert (out["verdict"], out["targets"]) == ("pass", [])


def test_three_green_runs_pass(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    out = ctr.record(repo, base, head)
    assert out["verdict"] == "pass"
    assert out["targets"] == ["test_ok.py"]
    assert out["runs"] == ["pass"] * 3
    assert (out["head"], out["base"]) == (head, base)


def test_a_red_test_fails_on_the_first_run(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_red.py": RED_TEST, "test_ok.py": OK_TEST})
    out = ctr.record(repo, base, head)
    assert (out["verdict"], out["runs"]) == ("fail", ["fail"])


def test_a_flaky_test_failing_its_second_run_fails(tmp_path):
    counter = tmp_path / "counter.txt"
    flaky = ("from pathlib import Path\n\n"
             f"COUNTER = Path({str(counter)!r})\n\n\n"
             "def test_flaky():\n"
             "    seen = int(COUNTER.read_text(encoding='utf-8')) if COUNTER.exists() else 0\n"
             "    COUNTER.write_text(str(seen + 1))\n"
             "    assert seen != 1\n")
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_flaky.py": flaky})
    out = ctr.record(repo, base, head)
    assert (out["verdict"], out["runs"]) == ("fail", ["pass", "fail"])
    assert counter.read_text(encoding="utf-8") == "2"  # the loop stopped at the first non-pass run


def test_a_non_pytest_runner_is_unverified_with_the_runners_reason(tmp_path):
    repo, base = make_repo(tmp_path, {"lib.py": "VALUE = 1\n", **OTHER_RUNNER})
    head = commit(repo, {"test_ok.py": OK_TEST})
    runner, why = task_scope.resolve_runner(repo, None)
    out = ctr.record(repo, base, head)
    assert runner is None
    assert (out["verdict"], out["reason"]) == ("unverified", why)
    assert out["reason"] == task_scope_runner.NON_PYTEST_RUNNER
    assert ctr.read(repo, head)["verdict"] == "unverified"


def test_an_absent_runner_is_unverified_with_the_runners_reason(tmp_path):
    repo, base = make_repo(tmp_path, {"lib.py": "VALUE = 1\n"})
    head = commit(repo, {"test_ok.py": OK_TEST})
    _runner, why = task_scope.resolve_runner(repo, None)
    out = ctr.record(repo, base, head)
    assert (out["verdict"], out["reason"]) == ("unverified", why)


def test_read_returns_the_record_for_its_own_head_only(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    later = commit(repo, {"lib.py": "VALUE = 3\n"})
    assert ctr.read(repo, head) is None  # nothing recorded yet
    out = ctr.record(repo, base, head)
    assert ctr.read(repo, head) == {k: v for k, v in out.items() if k != "written"}
    assert ctr.read(repo, later) is None
    assert ctr.read(repo, base) is None
    assert ctr.read(repo, "0" * 40) is None


def test_the_record_holds_only_the_latest_head(tmp_path):
    repo, base = make_repo(tmp_path)
    first = commit(repo, {"test_ok.py": OK_TEST})
    ctr.record(repo, base, first)
    second = commit(repo, {"test_more.py": OK_TEST})
    ctr.record(repo, base, second)
    assert ctr.read(repo, first) is None
    assert ctr.read(repo, second)["targets"] == ["test_more.py", "test_ok.py"]


def test_the_record_is_written_atomically_under_the_git_dir(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    ctr.record(repo, base, head)
    assert json.loads(runs_file(repo).read_text(encoding="utf-8"))["head"] == head
    assert [p.name for p in runs_file(repo).parent.iterdir()] == ["runs.json"]
    assert git(repo, "status", "--porcelain") == ""  # nothing in the working tree


def test_read_treats_an_unreadable_record_as_missing(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    ctr.record(repo, base, head)
    runs_file(repo).write_text("{not json", encoding="utf-8")
    assert ctr.read(repo, head) is None


def test_changed_test_files_uses_the_runners_globs_and_skips_deletions(tmp_path):
    repo, base = make_repo(tmp_path, {
        "pytest.ini": "[pytest]\npython_files = check_*.py\n",
        "check_old.py": OK_TEST, "check_kept.py": OK_TEST, "test_named.py": OK_TEST})
    git(repo, "rm", "-q", "check_old.py")
    head = commit(repo, {"check_new.py": OK_TEST, "check_kept.py": OK_TEST + "\n",
                         "test_named.py": RED_TEST, "helper.py": "X = 1\n"})
    assert ctr.changed_test_files(repo, base, head) == ["check_kept.py", "check_new.py"]


def test_conftest_is_a_changed_test_file_but_never_a_run_target(tmp_path):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"conftest.py": "VALUE = 1\n", "test_ok.py": OK_TEST})
    assert ctr.changed_test_files(repo, base, head) == ["conftest.py", "test_ok.py"]
    out = ctr.record(repo, base, head)
    assert (out["verdict"], out["targets"]) == ("pass", ["test_ok.py"])


def test_cli_record_prints_the_record_and_exits_by_verdict(tmp_path, capsys):
    repo, base = make_repo(tmp_path)
    green = commit(repo, {"test_ok.py": OK_TEST})
    red = commit(repo, {"test_red.py": RED_TEST})
    assert ctr.main(["record", "--root", str(repo), "--base", base, "--head", green]) == 0
    assert json.loads(capsys.readouterr().out)["head"] == green
    assert ctr.main(["record", "--root", str(repo), "--base", base, "--head", red]) == 1
    assert json.loads(capsys.readouterr().out)["verdict"] == "fail"
    assert ctr.main(["record", "--root", str(repo), "--base", base, "--head", "0" * 40]) == 2
    assert json.loads(capsys.readouterr().out)["written"] is False


def test_cli_read_prints_the_record_for_the_head_else_exits_one(tmp_path, capsys):
    repo, base = make_repo(tmp_path)
    head = commit(repo, {"test_ok.py": OK_TEST})
    assert ctr.main(["read", "--root", str(repo), "--head", head]) == 1
    capsys.readouterr()
    ctr.record(repo, base, head)
    assert ctr.main(["read", "--root", str(repo), "--head", head]) == 0
    assert json.loads(capsys.readouterr().out)["head"] == head
    assert ctr.main(["read", "--root", str(repo), "--head", base]) == 1
