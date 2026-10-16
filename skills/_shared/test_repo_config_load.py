"""Tests for repo_config_load.load_repo_config, update_config and the `set` CLI.

design: consumer-repo-parity (Task 1.2). The loader never raises — it reads the
work tree or `HEAD`, degrades per key (invalid keys pruned, siblings kept), and
reports `ok` / `absent` / `unreadable`. The writer is atomic (temp + rename) and
fails loud: an invalid value, an unreadable file or a bad `schema_version`
raises with the file byte-identical; an absent file is seeded with
`{"schema_version": 1}` and is never half-created on an invalid value.
`repo_config_load.py set` is the shell entry point the skills' prose calls.
Run with: python3 -m pytest skills/_shared/test_repo_config_load.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repo_config_load as rcl  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "repo_config_load.py"
# GIT_* scrubbed so the fixture repo's own identity wins over any inherited
# GIT_CONFIG_* (same pattern as fixtures/foreign_repo.py).
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(root: Path, *args: str) -> None:
    env = dict(CLEAN_ENV)
    env["HOME"] = str(root)  # the fixture repo's local config, never the user's
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _repo(tmp_path: Path, *, committed: dict | None = None) -> Path:
    """A scratch git repo under `tmp_path`; optionally a committed config file."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    if committed is not None:
        cfg_dir = root / ".three-pillars"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps(committed, indent=2) + "\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t12@test.local")
    _git(root, "config", "user.name", "T12 Fixture")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


def _config(root: Path) -> Path:
    return root / ".three-pillars" / "config.json"


def _run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True, text=True, check=False, env=dict(CLEAN_ENV),
    )


# --- load_repo_config: source selection ------------------------------------

def test_load_worktree_source_sees_uncommitted_edit(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    cfg = {"schema_version": 1, "ci": {"expects_github_checks": False}}
    _config(root).write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    got = rcl.load_repo_config(root, source="worktree")
    assert got.config == cfg
    assert got.status == "ok" and got.warnings == []


def test_load_head_source_sees_only_committed_file(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    _config(root).write_text(
        json.dumps({"schema_version": 1, "review": {"expects_copilot": False}}) + "\n",
        encoding="utf-8")
    got = rcl.load_repo_config(root, source="head")
    assert got.config == {"schema_version": 1}
    assert got.status == "ok"


# --- load_repo_config: degradation, never raises ----------------------------

def test_load_absent_file(tmp_path):
    root = _repo(tmp_path, committed=None)
    for source in ("worktree", "head"):
        got = rcl.load_repo_config(root, source=source)
        assert got.config == {}
        assert got.status == "absent"
        assert len(got.warnings) == 1 and got.warnings[0]


def test_load_bad_json_is_unreadable(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    _config(root).write_text("{ not json\n", encoding="utf-8")
    got = rcl.load_repo_config(root, source="worktree")
    assert got.config == {} and got.status == "unreadable"
    assert len(got.warnings) == 1


def test_load_non_object_is_unreadable(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    _config(root).write_text("[1, 2]\n", encoding="utf-8")
    got = rcl.load_repo_config(root, source="worktree")
    assert got.config == {} and got.status == "unreadable"


def test_load_os_unreadable_is_unreadable(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    path = _config(root)
    path.chmod(0o000)
    try:
        got = rcl.load_repo_config(root, source="worktree")
    finally:
        path.chmod(0o644)
    assert got.config == {} and got.status == "unreadable"


def test_load_degrades_per_key_keeps_siblings(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    cfg = {
        "schema_version": 1,
        "review": {
            "require_review_proof": "no",  # not in the schema: dropped alone
            "automation_identities": ["ci-bot[bot]"],
            "ci_gone_away": True,
        },
        "ci": {"expects_github_checks": True},
    }
    _config(root).write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    got = rcl.load_repo_config(root)
    assert got.status == "ok"
    assert got.config["review"]["automation_identities"] == ["ci-bot[bot]"]
    assert "require_review_proof" not in got.config["review"]
    assert "ci_gone_away" not in got.config["review"]
    assert got.config["ci"] == {"expects_github_checks": True}
    assert len(got.warnings) == 2
    assert all(w.startswith("config: dropped ") for w in got.warnings)


def test_load_unknown_review_key_keeps_siblings(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    cfg = {
        "schema_version": 1,
        "review": {"some_future_key": "value", "expects_copilot": False},
    }
    _config(root).write_text(json.dumps(cfg) + "\n", encoding="utf-8")

    # source="worktree": the uncommitted edit is read; the unknown key is
    # pruned with a warning and its valid sibling survives.
    got = rcl.load_repo_config(root, source="worktree")
    assert got.status == "ok", f"UNKNOWN-KEY-PRUNE[worktree]: status {got.status!r}"
    assert "review" in got.config, (
        "UNKNOWN-KEY-PRUNE[worktree]: unknown-key prune dropped the review block")
    assert got.config["review"] == {"expects_copilot": False}, (
        "UNKNOWN-KEY-PRUNE[worktree]: review siblings not kept exactly")
    assert any("some_future_key" in w for w in got.warnings), (
        "UNKNOWN-KEY-PRUNE[worktree]: pruned key not named in a warning")
    default = rcl.load_repo_config(root)
    assert default.config == got.config, (
        "UNKNOWN-KEY-PRUNE[default]: default read differs from the working tree")

    # source="head": commit a DIFFERENT config (another unknown key, a distinct
    # sibling value, the sibling now BEFORE the unknown key), then dirty the
    # working tree again — HEAD's block is read, pruned the same way, and is
    # observably not the working tree's.
    head_cfg = {
        "schema_version": 1,
        "review": {"expects_copilot": True, "head_only_future_key": 1},
    }
    _config(root).write_text(json.dumps(head_cfg) + "\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "head config")
    _config(root).write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    got = rcl.load_repo_config(root, source="head")
    assert got.status == "ok", f"UNKNOWN-KEY-PRUNE[head]: status {got.status!r}"
    assert "review" in got.config, (
        "UNKNOWN-KEY-PRUNE[head]: unknown-key prune dropped the review block")
    assert got.config["review"] == {"expects_copilot": True}, (
        "UNKNOWN-KEY-PRUNE[head]: review siblings not kept exactly from HEAD")
    assert any("head_only_future_key" in w for w in got.warnings), (
        "UNKNOWN-KEY-PRUNE[head]: pruned key not named in a warning")


def test_load_schema_version_mismatch_keeps_status_ok(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    _config(root).write_text(
        json.dumps({"schema_version": 2, "ci": {"expects_github_checks": False}}) + "\n",
        encoding="utf-8")
    got = rcl.load_repo_config(root)
    # A fatal schema_version failure: status stays "ok"; the reader tells this
    # apart by the empty config plus the upgrade warning.
    assert got.status == "ok"
    assert got.config == {}
    assert len(got.warnings) == 1 and "schema_version" in got.warnings[0]


def test_load_not_a_git_repo_never_raises(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / ".three-pillars").mkdir()
    (root / ".three-pillars" / "config.json").write_text(
        '{"schema_version": 1}\n', encoding="utf-8")
    got = rcl.load_repo_config(root, source="head")
    assert got.config == {} and got.status == "absent"
    got = rcl.load_repo_config(root, source="worktree")
    assert got.config == {"schema_version": 1} and got.status == "ok"


def test_config_load_is_namedtuple():
    assert isinstance(rcl.ConfigLoad, type(namedtuple("T", ["a"])))


# --- update_config: atomic write, loud failures -----------------------------

def test_update_config_creates_intermediate_block_and_writes(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    rcl.update_config(root, "ci.expects_github_checks", False)
    assert json.loads(_config(root).read_text(encoding="utf-8")) == {
        "schema_version": 1, "ci": {"expects_github_checks": False}}


def test_update_config_atomic_on_failure_leaves_no_partial(tmp_path, monkeypatch):
    root = _repo(tmp_path, committed={"schema_version": 1})
    before = _config(root).read_bytes()

    def boom(*_a, **_k):
        raise RuntimeError("simulated rename failure")

    monkeypatch.setattr(rcl, "os_replace", boom)
    with pytest.raises(ValueError):
        rcl.update_config(root, "ci.expects_github_checks", False)
    assert _config(root).read_bytes() == before
    assert [p for p in (root / ".three-pillars").iterdir() if p.name != "config.json"] == []


def test_update_config_invalid_value_raises_file_untouched(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    before = _config(root).read_bytes()
    with pytest.raises(ValueError) as exc:
        rcl.update_config(root, "fleet.diff_balloon_factor", 0.5)
    assert "diff_balloon_factor" in str(exc.value)
    assert _config(root).read_bytes() == before


def test_update_config_unknown_key_raises_file_untouched(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    before = _config(root).read_bytes()
    with pytest.raises(ValueError) as exc:
        rcl.update_config(root, "ci.no_such_key", 1)
    assert "no_such_key" in str(exc.value)
    assert _config(root).read_bytes() == before


def test_update_config_unreadable_file_raises(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    _config(root).write_text("{ bad json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        rcl.update_config(root, "ci.expects_github_checks", False)


def test_update_config_bad_schema_version_raises_file_untouched(tmp_path):
    root = _repo(tmp_path, committed={
        "schema_version": 2, "ci": {"expects_github_checks": False}})
    before = _config(root).read_bytes()
    with pytest.raises(ValueError) as exc:
        rcl.update_config(root, "ci.expects_github_checks", False)
    assert "schema_version" in str(exc.value)
    assert _config(root).read_bytes() == before


# --- update_config: absent file seeds, never half-creates -------------------

def test_update_config_absent_file_seeds(tmp_path):
    root = _repo(tmp_path, committed=None)
    assert not _config(root).exists()
    rcl.update_config(root, "ci.expects_github_checks", False)
    assert json.loads(_config(root).read_text(encoding="utf-8")) == {
        "schema_version": 1, "ci": {"expects_github_checks": False}}


def test_update_config_absent_file_invalid_value_creates_nothing(tmp_path):
    root = _repo(tmp_path, committed=None)
    with pytest.raises(ValueError):
        rcl.update_config(root, "fleet.diff_balloon_factor", 0.5)
    assert not (root / ".three-pillars").exists()


# --- the `set` CLI ------------------------------------------------------------

def test_cli_set_valid_value_exits_zero(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    proc = _run_cli("set", "ci.expects_github_checks", "false", "--repo", str(root))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(_config(root).read_text(encoding="utf-8"))[
        "ci"]["expects_github_checks"] is False


def test_cli_set_invalid_value_exits_one_file_untouched(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    before = _config(root).read_bytes()
    proc = _run_cli("set", "fleet.diff_balloon_factor", "0.5", "--repo", str(root))
    assert proc.returncode == 1
    assert proc.stderr.strip()
    assert _config(root).read_bytes() == before


def test_cli_set_non_json_value_exits_one(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 1})
    proc = _run_cli("set", "ci.expects_github_checks", "not-a-json", "--repo", str(root))
    assert proc.returncode == 1
    assert proc.stderr.strip()


def test_cli_set_bad_schema_version_file_exits_one(tmp_path):
    root = _repo(tmp_path, committed={"schema_version": 2})
    before = _config(root).read_bytes()
    proc = _run_cli("set", "ci.expects_github_checks", "false", "--repo", str(root))
    assert proc.returncode == 1
    assert _config(root).read_bytes() == before
