"""test_ci_gate_run.py — Task 2.3: run the declared gate command, then stamp.

`ci_gate_run.main(argv=None)` resolves the repo and the gate command (from
`--command`, else the repo config's `ci.gate_command`), captures HEAD and the
working-tree dirty state, runs the command through the shell at the repo root,
and — on exit 0 — writes the head stamp via `ci_local_stamp.write_stamp` with
the captured head/dirty as drift guards.

Red pins (consumer-repo-parity 2.3):
  * `--command true`          -> rc 0 and a stamp `pred_ci_local_stamp` PASSes;
  * `--command "exit 3"`      -> rc 3, no stamp;
  * dirty start (untracked f) -> rc 1 with the `StampError` text, no stamp;
  * a command that commits    -> rc 1 (head moved), no stamp;
  * `ci.gate_command` from config (no `--command`) is used;
  * key missing and `null`    -> rc 2 with the first-run pointer;
  * impl-audit F2 / A2-F1: refusals list the dirty paths (untracked ->
    `.gitignore`); only allowlisted cache output (__pycache__/**/*.pyc,
    .pytest_cache/**, .coverage[.*]) created by a clean run is stamped and
    reported — any other new untracked path, a tracked change, or a HEAD move
    mid-run refuses; status samples are --untracked-files=all.

Git-backed tests build a real repo in `tmp_path` and scrub inherited `GIT_*` env
(same pattern as `skills/_shared/fixtures/foreign_repo.py` / the 2.1 sibling).
Stdlib only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure _shared/ is on sys.path
_SHARED_DIR = Path(__file__).resolve().parent
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

import ci_gate_run      # noqa: E402
import ci_local_stamp   # noqa: E402

# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_DIR / GIT_CONFIG_* (same pattern as fixtures/foreign_repo.py / 2.1 sibling).
_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, env=_CLEAN_ENV,
    )
    return result.stdout.strip()


def _make_repo(tmp_path: Path, config: "dict | None" = None) -> tuple[Path, str]:
    """A scratch git repo with one commit; return (root, head_sha).

    When `config` is given it is committed as `.three-pillars/config.json`
    (schema-valid), so the working tree starts CLEAN — a config file left
    untracked would itself trip the dirty-start guard and muddy the case under
    test. The stamp lives under the git dir (never in the tree), so it does not
    affect this cleanliness.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "x.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t23@test.local")
    _git(root, "config", "user.name", "T23 Fixture")
    if config is not None:
        cfg_dir = root / ".three-pillars"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root, _git(root, "rev-parse", "HEAD")


def _stamp(root: Path):
    return ci_local_stamp.read_stamp(root)


def _stamp_pred(root: Path, head: str):
    return ci_local_stamp.pred_ci_local_stamp(head, repo_root=str(root))


class TestSuccessPath:
    """rc 0 + a clean, head-matching stamp that pred_ci_local_stamp PASSes."""

    def test_true_writes_passing_stamp(self, tmp_path):
        root, head = _make_repo(tmp_path)
        rc = ci_gate_run.main(["--repo", str(root), "--command", "true"])
        assert rc == 0
        stamp = _stamp(root)
        assert stamp is not None
        assert stamp["head_sha"] == head
        assert stamp["dirty"] is False
        result = _stamp_pred(root, head)
        assert result.verdict == ci_local_stamp.GateVerdict.PASS, result.detail


class TestNonZeroRcPassthrough:
    """A non-zero command rc is returned as-is; nothing is stamped."""

    def test_exit_3_passthrough_no_stamp(self, tmp_path):
        root, _head = _make_repo(tmp_path)
        rc = ci_gate_run.main(["--repo", str(root), "--command", "exit 3"])
        assert rc == 3, f"RC-PASSTHROUGH: the failing command's rc 3 came back as {rc}"
        stamp = _stamp(root)
        assert stamp is None, f"RC-PASSTHROUGH: a failing gate run wrote a stamp: {stamp!r}"


class TestDriftRefusal:
    """write_stamp's drift guards refuse (exit 1) and write no stamp."""

    def test_dirty_start_refuses(self, tmp_path, capsys):
        root, _head = _make_repo(tmp_path)
        (root / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")
        rc = ci_gate_run.main(["--repo", str(root), "--command", "true"])
        assert rc == 1
        assert _stamp(root) is None
        assert "uncommitted" in capsys.readouterr().err

    def test_command_that_commits_moves_head_refuses(self, tmp_path, monkeypatch, capsys):
        root, _head = _make_repo(tmp_path)
        # Scrub ambient GIT_* so the command's `git commit` targets THIS repo.
        for var in [k for k in os.environ if k.startswith("GIT_")]:
            monkeypatch.delenv(var, raising=False)
        cmd = "printf c > c.txt && git add c.txt && git commit -q -m c"
        rc = ci_gate_run.main(["--repo", str(root), "--command", cmd])
        assert rc == 1
        assert _stamp(root) is None
        assert "HEAD drifted" in capsys.readouterr().err


class TestConfigGateCommand:
    """The command resolves from `ci.gate_command` when `--command` is absent."""

    def test_config_command_is_used(self, tmp_path):
        root, head = _make_repo(
            tmp_path, config={"schema_version": 1, "ci": {"gate_command": "true"}}
        )
        rc = ci_gate_run.main(["--repo", str(root)])  # no --command
        assert rc == 0
        stamp = _stamp(root)
        assert stamp is not None and stamp["head_sha"] == head
        assert _stamp_pred(root, head).verdict == ci_local_stamp.GateVerdict.PASS


class TestNoCommandDeclared:
    """Key missing or null -> exit 2 with the first-run pointer on stderr."""

    @pytest.mark.parametrize("config", [
        {"schema_version": 1},  # key missing
        {"schema_version": 1, "ci": {"gate_command": None}},  # key null
    ])
    def test_no_command_exits_2_with_pointer(self, tmp_path, config, capsys):
        root, _head = _make_repo(tmp_path, config=config)
        rc = ci_gate_run.main(["--repo", str(root)])  # no --command
        assert rc == 2
        assert "no ci.gate_command declared" in capsys.readouterr().err


def test_branch_backstop_refuses_to_stamp(tmp_path):
    """Task 5.5: `ci_gate_run` runs `hot_patch_check --branch-trailered` before
    the gate command — an over-cap trailered commit on the branch refuses the
    run (rc 1) before the command ever executes, and nothing is stamped."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t55@test.local")
    _git(root, "config", "user.name", "T55 Fixture")
    (root / "README.md").write_text("init\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-q", "-m", "init")

    _git(root, "checkout", "-q", "-b", "tp/x")
    big = root / "pkg" / "big.py"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_text("".join(f"line {i}\n" for i in range(200)), encoding="utf-8")
    _git(root, "add", "pkg/big.py")
    _git(root, "commit", "-q", "-m", "Hotfix: big", "-m", "hot-patch: x")

    rc = ci_gate_run.main(["--repo", str(root), "--command", "true"])
    assert rc == 1
    assert _stamp(root) is None


# ---------------------------------------------------------------------------
# impl-audit F2 / A2-F1: actionable refusals for untracked paths. Both status
# samples run with --untracked-files=all (per-file listing, immune to a
# repo-local status.showUntrackedFiles=no). The START sample stays
# untracked-inclusive (an untracked conftest.py can change test results); both
# refusals list the offending paths and point untracked ones at .gitignore.
# POST-run, a new untracked path is stamped (and reported as needing an ignore
# rule) ONLY when it is a known test/bytecode cache: a .pyc under a __pycache__
# component, anything under a .pytest_cache component, or a `.coverage` /
# `.coverage.*` data file. Every other new untracked path (conftest.py,
# sitecustomize.py, a sourceless .pyc, build/, .coveragerc, ...) can alter the
# outcome, so it refuses. A tracked change or a HEAD move mid-run still refuses.
# ---------------------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    for var in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(var, raising=False)
    return _make_repo(tmp_path)[0]


def _run(root: Path, command: str) -> int:
    return ci_gate_run.main(["--repo", str(root), "--command", command])


def test_untracked_start_refusal_lists_paths_and_points_at_gitignore(repo, capsys):
    (repo / "junk.log").write_text("x\n", encoding="utf-8")
    assert _run(repo, "true") == 1
    err = capsys.readouterr().err
    assert "started with uncommitted" in err
    assert "junk.log" in err and ".gitignore" in err
    assert "stash/revert" not in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_tracked_start_refusal_lists_the_modified_file(repo, capsys):
    (repo / "x.txt").write_text("edited\n", encoding="utf-8")
    assert _run(repo, "true") == 1
    err = capsys.readouterr().err
    assert "x.txt" in err and "commit" in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_gate_output_is_stamped_and_reported_as_needing_an_ignore_rule(repo, capsys):
    head = _git(repo, "rev-parse", "HEAD")
    pyc = "__pycache__/m.cpython-312.pyc"
    assert _run(repo, f"mkdir -p __pycache__ && touch {pyc}") == 0
    err = capsys.readouterr().err
    assert pyc in err and ".gitignore" in err
    stamp = ci_local_stamp.read_stamp(repo)
    assert stamp is not None and stamp["head_sha"] == head and stamp["dirty"] is False
    pred = ci_local_stamp.pred_ci_local_stamp(head, repo_root=str(repo))
    assert pred.verdict == ci_local_stamp.GateVerdict.PASS, pred.detail

    # The un-ignored output now makes the NEXT run start dirty: actionable refusal.
    assert _run(repo, "true") == 1
    err = capsys.readouterr().err
    assert pyc in err and ".gitignore" in err


def _touch_cmd(path: str) -> str:
    parent = path.rsplit("/", 1)[0] if "/" in path else "."
    return f"mkdir -p '{parent}' && touch '{path}'"


@pytest.mark.parametrize("path", [
    "__pycache__/x.cpython-312.pyc",
    "pkg/sub/__pycache__/m.cpython-312.opt-1.pyc",
    ".pytest_cache/v/cache/nodeids",
    "tests/.pytest_cache/README.md",
    ".coverage",
    ".coverage.host.1234.XyZ",
    "sub/.coverage",
])
def test_allowlisted_cache_output_mid_run_is_stamped_and_reported(repo, capsys, path):
    head = _git(repo, "rev-parse", "HEAD")
    assert _run(repo, _touch_cmd(path)) == 0
    err = capsys.readouterr().err
    assert path in err and ".gitignore" in err
    stamp = ci_local_stamp.read_stamp(repo)
    assert stamp is not None and stamp["head_sha"] == head and stamp["dirty"] is False


@pytest.mark.parametrize("path", [
    "conftest.py",                           # can skip every test
    "tests/new/conftest.py",                 # new directory: listed per file
    "x.pyc",                                 # sourceless .pyc shadows imports
    "pkg/x.pyc",
    "not__pycache__/x.pyc",                  # whole-component match only
    "__pycache__/evil.py",                   # only .pyc under __pycache__
    "sitecustomize.py",
    ".coveragerc",                           # can override fail_under
    ".coverage_evil",
    "build/out.o",                           # no directory-prefix acceptance
    "dist/pkg-1.0-py3-none-any.whl",
    "pkg.egg-info/entry_points.txt",
    ".mypy_cache/3.12/x.json",
    ".pytest_cache",                         # a FILE, not a cache component
])
def test_non_allowlisted_untracked_path_mid_run_refuses(repo, capsys, path):
    assert _run(repo, _touch_cmd(path)) == 1
    err = capsys.readouterr().err
    assert "dirty state changed" in err
    assert path in err and ".gitignore" in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_allowlisted_plus_foreign_output_mid_run_refuses(repo, capsys):
    cmd = f"{_touch_cmd('__pycache__/a.cpython-312.pyc')} && touch conftest.py"
    assert _run(repo, cmd) == 1
    err = capsys.readouterr().err
    assert "conftest.py" in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_show_untracked_files_no_does_not_hide_a_start_conftest(repo, capsys):
    _git(repo, "config", "status.showUntrackedFiles", "no")
    (repo / "conftest.py").write_text("x = 1\n", encoding="utf-8")
    assert _run(repo, "true") == 1
    err = capsys.readouterr().err
    assert "started with uncommitted" in err and "conftest.py" in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_show_untracked_files_no_does_not_hide_a_mid_run_conftest(repo, capsys):
    _git(repo, "config", "status.showUntrackedFiles", "no")
    assert _run(repo, "mkdir -p tests/new && touch tests/new/conftest.py") == 1
    assert "tests/new/conftest.py" in capsys.readouterr().err
    assert ci_local_stamp.read_stamp(repo) is None


def test_ignored_gate_output_is_silent(repo, capsys):
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore build")
    assert _run(repo, "mkdir -p build && touch build/out.o") == 0
    assert ".gitignore" not in capsys.readouterr().err
    assert _run(repo, "mkdir -p build && touch build/out.o") == 0


def test_tracked_change_mid_run_still_refuses(repo, capsys):
    assert _run(repo, "echo more >> x.txt") == 1
    err = capsys.readouterr().err
    assert "dirty state changed" in err and "x.txt" in err
    assert ci_local_stamp.read_stamp(repo) is None


def test_tracked_change_plus_output_mid_run_still_refuses(repo, capsys):
    assert _run(repo, "echo more >> x.txt && touch out.o") == 1
    assert "dirty state changed" in capsys.readouterr().err
    assert ci_local_stamp.read_stamp(repo) is None


def test_head_move_mid_run_still_refuses(repo, capsys):
    assert _run(repo, "touch c.txt && git add c.txt && git commit -q -m c") == 1
    assert "HEAD drifted" in capsys.readouterr().err
    assert ci_local_stamp.read_stamp(repo) is None


def test_status_paths_parses_renames_and_non_ascii(repo):
    _git(repo, "mv", "x.txt", "y.txt")
    (repo / "über.log").write_text("x\n", encoding="utf-8")
    (repo / "newdir").mkdir()
    (repo / "newdir" / "a.py").write_text("x\n", encoding="utf-8")
    tracked, untracked = ci_local_stamp._status_paths(repo)
    assert tracked == ["y.txt"]
    assert sorted(untracked) == ["newdir/a.py", "über.log"]  # per file, not "newdir/"


def test_long_listings_are_truncated(repo, capsys):
    for i in range(15):
        (repo / f"junk{i:02d}.log").write_text("x\n", encoding="utf-8")
    assert _run(repo, "true") == 1
    err = capsys.readouterr().err
    assert "junk00.log" in err and "(+5 more)" in err
